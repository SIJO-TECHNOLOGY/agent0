# Sijo agent0 — manual deployment of one app (or all) to Azure Container Apps.
#
# Builds the image(s) in ACR from the CURRENT local checkout and updates the
# corresponding container app(s). Use this while GitHub Actions CI/CD is not
# active, or to deploy a feature branch without merging to main.
#
# Usage (from the repo root, after `az login`):
#   powershell -ExecutionPolicy Bypass -File infra\azure\deploy-app.ps1                # everything
#   powershell -ExecutionPolicy Bypass -File infra\azure\deploy-app.ps1 -App web-ui   # one app

param(
    [ValidateSet("web-ui", "agent-api", "mcp-boondmanager", "all")]
    [string]$App = "all",
    [string]$ResourceGroup = "rg-agent0",
    [string]$BaseName = "agent0",
    # Pinned on purpose: rg-agent0 also holds an unused legacy registry, and
    # picking "the first one listed" could push images to a registry the apps
    # have no AcrPull role on — a deployment that builds fine and then fails
    # to start. See infra/azure/README.md.
    [string]$AcrName = "agent0acr"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Fail "Azure CLI not found." }

$acrName = az acr show --name $AcrName --resource-group $ResourceGroup --query "name" --output tsv 2>$null
if (-not $acrName) {
    Fail "Container registry '$AcrName' not found in $ResourceGroup. Check the inventory in infra/azure/README.md, or pass -AcrName."
}

# Tag with the current commit (plus -dirty when uncommitted changes exist).
$sha = git -C $repoRoot rev-parse --short HEAD
$dirty = git -C $repoRoot status --porcelain
$tag = if ($dirty) { "$sha-dirty" } else { $sha }

# app folder -> container app name
$apps = [ordered]@{
    "agent-api"         = "$BaseName-api"
    "mcp-boondmanager"  = "$BaseName-mcp"
    "web-ui"            = "$BaseName-web"
}
$targets = if ($App -eq "all") { @($apps.Keys) } else { @($App) }

foreach ($name in $targets) {
    $containerApp = $apps[$name]
    $image = "$BaseName/${name}:$tag"
    Write-Host "`n=== Building $image ===" -ForegroundColor Cyan
    az acr build --registry $acrName --image $image (Join-Path $repoRoot "apps\$name")
    if ($LASTEXITCODE -ne 0) { Fail "$name image build failed." }

    Write-Host "=== Updating $containerApp ===" -ForegroundColor Cyan
    az containerapp update `
        --name $containerApp `
        --resource-group $ResourceGroup `
        --image "$acrName.azurecr.io/$image" --output none
    if ($LASTEXITCODE -ne 0) { Fail "$containerApp update failed." }
    Write-Host "$containerApp deployed with tag $tag" -ForegroundColor Green
}

$webFqdn = az containerapp show --name "$BaseName-web" --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" --output tsv
Write-Host "`nWeb UI: https://$webFqdn" -ForegroundColor Green
