# Déploiement Azure — agent0

Première version déployée sur **Azure Container Apps**, mise à jour en continu par **GitHub Actions** à chaque push sur `main`.

## Architecture

```text
Internet
   │
   ▼
agent0-web   (nginx : front Vite + proxy /api/*)   ← ingress PUBLIC
   │
   ▼
agent0-api   (FastAPI + LangGraph)                 ← ingress interne
   │
   ▼
agent0-mcp   (Spring Boot MCP server)              ← ingress interne
   │
   ▼
BoondManager API
```

- Le front appelle `/api/*` sur sa propre origine ; nginx proxifie vers `agent0-api` en interne → pas de CORS, pas d'URL d'API à configurer côté front.
- `agent0-api` et `agent0-mcp` ne sont **pas accessibles depuis Internet** (ingress interne à l'environnement Container Apps).
- Les images sont stockées dans un **Azure Container Registry** (ACR) ; les apps les tirent via une identité managée (pas de mot de passe).
- GitHub Actions s'authentifie via **OIDC** (federated credentials) : aucun secret Azure longue durée dans GitHub.
- `minReplicas: 0` partout → coût quasi nul au repos (scale-to-zero, démarrage à froid de quelques secondes au premier appel).

## Valeurs par défaut de la v1 (volontairement sûres)

| Réglage | Valeur | Effet |
|---|---|---|
| `USE_MOCK_MCP` | `true` | agent-api sert des résultats mock, ne touche pas BoondManager |
| `USE_LLM_PLANNER` | `false` | planificateur déterministe, pas de clé LLM requise |
| `VITE_DEV_MODE` | `true` | connexion Microsoft (MSAL) contournée dans le front |

Rien de sensible n'est exposé tant que ces valeurs ne sont pas changées (voir « Passer en mode réel »).

## Mise en route (une seule fois)

1. Installer l'[Azure CLI](https://aka.ms/installazurecli) puis se connecter :

   ```powershell
   az login
   ```

2. (Optionnel mais recommandé) Installer [GitHub CLI](https://cli.github.com/) et `gh auth login` — le script pourra alors configurer les secrets GitHub tout seul.

3. Depuis la racine du repo :

   ```powershell
   powershell -ExecutionPolicy Bypass -File infra\azure\provision.ps1
   ```

   Le script : crée le groupe de ressources `rg-agent0` (France Central), l'ACR, l'environnement Container Apps, construit les 3 images dans le cloud (`az acr build`, pas besoin de Docker en local), déploie les 3 apps, crée l'application Entra pour GitHub Actions et pousse les secrets/variables dans le repo. Il affiche l'URL publique du front à la fin.

4. C'est tout. Chaque push sur `main` qui touche `apps/agent-api/**`, `apps/mcp-boondmanager/**` ou `apps/web-ui/**` reconstruit et redéploie **uniquement** l'app concernée (workflows `.github/workflows/deploy-*.yml`). On peut aussi lancer un déploiement à la main : onglet *Actions* → workflow → *Run workflow*.

## Secrets / variables GitHub utilisés par le CI/CD

| Nom | Type | Rôle |
|---|---|---|
| `AZURE_CLIENT_ID` | secret | app Entra `github-agent0-deploy` (OIDC) |
| `AZURE_TENANT_ID` | secret | tenant Azure |
| `AZURE_SUBSCRIPTION_ID` | secret | abonnement cible |
| `AZURE_RESOURCE_GROUP` | variable | `rg-agent0` |
| `ACR_NAME` | variable | nom du registre (généré, ex. `cragent0abc123`) |

## Passer en mode réel (BoondManager + LLM)

Quand tu veux brancher les vraies données :

```powershell
# Secrets du MCP server
az containerapp secret set -n agent0-mcp -g rg-agent0 --secrets boond-jwt-client=<JWT_CLIENT>
az containerapp update -n agent0-mcp -g rg-agent0 --set-env-vars BOONDMANAGER_BASE_URL=<URL_API_BOOND>

# Agent API : désactiver le mock, activer le LLM
az containerapp secret set -n agent0-api -g rg-agent0 --secrets llm-api-key=<CLE_API>
az containerapp update -n agent0-api -g rg-agent0 --set-env-vars USE_MOCK_MCP=false USE_LLM_PLANNER=true
```

Pour activer la vraie connexion Microsoft dans le front : configurer `apps/web-ui/msalConfig.js` (clientId/tenantId + redirectUri = URL publique du front), passer `--build-arg VITE_DEV_MODE="false"` dans `.github/workflows/deploy-web-ui.yml`, et pousser sur `main`.

## Exploitation courante

```powershell
# Logs en direct
az containerapp logs show -n agent0-api -g rg-agent0 --follow

# État / URL publique
az containerapp show -n agent0-web -g rg-agent0 --query properties.configuration.ingress.fqdn -o tsv

# Revenir à une image précédente (tag = SHA du commit)
az containerapp update -n agent0-api -g rg-agent0 --image <ACR>.azurecr.io/agent0/agent-api:<sha>
```

## Coûts (ordre de grandeur)

- Container Apps en consommation avec scale-to-zero : ~0 € au repos, facturation à la seconde d'activité.
- ACR Basic : ~5 €/mois.
- Log Analytics : quelques €/mois selon le volume de logs (rétention 30 jours).
