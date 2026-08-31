# Infrastructure

- `azure/` — Azure Container Apps deployment: the documented production topology and the image-only deploy script. There is no infrastructure-as-code; the portal is authoritative and [azure/README.md](azure/README.md) is the written source of truth. See it before touching anything in `rg-agent0`.
- `docker/`, `compose/`, `scripts/` — placeholders for local development tooling.

Each app builds from its own Dockerfile (`apps/<app>/Dockerfile`). Continuous deployment runs from `.github/workflows/deploy-*.yml` on every push to `main`.
