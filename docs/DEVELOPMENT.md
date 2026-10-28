# Development guide

## Layout

- `app/main.py` configures OAuth verification, MCP tools, dependency lifespan, and the ASGI host.
- `.env.example` lists the supported runtime configuration keys.
- `requirements.txt` constrains the supported major versions.

## Add a tool safely

1. Define a typed input model and field bounds for untrusted values.
2. Give the tool a narrow single-purpose name and docstring.
3. Pass the MCP `Context` argument when accessing lifespan-managed resources.
4. Keep database statements fixed and parameterized; do not add arbitrary SQL execution.
5. Apply explicit host allowlists and time/size caps to network calls.
6. Update the README tool table, architecture, and security notes.

For local code checks, install a pinned formatter/linter in the contributor environment and use the existing Ubaid [engineering standards](../../CODE_STANDARDS.md). The project currently does not include a test or CI suite.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string for a restricted read-only role. |
| `REDIS_URL` | Redis connection string; tool access is limited to `public:` keys. |
| `OAUTH_ISSUER_URL` | OAuth authorization server issuer advertised in MCP auth metadata. |
| `OAUTH_INTROSPECTION_URL` | HTTPS endpoint implementing OAuth token introspection. |
| `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` | Confidential client credentials for the introspection request. |
| `MCP_RESOURCE_URL` | Exact resource audience expected in the token response. |
| `ALLOWED_WEB_HOSTS` | Comma-separated suffix allowlist for the text-fetch tool. |
| `ALLOWED_BROWSER_HOSTS` | Comma-separated suffix allowlist for browser inspection. |
| `MAX_WEB_RESPONSE_BYTES` | Maximum fetched response body size. |
| `REQUEST_TIMEOUT_SECONDS` | Timeout for upstream and database operations. |

An empty host allowlist denies all destinations. Host entries are normalized to lowercase and match the exact hostname or a subdomain boundary.
