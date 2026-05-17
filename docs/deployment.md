# Deployment

## Docker Compose

The full stack is defined in `compose.yml`. All services start with a single command:

```bash
docker compose up
```

### Service Dependencies

```
postgres (healthy) ─┐
redis (healthy) ────┤
minio (healthy) ────┤
                    ├── minio-setup (completed) ─── migrate (completed) ─── api ─── frontend
                    │                                                   └── worker
                    │
prometheus ─────────┤
loki ── promtail    ├── grafana
tempo ──────────────┘
```

Health checks ensure services start in the correct order:
- **postgres** — `pg_isready` check every 5s
- **redis** — `redis-cli ping` every 5s
- **minio** — TCP check on port 9000
- **minio-setup** — must complete (creates bucket and attempts CORS config) before API starts

### Secrets

The `.env` file is read at runtime by Docker Compose but is excluded from the Docker build context (via `.dockerignore`). Secrets are never baked into images.

Required secrets: `DB_ADMIN_PASSWORD`, `DB_PASSWORD`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `PINECONE_API_KEY`, plus at least one LLM provider API key.

### Database Migrations

Docker Compose uses a dedicated `migrate` service that runs `uv run alembic upgrade head` after PostgreSQL, Redis, MinIO, and `minio-setup` are healthy. The API and worker wait for that service to complete before starting, which avoids concurrent migration races.

The Helm chart also applies migrations before serving traffic:
- `templates/jobs/migrate.yaml` defines a pre-upgrade hook job.
- `templates/api/deployment.yaml` includes a `run-migration` init container before the API container starts.
- The worker does not run migrations itself.

### MinIO Setup

The `minio-setup` init container:
1. Waits for MinIO to accept connections
2. Creates the `agenticrag-documents` bucket
3. Tries to apply CORS configuration from `minio/cors.xml`

Some MinIO builds return `NotImplemented` for bucket CORS. In that case the setup container logs the failure and continues so the rest of the stack can still start.

### Volumes

| Volume | Purpose |
|--------|---------|
| `postgres_data` | Database persistence |
| `redis_data` | Redis persistence (sessions, memory, cache) |
| `minio_data` | Uploaded document files |
| `frontend_node_modules` | Cached node_modules for dev |
| `prometheus_data` | Metric storage |
| `loki_data` | Log storage |
| `tempo_data` | Trace storage |
| `grafana_data` | Dashboard state |

## Scaling

- **API** — stateless (session state is in Redis). Can run multiple instances behind a load balancer.
- **Worker** — stateless ARQ worker. Scale by running additional instances.
- **Frontend** — stateless Next.js. Can run multiple instances.
- **Redis** — single instance. Consider Redis Cluster for high availability.
- **PostgreSQL** — single instance. Consider read replicas for scale.

## GitHub Actions Runners

Optional self-hosted GitHub Actions runner setup lives under `helm/github-runners`.

This uses GitHub's official Actions Runner Controller Helm charts and the official `ghcr.io/actions/actions-runner` image, rather than embedding runner pods into the main application chart. Keep the controller and runner scale set in dedicated namespaces separate from the app release.

## Helm Chart

The application chart lives at `helm/agenticrag` and deploys the API, worker, frontend, PostgreSQL with pgvector, Redis Stack, MinIO, ingress, optional monitoring, Cloudflare tunnel/DDNS helpers, cert-manager resources, and network policies.

Key values:

| Area | Values |
|------|--------|
| Public URLs | `config.frontendUrl`, `config.apiPublicUrl`, `config.minioPublicBaseUrl` |
| CORS | `config.corsAllowedOrigins`, `config.corsAllowLocalhostRegex` |
| API docs | `config.enableApiDocs` |
| Auth cookies | `config.cookieDomain`, generated `COOKIE_SECURE` from ingress TLS |
| Ingestion | `config.documentIngestMode` |
| Secrets | `secrets.*` or `secrets.externalSecret` + `secrets.secretName` |

Production overrides in `helm/agenticrag/values.prod.yaml` set:

| Setting | Value |
|---------|-------|
| Frontend URL | `https://runaxai.com` |
| API URL | `https://api.runaxai.com` |
| MinIO public URL | `https://storage.runaxai.com` |
| CORS origin | `https://runaxai.com` |
| Cookie domain | `runaxai.com` |

Because the backend builds the Google OAuth redirect URI from `FRONTEND_URL`, the production Google callback URL is:

```text
https://runaxai.com/api/auth/callback/google
```

## Syncing Helm Secrets to the Cluster

The CI deploy (`.github/workflows/deploy.yml`) does not read `helm/values-secrets.yaml` from the repo — that file is gitignored. Instead it reads a Kubernetes secret named `helm-values-secrets` in the `arc-runners` namespace, which is a *snapshot* of the local file taken at the moment it was last applied with `kubectl create secret`.

If you edit `helm/values-secrets.yaml` locally and forget to re-apply the cluster secret, the next deploy will keep using the old values. Run:

```bash
./scripts/sync-helm-secrets.sh
```

This shows a diff between the local file and the cluster secret, asks for confirmation, then applies. Use `--check` for a dry run or `--yes` to skip the prompt.

## Adding a New Subdomain (e.g. blog.runaxai.com)

The Cloudflare tunnel uses a `TUNNEL_TOKEN` (see `helm/agenticrag/templates/tunnel/deployment.yaml`), so public hostnames are configured in the Cloudflare Zero Trust dashboard rather than in the chart. Adding a subdomain takes three coordinated changes:

1. **Cloudflare Zero Trust → Tunnels → `<your tunnel>` → Public Hostnames → Add a public hostname:**

   | Field | Value |
   |-------|-------|
   | Subdomain | `blog` |
   | Domain | `runaxai.com` |
   | Service type | `HTTP` |
   | URL | `<release>-frontend:3000` (or the API service for an API subdomain) |

   Cloudflare auto-creates the proxied CNAME `blog.runaxai.com → <tunnel-id>.cfargotunnel.com`.

2. **Add the host to `helm/agenticrag/values.prod.yaml`** under `ingress.hosts` so Traefik accepts the new `Host` header and routes it to the right service.

3. **Frontend routing (subdomain → app route).** `frontend/middleware.ts` inspects the incoming `Host` header. For `blog.runaxai.com`, it rewrites the URL internally to `/blog/*` so the address bar stays clean (`blog.runaxai.com/some-post`) while the route lives at `app/blog/[slug]`.

TLS terminates at Cloudflare's edge, so no cert-manager changes are needed in prod (cert-manager is disabled per `values.prod.yaml`).

## Monitoring Setup

### Prometheus

Prometheus scrapes the API's `/metrics` endpoint. Config at `monitoring/prometheus/prometheus.yml`.

The API exposes both standard HTTP metrics and custom RunaxAI metrics (LLM, tools, agents, orchestration). See [Observability](architecture/observability.md) for the full metrics catalog.

The `/metrics` handler rejects requests carrying public proxy forwarding headers (`X-Forwarded-For` or `X-Real-IP`) so metrics remain intended for direct in-cluster or local Prometheus scraping.

### Loki + Promtail

Promtail scrapes Docker container logs via the Docker socket and ships them to Loki. The app currently writes plain container stdout/stderr logs rather than structured JSON.

Config files:
- `monitoring/promtail/promtail-config.yml`
- `monitoring/loki/loki-config.yml`

### Tempo

OpenTelemetry traces are exported via OTLP HTTP to Tempo on port 4318. Enable with `OTEL_ENABLED=true`.

Config: `monitoring/tempo/tempo-config.yml`

### Grafana

Grafana is pre-provisioned with:
- **Datasources** — Prometheus, Loki, and Tempo (auto-configured)
- **Dashboards** — Economics, Operations, UX & Latency
- **Alert rules** — pre-configured rules (contact points must be set manually)

Default login on a fresh Grafana volume: `admin`/`admin` (configurable via `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`). If the `grafana_data` volume already exists, Grafana keeps the previously stored admin password instead of reapplying the env defaults.

## Rebuild

Only rebuild when dependencies or Dockerfiles change:

```bash
docker compose up --build
```

## Reset

Remove all volumes and start fresh:

```bash
docker compose down -v
```
