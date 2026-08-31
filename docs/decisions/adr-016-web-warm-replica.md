# ADR-016: Keep one warm replica for the public web front

## Status

Accepted (2026-08-31)

## Context

`agent0-web` is the only publicly reachable Container App: an nginx that
serves the built Vite bundle and proxies `/api/*` to the internal
`agent0-api` (see [infra/azure/README.md](../../infra/azure/README.md)).
It was configured with `minReplicas: 0`, `maxReplicas: 10`, and a
`cooldownPeriod` of 300 s.

Scale-to-zero means Azure stops the replica after five minutes without
traffic. The next visitor then pays a **cold start** — replica
scheduling, image pull, nginx start — before the first byte of HTML is
served. Users reported 30 s to 1 min on `https://agent0.sijo.fr/`.

Three things made this the wrong default here:

- **The usage pattern is the worst case for scale-to-zero.** A handful
  of recruiters open the app a few times a day with long gaps between
  visits. Almost every genuine visit landed on a stopped container,
  while a reload immediately afterwards was instant — which is why the
  symptom read as intermittent rather than systematic.
- **The delay hit the front door, before any product value.** The user
  is staring at a blank page during a cold start; nothing about the
  wait is attributable to search work. `agent0-api` and `agent0-mcp`
  already run `minReplicas: 1`, so the backend never had this
  behaviour — the whole delay came from the one app that greets the
  user.
- **The saving was marginal.** The container is a static-file nginx,
  the cheapest workload in the environment, and it only saved money
  during idle periods — precisely the periods where the next request
  pays for it.

## Decision

`agent0-web` runs with **`minReplicas: 1`**. `maxReplicas` stays at 10,
so traffic-driven scale-out is unchanged.

Applied directly to the live application (infrastructure here is
portal-managed, not IaC), creating revision `agent0-web--0000012`:

```bash
az containerapp update -n agent0-web -g rg-agent0 --min-replicas 1
```

`infra/azure/README.md` is the source of truth for what actually runs
and records the new value together with the reason.

## Measured Outcome

| | First response on `https://agent0.sijo.fr/` |
|---|---|
| Before | 30 s – 1 min after an idle period |
| After | HTTP 200 in **0.40 s** |

The "after" number is a `curl` measurement taken once the new revision
was live. The "before" is user-reported and corroborated by the
configuration (`minReplicas: 0`, 300 s cooldown) rather than
instrumented — no synthetic monitoring exists on this endpoint, and
adding one was out of scope for the fix.

## Consequences

- The first visit of the day no longer pays a startup penalty. This is
  the entire user-visible benefit, and it is confined to page load:
  search latency is a separate budget, governed by the LLM and MCP
  round-trips (ADR-013 caching, and the cost profile in the
  architecture document).
- One small nginx replica is now billed continuously instead of only
  under traffic. At this workload size the difference is a few euros a
  month — accepted deliberately in exchange for the latency.
- **"Never zero" is not "never a cold start."** Scaling out past one
  replica still starts containers, and every deployment activates a new
  revision that must boot. A user can still meet a slow first request
  right after a deploy.
- Deployments only update the image and never touch scaling, so this
  setting survives future releases; it changes only if someone edits
  scaling explicitly.
- Reverting is one command (`--min-replicas 0`) or reactivating the
  previous revision, should the cost/latency tradeoff ever be judged
  differently.
- `agent0-api` and `agent0-mcp` were already warm and are untouched;
  all three applications now keep a minimum replica, so no part of the
  chain is scale-to-zero.
