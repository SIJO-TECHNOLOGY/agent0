# Sijo agent0 — one-time Azure provisioning.
#
# Prerequisites:
#   - Azure CLI installed (https://aka.ms/installazurecli) and `az login` done
#   - Rights to create resources + role assignments on the subscription
#   - (optional) GitHub CLI `gh` authenticated, to set repo secrets automatically
#
# Usage (from the repo root):
#   powershell -ExecutionPolicy Bypass -File infra\azure\provision.ps1
#
# After this script succeeds, every push to `main` deploys automatically via
# GitHub Actions (.github/workflows/deploy-*.yml).

param(
    [string]$ResourceGroup = "rg-agent0",
    [string]$Location = "francecentral",
    [string]$BaseName = "agent0",
    [string]$GitHubRepo = "SIJO-TECHNOLOGY/agent0",
    [string]$EntraAppName = "github-agent0-deploy",
    # Use when the operator lacks roleAssignments/write (i.e. is not Owner of
    # the resource group): ACR auth falls back to the admin password and the
    # GitHub Actions OIDC setup is skipped. Deploys stay manual
    # (deploy-app.ps1) until an admin grants rights and this script is re-run
    # without the switch.
    [switch]$SkipAdminSteps
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$bicepFile = Join-Path $PSScriptRoot "main.bicep"

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# --- 0. Prerequisites ---------------------------------------------------------
Step "Checking prerequisites"
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Fail "Azure CLI not found. Install it: https://aka.ms/installazurecli then run 'az login'."
}
$useRegistryPassword = if ($SkipAdminSteps) { "true" } else { "false" }
$account = $null
try {
    $accountJson = az account show --output json 2>$null
    if ($LASTEXITCODE -eq 0 -and $accountJson) { $account = $accountJson | ConvertFrom-Json }
} catch {}
if (-not $account) { Fail "Not logged in to Azure. Run 'az login' first." }
$subscriptionId = $account.id
$tenantId = $account.tenantId
Write-Host "Subscription: $($account.name) ($subscriptionId)"

# --- 1. Resource group ---------------------------------------------------------
Step "Creating resource group $ResourceGroup in $Location"
az group create --name $ResourceGroup --location $Location --output none

# --- 2. Phase A: registry + environment (no apps yet) ---------------------------
Step "Deploying base infrastructure (registry, environment)"
$phaseA = az deployment group create `
    --resource-group $ResourceGroup `
    --name "agent0-infra" `
    --template-file $bicepFile `
    --parameters baseName=$BaseName deployApps=false useRegistryPassword=$useRegistryPassword `
    --query "properties.outputs" --output json | ConvertFrom-Json
if (-not $phaseA) { Fail "Base infrastructure deployment failed." }
$acrName = $phaseA.acrName.value
Write-Host "Container registry: $acrName"

# --- 3. Build the three images into ACR (cloud build, no local Docker needed) ---
Step "Building container images in ACR (this takes a few minutes)"
az acr build --registry $acrName --image "$BaseName/agent-api:init" (Join-Path $repoRoot "apps\agent-api")
if ($LASTEXITCODE -ne 0) { Fail "agent-api image build failed." }
az acr build --registry $acrName --image "$BaseName/mcp-boondmanager:init" (Join-Path $repoRoot "apps\mcp-boondmanager")
if ($LASTEXITCODE -ne 0) { Fail "mcp-boondmanager image build failed." }
az acr build --registry $acrName --image "$BaseName/web-ui:init" (Join-Path $repoRoot "apps\web-ui")
if ($LASTEXITCODE -ne 0) { Fail "web-ui image build failed." }

# --- 4. Phase B: the three container apps ---------------------------------------
Step "Deploying the container apps"
$phaseB = az deployment group create `
    --resource-group $ResourceGroup `
    --name "agent0-apps" `
    --template-file $bicepFile `
    --parameters baseName=$BaseName deployApps=true imageTag=init useRegistryPassword=$useRegistryPassword `
    --query "properties.outputs" --output json | ConvertFrom-Json
if (-not $phaseB) { Fail "Container apps deployment failed." }
$webUrl = $phaseB.webUrl.value

# --- 5. Entra app + OIDC federated credential for GitHub Actions ----------------
if ($SkipAdminSteps) {
    Step "Skipping GitHub Actions OIDC setup (-SkipAdminSteps)"
    Write-Host "CI/CD is NOT active. Deploy manually with infra\azure\deploy-app.ps1." -ForegroundColor Yellow
    Write-Host "Once an admin grants you Owner on $ResourceGroup, re-run this script WITHOUT -SkipAdminSteps."
    Step "Done"
    Write-Host "Web UI URL: $webUrl" -ForegroundColor Green
    exit 0
}
Step "Configuring GitHub Actions OIDC access"
$appId = az ad app list --display-name $EntraAppName --query "[0].appId" --output tsv
if (-not $appId) {
    $appId = az ad app create --display-name $EntraAppName --query appId --output tsv
    Write-Host "Created Entra application $EntraAppName ($appId)"
} else {
    Write-Host "Reusing Entra application $EntraAppName ($appId)"
}
$spId = az ad sp list --filter "appId eq '$appId'" --query "[0].id" --output tsv
if (-not $spId) {
    $spId = az ad sp create --id $appId --query id --output tsv
}

$fedName = "github-main"
$existingFed = az ad app federated-credential list --id $appId --query "[?name=='$fedName'] | length(@)" --output tsv
if ($existingFed -eq "0") {
    $fedParams = @{
        name      = $fedName
        issuer    = "https://token.actions.githubusercontent.com"
        subject   = "repo:${GitHubRepo}:ref:refs/heads/main"
        audiences = @("api://AzureADTokenExchange")
    } | ConvertTo-Json -Compress
    $fedFile = Join-Path $env:TEMP "agent0-fed-cred.json"
    Set-Content -Path $fedFile -Value $fedParams -Encoding ascii
    az ad app federated-credential create --id $appId --parameters "@$fedFile" --output none
    Remove-Item $fedFile
    Write-Host "Federated credential created for repo:${GitHubRepo}:ref:refs/heads/main"
}

$rgScope = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup"
az role assignment create `
    --assignee-object-id $spId `
    --assignee-principal-type ServicePrincipal `
    --role Contributor `
    --scope $rgScope --output none

# --- 6. GitHub repository secrets/variables --------------------------------------
Step "GitHub repository configuration"
$hasGh = Get-Command gh -ErrorAction SilentlyContinue
if ($hasGh) {
    gh secret set AZURE_CLIENT_ID --body $appId --repo $GitHubRepo
    gh secret set AZURE_TENANT_ID --body $tenantId --repo $GitHubRepo
    gh secret set AZURE_SUBSCRIPTION_ID --body $subscriptionId --repo $GitHubRepo
    gh variable set AZURE_RESOURCE_GROUP --body $ResourceGroup --repo $GitHubRepo
    gh variable set ACR_NAME --body $acrName --repo $GitHubRepo
    Write-Host "GitHub secrets and variables set on $GitHubRepo."
} else {
    Write-Host "GitHub CLI not found. Set these manually in GitHub → Settings → Secrets and variables → Actions:" -ForegroundColor Yellow
    Write-Host "  Secrets:"
    Write-Host "    AZURE_CLIENT_ID        = $appId"
    Write-Host "    AZURE_TENANT_ID        = $tenantId"
    Write-Host "    AZURE_SUBSCRIPTION_ID  = $subscriptionId"
    Write-Host "  Variables:"
    Write-Host "    AZURE_RESOURCE_GROUP   = $ResourceGroup"
    Write-Host "    ACR_NAME               = $acrName"
}

Step "Done"
Write-Host "Web UI URL: $webUrl" -ForegroundColor Green
Write-Host "Every push to 'main' now redeploys the changed app(s) automatically."
