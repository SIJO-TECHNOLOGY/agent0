# Infrastructure

- `azure/` — Azure Container Apps deployment: Bicep template, one-time provisioning script, and runbook. See [azure/README.md](azure/README.md).
- `docker/`, `compose/`, `scripts/` — placeholders for local development tooling.

Each app builds from its own Dockerfile (`apps/<app>/Dockerfile`). Continuous deployment runs from `.github/workflows/deploy-*.yml` on every push to `main`.
