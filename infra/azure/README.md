# Infrastructure Azure — agent0

> **L'infrastructure est gérée depuis le portail Azure, pas par de
> l'infrastructure-as-code.** Ce document est la source de vérité : il
> décrit ce qui tourne réellement, vérifié via `az` le 2026-08-26.
> Le déploiement de code, lui, est automatisé (voir [Déploiement](#déploiement)).

Un template Bicep (`main.bicep`) et son script (`provision.ps1`) ont
existé ici et ont été supprimés : ils décrivaient un environnement
**différent** de celui en production — un autre environnement Container
Apps, un autre registre, un autre modèle d'identité. Les exécuter aurait
tenté de déplacer les applications. Le détail est dans la PR qui les a
retirés. Ne les réintroduisez pas sans les valider par
`az deployment group what-if` contre `rg-agent0`.

## Topologie

```text
Internet
   │
   ▼  agent0.sijo.fr
agent0-web   nginx : front Vite + proxy /api/*        ingress PUBLIC
   │
   ▼  AGENT_API_UPSTREAM
agent0-api   FastAPI + LangGraph                      ingress INTERNE
   │
   ▼  MCP_SERVER_URL = http://agent0-mcp/mcp
agent0-mcp   Spring Boot, serveur MCP                 ingress INTERNE
   │
   ▼
BoondManager API
```

Le front appelle `/api/*` sur sa propre origine et nginx proxifie vers
`agent0-api` : pas de CORS à configurer, et l'API n'est jamais exposée
directement sur Internet.

## Inventaire réel — groupe `rg-agent0` (France Central)

### Ressources utilisées

| Ressource | Type | Rôle |
|---|---|---|
| `agent0-web` | Container App | Front + proxy. Ingress public, domaine `agent0.sijo.fr` |
| `agent0-api` | Container App | Agent API. Ingress interne, port 8000 |
| `agent0-mcp` | Container App | Serveur MCP. Ingress interne |
| `env-agent0` | Managed Environment | Environnement des trois applications |
| `agent0acr` | Container Registry | Images `agent0/agent-api`, `agent0/mcp-boondmanager`, `agent0/web-ui` |
| `agent0store2026` | Storage Account | Tables `agent0conversations`, `agent0messages` |
| `log-agent0` | Log Analytics | Logs des applications |

### Ressources orphelines

Elles existent dans le groupe mais **rien ne s'en sert** (vérifié) :

| Ressource | Constat |
|---|---|
| `cae-agent0` | Managed Environment vide — aucune application |
| `cragent04d6lwwwnnnk64` | Registry contenant d'anciennes images, non référencé |
| `id-agent0` | Identité user-assigned — aucune application ne l'utilise |

Vestiges d'un déploiement antérieur. Leur suppression est possible mais
n'a pas été faite : à décider et à exécuter délibérément.

### Hors périmètre

L'application `home` (domaine `home.sijo.fr`) partage le groupe de
ressources mais n'appartient pas à agent0.

## Configuration des applications

### `agent0-api`

Identité **SystemAssigned**. Réplicas **1 → 10**. 0,5 vCPU, 1 Gio de
mémoire, 2 Gio de stockage éphémère.

| Variable | Valeur | Note |
|---|---|---|
| `USE_MOCK_MCP` | `false` | données réelles |
| `MCP_SERVER_URL` | `http://agent0-mcp/mcp` | nom interne, pas le FQDN |
| `USE_LLM_PLANNER` | `true` | |
| `LLM_PROVIDER` / `LLM_MODEL` | `openai` / `gpt-5.2` | |
| `LLM_API_KEY` | secret `llm-key` | |
| `CONVERSATION_STORE` | `azure_table` | historique durable |
| `AZURE_STORAGE_ACCOUNT_URL` | `https://agent0store2026.table.core.windows.net` | |

**Non défini, donc à la valeur par défaut du code :**

- `ENABLE_AUTH` → `false`. Les routes `/api/*` ne vérifient aucun jeton
  Entra. Le risque est contenu par l'ingress interne, mais la
  vérification d'identité repose entièrement sur le front. Le code de
  validation existe et est testé : l'activer demande `ENABLE_AUTH`,
  `ENTRA_TENANT_ID` et `ENTRA_CLIENT_ID`. Voir [Écarts connus](#écarts-connus).
- `MCP_CACHE_*` → le cache MCP est **actif** (activé par défaut,
  ADR-013). Aucune variable n'est nécessaire pour en bénéficier.

### `agent0-mcp`

Identité SystemAssigned. Réplicas **1 → 1**.
Variables : `BOONDMANAGER_BASE_URL`, `BOONDMANAGER_JWT_CLIENT`.

### `agent0-web`

Identité SystemAssigned. Réplicas **1 → 10**. Le minimum était à 0
(scale-to-zero) jusqu'au 2026-08-31 : chaque visite après 5 minutes
d'inactivité subissait un cold start de 30 s à 1 min, d'où le passage
à 1. Variable : `AGENT_API_UPSTREAM`. Domaine `agent0.sijo.fr` avec
certificat managé.

## Identités et rôles

Les trois applications utilisent une identité **SystemAssigned**.
L'identité de `agent0-api` (`c994fbb6-074d-42b6-8c70-cf95c842d578`)
porte deux attributions :

| Rôle | Portée |
|---|---|
| `AcrPull` | `agent0acr` |
| `Storage Table Data Contributor` | `agent0store2026` |

C'est ce second rôle qui permet la persistance des conversations sans
aucun secret de connexion. Les tables sont créées automatiquement par
l'application au démarrage.

Note : le rôle sur les données n'est attribué qu'à l'application. Un
compte utilisateur, même propriétaire de l'abonnement, ne peut pas lire
le contenu des tables sans se donner explicitement le rôle — c'est le
comportement souhaitable.

## Déploiement

**Automatique.** Chaque push sur `main` touchant `apps/agent-api/**`,
`apps/mcp-boondmanager/**` ou `apps/web-ui/**` déclenche le workflow
correspondant dans `.github/workflows/`. Le workflow construit l'image
dans l'ACR (`az acr build`) puis met à jour l'application
(`az containerapp update --image`).

**Important : le déploiement ne touche que l'image.** Ni les variables
d'environnement, ni les secrets, ni le scaling ne sont modifiés. Un
déploiement ne peut donc pas casser la configuration.

**Manuel**, depuis un poste avec `az login` :

```powershell
powershell -ExecutionPolicy Bypass -File infra\azure\deploy-app.ps1
```

Ce script suit exactement le même principe (image seulement).

## Exploitation courante

```powershell
# Logs en direct
az containerapp logs show -n agent0-api -g rg-agent0 --follow

# Configuration effective d'une application
az containerapp show -n agent0-api -g rg-agent0 `
  --query "properties.template.containers[0].env" -o table

# Modifier une variable (crée une nouvelle révision)
az containerapp update -n agent0-api -g rg-agent0 --set-env-vars CLE=valeur

# Modifier un secret
az containerapp secret set -n agent0-api -g rg-agent0 --secrets llm-key=<valeur>

# Historique des révisions et retour arrière
az containerapp revision list -n agent0-api -g rg-agent0 -o table
az containerapp revision activate -n agent0-api -g rg-agent0 --revision <nom>

# Revenir à une image précédente (tag = SHA du commit)
az containerapp update -n agent0-api -g rg-agent0 `
  --image agent0acr.azurecr.io/agent0/agent-api:<sha>
```

Toute modification de configuration crée une **nouvelle révision**
Container Apps : une erreur se rattrape en réactivant la précédente.

## Écarts connus

À traiter quand vous le jugerez utile — aucun n'est bloquant aujourd'hui.

1. **`ENABLE_AUTH` non défini** sur `agent0-api`. L'API accepte toute
   requête venant de l'environnement Container Apps. Atténué par
   l'ingress interne, mais c'est une défense en profondeur qui manque
   alors que le code existe.
2. **Ressources orphelines** (`cae-agent0`, `cragent04d6lwwwnnnk64`,
   `id-agent0`) — coût faible mais bruit permanent dans le groupe.
3. **Modèle divergent du dépôt** : `LLM_MODEL` vaut `gpt-5.2` en
   production contre `gpt-5.4` dans les `.env.example`.

## Reconstruire depuis zéro

Si le groupe de ressources devait être recréé, dans l'ordre :

1. Groupe de ressources `rg-agent0` en France Central.
2. Log Analytics, Container Registry, Managed Environment.
3. Compte de stockage (Table Storage suffit).
4. Les trois Container Apps depuis les images de l'ACR, avec le
   découpage d'ingress du schéma ci-dessus (seul le web est public).
5. Activer l'identité SystemAssigned sur les trois, puis attribuer à
   celle de l'API : `AcrPull` sur le registre et
   `Storage Table Data Contributor` sur le compte de stockage.
6. Renseigner les variables et secrets listés plus haut.
7. Domaine personnalisé `agent0.sijo.fr` sur `agent0-web` + certificat
   managé.
8. Vérifier : `GET /api/health` sur l'API doit rendre
   `dependencies.mcp.status = "connected"`.

## Coûts (ordre de grandeur)

- Container Apps : les trois applications gardent un réplica minimum,
  donc facturation continue et non scale-to-zero. Le web y est passé
  le 2026-08-31 pour éliminer le cold start au chargement de la page.
- ACR Basic : ~5 €/mois. Table Storage : négligeable à ce volume.
- Log Analytics : quelques €/mois selon le volume, rétention 30 jours.
