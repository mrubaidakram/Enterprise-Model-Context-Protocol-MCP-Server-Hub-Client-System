# Security model

## Authentication and authorization

The MCP endpoint delegates token issuance to an external OAuth authorization server. The hub performs OAuth token introspection and accepts only active, unexpired opaque tokens with a subject, client ID, the `mcp:invoke` scope, and an audience matching `MCP_RESOURCE_URL`. Configure the authorization server to restrict which principals receive that scope. Missing or invalid introspection configuration results in tool calls being denied.

## Tool boundaries

- PostgreSQL access consists of fixed read-only statements. The application database role should be read-only as a second enforcement layer.
- Redis access is read-only and prefixed with `public:`.
- Web access is HTTPS-only, host-allowlisted, DNS-resolved at call time, rejects non-public resolved addresses, disables redirects, and caps response bytes.
- Browser access is HTTPS-only and host-allowlisted. The tool extracts title and text and does not expose interaction methods.

## Deployment requirements

Terminate TLS in a trusted proxy or serve HTTPS directly. Keep OAuth secrets out of images and logs. Restrict outbound network access to the identity server, configured websites, PostgreSQL, and Redis. Do not expose PostgreSQL or Redis ports publicly. Apply proxy-level request size, connection, and rate limits.

The current DNS check is performed before the HTTP or browser client resolves the hostname again; deployments with hostile or mutable DNS should add an egress proxy that enforces destination IP policy at connection time to close DNS rebinding windows. The example is a starter implementation and should undergo organization security review before production use.
