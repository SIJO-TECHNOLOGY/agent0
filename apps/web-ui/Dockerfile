# Sijo Web UI — Vite static build served by nginx, /api proxied to agent-api
FROM node:22-alpine AS builder

WORKDIR /build

COPY . .

# The upload context may carry a Windows node_modules/dist (az acr build does
# not always honor .dockerignore); replace with a clean Linux install so the
# vite binary keeps its executable bit.
RUN rm -rf node_modules dist && npm ci

# Same-origin deployment: the UI calls /api/* on its own host and nginx
# proxies to agent-api, so the API base URL is empty in production builds.
# VITE_DEV_MODE defaults to "false": a production image must never ship
# with the Microsoft login bypassed. The Entra ids are required for the
# login to work (public identifiers, not secrets).
ARG VITE_API_URL=""
ARG VITE_DEV_MODE="false"
ARG VITE_ENTRA_CLIENT_ID=""
ARG VITE_ENTRA_TENANT_ID=""
ENV VITE_API_URL=$VITE_API_URL \
    VITE_DEV_MODE=$VITE_DEV_MODE \
    VITE_ENTRA_CLIENT_ID=$VITE_ENTRA_CLIENT_ID \
    VITE_ENTRA_TENANT_ID=$VITE_ENTRA_TENANT_ID
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /build/dist /usr/share/nginx/html

# Upstream resolved at container start via envsubst (nginx docker entrypoint).
ENV AGENT_API_UPSTREAM=http://agent0-api

EXPOSE 80
