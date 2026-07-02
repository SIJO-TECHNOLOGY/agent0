# Sijo Web UI — Vite static build served by nginx, /api proxied to agent-api
FROM node:22-alpine AS builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Same-origin deployment: the UI calls /api/* on its own host and nginx
# proxies to agent-api, so the API base URL is empty in production builds.
ARG VITE_API_URL=""
ARG VITE_DEV_MODE="true"
ENV VITE_API_URL=$VITE_API_URL \
    VITE_DEV_MODE=$VITE_DEV_MODE
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /build/dist /usr/share/nginx/html

# Upstream resolved at container start via envsubst (nginx docker entrypoint).
ENV AGENT_API_UPSTREAM=http://agent0-api

EXPOSE 80
