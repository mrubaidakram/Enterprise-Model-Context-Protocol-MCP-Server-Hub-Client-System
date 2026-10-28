# Enterprise MCP Server Hub & Client System

A Python MCP Streamable HTTP server that exposes narrowly scoped, OAuth-protected read tools for PostgreSQL, Redis, allowlisted web pages, and browser page inspection. The tool surface is intentionally read-only. This repository does not issue OAuth tokens; it verifies opaque bearer tokens through an OAuth 2.0 introspection endpoint.

## Architecture and workflow

```mermaid
flowchart LR
  Agent[LLM agent / MCP client] -->|Bearer token, Streamable HTTP| Hub[FastAPI host + MCP server]
  Hub -->|RFC 7662 introspection| OAuth[Enterprise OAuth authorization server]
  OAuth -->|active, audience, scope, expiry| Hub
  Hub -->|fixed parameterized SELECT| PG[(PostgreSQL read-only role)]
  Hub -->|public namespace GET| Redis[(Redis)]
  Hub -->|HTTPS allowlist + public DNS check| Web[Approved web host]
  Hub -->|HTTPS allowlist + browser route limits| Browser[Playwright Chromium]
  Hub --> Health[/health]
```

An MCP client sends a request to `/mcp`. The server validates the token with the configured authorization server and requires the `mcp:invoke` scope and matching resource audience. Each tool applies its own input and destination limits before access. `/health` is a liveness route and does not prove that dependencies or OAuth are ready.

## Tools

| Tool | Access |
| --- | --- |
| `database_identity` | Reports current database and role. |
| `recent_orders` | Runs a fixed query against `public.orders`, with a bounded limit. |
| `read_public_cache` | Reads only `public:<key>` in Redis. |
| `fetch_allowed_page` | Fetches HTTPS text from `ALLOWED_WEB_HOSTS`, disallows redirects, caps bytes. |
| `inspect_browser_page` | Reads page title and visible text from `ALLOWED_BROWSER_HOSTS`; no clicking, typing, or downloads. |

The orders tool requires a `public.orders(id, created_at, status)` table. Create the database and `mcp_readonly` role through your database administration process, then apply `infra/schema.sql` as a database administrator (adjust the database name and role first). Adapt the fixed query to your schema before enabling that tool. Configure the application credentials with a role that has only `CONNECT` and `SELECT` permissions for intended tables.

## Run locally

Python 3.11 or newer is recommended.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set real development values in `.env`, including the OAuth issuer, introspection endpoint, client credentials, resource URL, and host allowlists. Do not commit `.env`. Install browser binaries only if browser inspection is needed:

```sh
playwright install chromium
set -a; source .env; set +a
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Connect an MCP-compatible client to `http://127.0.0.1:8000/mcp` and provide a valid bearer token. The OAuth authorization server must issue tokens whose introspection response includes `active`, `exp`, `aud`, `sub`, `client_id`, and `scope`; the audience must contain the exact configured `MCP_RESOURCE_URL`.

The included CLI client can list tools or call one by name:

```sh
export MCP_ACCESS_TOKEN="token-from-your-authorized-login-flow"
python -m app.client --url http://127.0.0.1:8000/mcp
python -m app.client --tool database_identity
python -m app.client --tool recent_orders --arguments '{"limit":5}'
```

## Operations and limits

- `GET /health` is a liveness endpoint only.
- Introspection is performed on each MCP request through the SDK verifier.
- Database and Redis connections are opened and closed with the MCP server lifespan.
- Web tools require HTTPS and a hostname in the corresponding allowlist. DNS results are checked for public IPs at invocation time; redirects are disabled.
- `MAX_WEB_RESPONSE_BYTES` caps response bodies; extracted text is capped at 20,000 characters.
- OAuth introspection must use TLS outside localhost. Store client secrets in a secret manager in deployed environments.
- The browser tool is a read-only page inspector; arbitrary browsing and side-effecting web actions are out of scope.

See [development guide](docs/DEVELOPMENT.md), [security model](docs/SECURITY.md), and [deployment guide](docs/DEPLOYMENT.md).
