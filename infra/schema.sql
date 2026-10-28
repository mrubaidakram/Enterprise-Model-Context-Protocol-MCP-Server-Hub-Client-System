-- Optional demo table queried by the fixed recent_orders MCP tool.
CREATE TABLE IF NOT EXISTS public.orders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'complete', 'cancelled'))
);

-- Grant only the privileges needed by this application's read-only role.
-- Create the role and its password through your secret-management process first.
GRANT CONNECT ON DATABASE enterprise TO mcp_readonly;
GRANT USAGE ON SCHEMA public TO mcp_readonly;
GRANT SELECT ON TABLE public.orders TO mcp_readonly;
