# Deployment guide

1. Build an image from this repository with a locked dependency file reviewed by your security process.
2. Provide `DATABASE_URL`, `REDIS_URL`, OAuth credentials, resource URL, and host allowlists from a secret/configuration manager.
3. Create a dedicated PostgreSQL role with only required `SELECT` privileges. Create the `public:` Redis namespace according to your data policy.
4. Put the HTTP service behind TLS termination and an authenticated network boundary. Configure the OAuth authorization server with the MCP resource URL and `mcp:invoke` scope.
5. Permit only required egress. Include DNS resolution and the configured identity/web destinations.
6. Monitor liveness, upstream failures, auth rejection rates, request latency, and dependency pool saturation. Avoid logging bearer tokens or full page contents.
7. Deploy a schema-specific version of `recent_orders` only after confirming the table and columns exist.

The repository does not include a production container manifest or CI pipeline. Add these to match your organization’s base-image, signing, and deployment controls before production rollout.
