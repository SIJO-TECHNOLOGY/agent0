// Sijo agent0 — Azure Container Apps infrastructure.
//
// Deployed in two phases by provision.ps1:
//   Phase A (deployApps=false): registry + environment only, so images can
//   be built into the ACR before any container app references them.
//   Phase B (deployApps=true): the three container apps.
//
// Day-to-day updates do NOT go through this template: the GitHub Actions
// workflows build new images and run `az containerapp update`.

@description('Prefix for all resource names.')
param baseName string = 'agent0'

param location string = resourceGroup().location

@description('False on the first pass, before images exist in the registry.')
param deployApps bool = true

@description('Image tag to deploy (CI uses the commit SHA).')
param imageTag string = 'init'

@description('true = apps authenticate to ACR with the admin password instead of a managed identity. Fallback for operators without roleAssignments/write; switch back to false once rights are granted.')
param useRegistryPassword bool = false

// --- BoondManager (MCP server) ---------------------------------------------
@description('BoondManager API base URL. Placeholder is fine while USE_MOCK_MCP=true.')
param boondBaseUrl string = 'https://change-me.example.com'

@secure()
@description('BoondManager JWT client token. Placeholder is fine while USE_MOCK_MCP=true.')
param boondJwtClient string = 'change-me'

// --- Agent API ---------------------------------------------------------------
@description('true = the agent-api serves mock results and never calls the MCP server. Safe default for a first deployment.')
param useMockMcp string = 'true'

@description('true = LLM planner enabled (requires llmApiKey).')
param useLlmPlanner string = 'false'

param llmProvider string = 'anthropic'
param llmModel string = 'claude-sonnet-4-6'

@secure()
param llmApiKey string = 'change-me'

// -----------------------------------------------------------------------------

var acrName = toLower(replace('cr${baseName}${uniqueString(resourceGroup().id)}', '-', ''))
var webAppName = '${baseName}-web'
var apiAppName = '${baseName}-api'
var mcpAppName = '${baseName}-mcp'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${baseName}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: useRegistryPassword
  }
}

resource uai 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${baseName}'
  location: location
}

// AcrPull for the container apps' shared identity.
var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!useRegistryPassword) {
  name: guid(acr.id, uai.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: uai.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${baseName}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

var registryConfig = useRegistryPassword
  ? [
      {
        server: acr.properties.loginServer
        username: acr.name
        passwordSecretRef: 'acr-password'
      }
    ]
  : [
      {
        server: acr.properties.loginServer
        identity: uai.id
      }
    ]

var acrPasswordSecrets = useRegistryPassword
  ? [
      {
        name: 'acr-password'
        value: acr.listCredentials().passwords[0].value
      }
    ]
  : []

// --- MCP BoondManager (internal only) ----------------------------------------

resource mcpApp 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: mcpAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uai.id}': {} }
  }
  dependsOn: [acrPull]
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: false
        targetPort: 8080
        allowInsecure: true
      }
      registries: registryConfig
      secrets: concat(
        [
          { name: 'boond-jwt-client', value: boondJwtClient }
        ],
        acrPasswordSecrets
      )
    }
    template: {
      containers: [
        {
          name: 'mcp-boondmanager'
          image: '${acr.properties.loginServer}/${baseName}/mcp-boondmanager:${imageTag}'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'BOONDMANAGER_BASE_URL', value: boondBaseUrl }
            { name: 'BOONDMANAGER_JWT_CLIENT', secretRef: 'boond-jwt-client' }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

// --- Agent API (internal only) ------------------------------------------------

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: apiAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uai.id}': {} }
  }
  dependsOn: [acrPull]
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: false
        targetPort: 8000
        allowInsecure: true
      }
      registries: registryConfig
      secrets: concat(
        [
          { name: 'llm-api-key', value: llmApiKey }
        ],
        acrPasswordSecrets
      )
    }
    template: {
      containers: [
        {
          name: 'agent-api'
          image: '${acr.properties.loginServer}/${baseName}/agent-api:${imageTag}'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'APP_ENV', value: 'production' }
            { name: 'USE_MOCK_MCP', value: useMockMcp }
            // Safe: mcpApp shares the same deployApps condition.
            #disable-next-line BCP318
            { name: 'MCP_SERVER_URL', value: 'http://${mcpApp.properties.configuration.ingress.fqdn}/mcp' }
            { name: 'USE_LLM_PLANNER', value: useLlmPlanner }
            { name: 'LLM_PROVIDER', value: llmProvider }
            { name: 'LLM_MODEL', value: llmModel }
            { name: 'LLM_API_KEY', secretRef: 'llm-api-key' }
            { name: 'ENABLE_MCP_DEBUG_ENDPOINTS', value: 'false' }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

// --- Web UI (public entry point) -----------------------------------------------

resource webApp 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: webAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uai.id}': {} }
  }
  dependsOn: [acrPull]
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 80
      }
      registries: registryConfig
      secrets: acrPasswordSecrets
    }
    template: {
      containers: [
        {
          name: 'web-ui'
          image: '${acr.properties.loginServer}/${baseName}/web-ui:${imageTag}'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            // Safe: apiApp shares the same deployApps condition.
            #disable-next-line BCP318
            { name: 'AGENT_API_UPSTREAM', value: 'http://${apiApp.properties.configuration.ingress.fqdn}' }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
#disable-next-line BCP318
output webUrl string = deployApps ? 'https://${webApp.properties.configuration.ingress.fqdn}' : ''
