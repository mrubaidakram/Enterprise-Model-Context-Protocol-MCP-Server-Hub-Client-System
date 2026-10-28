"""MCP tools behind OAuth bearer-token validation and narrow allowlists."""

from __future__ import annotations

import ipaddress
import os
import socket
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any
from urllib.parse import urlparse

import asyncpg
import httpx
import redis.asyncio as redis
from bs4 import BeautifulSoup
from fastapi import FastAPI
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AnyHttpUrl, BaseModel, Field


def csv_env(name: str) -> frozenset[str]:
    return frozenset(value.strip().lower().rstrip(".") for value in os.getenv(name, "").split(",") if value.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    oauth_issuer_url: str
    introspection_url: str
    oauth_client_id: str
    oauth_client_secret: str
    resource_url: str
    allowed_web_hosts: frozenset[str]
    allowed_browser_hosts: frozenset[str]
    max_response_bytes: int
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "postgresql://localhost/enterprise"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            oauth_issuer_url=os.getenv("OAUTH_ISSUER_URL", "https://identity.example.invalid"),
            introspection_url=os.getenv("OAUTH_INTROSPECTION_URL", ""),
            oauth_client_id=os.getenv("OAUTH_CLIENT_ID", ""),
            oauth_client_secret=os.getenv("OAUTH_CLIENT_SECRET", ""),
            resource_url=os.getenv("MCP_RESOURCE_URL", "http://localhost:8000/mcp"),
            allowed_web_hosts=csv_env("ALLOWED_WEB_HOSTS"),
            allowed_browser_hosts=csv_env("ALLOWED_BROWSER_HOSTS"),
            max_response_bytes=max(1024, int(os.getenv("MAX_WEB_RESPONSE_BYTES", "1000000"))),
            timeout_seconds=max(1.0, float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))),
        )


class IntrospectionVerifier(TokenVerifier):
    """Validate opaque bearer tokens against an RFC 7662 authorization server."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.timeout_seconds)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not all((self.settings.introspection_url, self.settings.oauth_client_id, self.settings.oauth_client_secret)):
            return None
        endpoint = urlparse(self.settings.introspection_url)
        if endpoint.scheme != "https" and endpoint.hostname not in {"localhost", "127.0.0.1"}:
            return None
        try:
            response = await self.client.post(
                self.settings.introspection_url,
                data={"token": token},
                auth=(self.settings.oauth_client_id, self.settings.oauth_client_secret),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        if not isinstance(payload, dict) or payload.get("active") is not True:
            return None
        expires_at = payload.get("exp")
        if not isinstance(expires_at, (int, float)) or expires_at <= datetime.now(timezone.utc).timestamp():
            return None
        audience = payload.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if self.settings.resource_url not in audiences:
            return None
        subject = payload.get("sub")
        client_id = payload.get("client_id")
        scopes = payload.get("scope", "")
        if not isinstance(subject, str) or not subject or not isinstance(client_id, str) or not client_id:
            return None
        if isinstance(scopes, str):
            scope_list = scopes.split()
        elif isinstance(scopes, list) and all(isinstance(scope, str) for scope in scopes):
            scope_list = scopes
        else:
            return None
        if "mcp:invoke" not in scope_list:
            return None
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scope_list,
            expires_at=int(expires_at),
            resource=self.settings.resource_url,
            subject=subject,
            claims=payload,
        )


def host_is_allowed(hostname: str, allowlist: frozenset[str]) -> bool:
    host = hostname.lower().rstrip(".")
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowlist)


async def assert_public_host(hostname: str) -> None:
    """Resolve at call time and reject private, loopback, link-local, or reserved IPs."""
    try:
        records = await asyncio.get_running_loop().getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Host could not be resolved") from exc
    addresses = {record[4][0] for record in records}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Host resolves to a non-public address")


settings = Settings.from_env()
auth = AuthSettings(
    issuer_url=settings.oauth_issuer_url,
    resource_server_url=settings.resource_url,
    required_scopes=["mcp:invoke"],
    validate_token_resource=True,
)
verifier = IntrospectionVerifier(settings)
@asynccontextmanager
async def mcp_lifespan(server: FastMCP):
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5, command_timeout=settings.timeout_seconds)
    redis_client = redis.from_url(settings.redis_url, socket_timeout=settings.timeout_seconds, decode_responses=False)
    http_client = httpx.AsyncClient(timeout=settings.timeout_seconds, follow_redirects=False)
    try:
        yield {"postgres_pool": pool, "redis_client": redis_client, "http_client": http_client}
    finally:
        await http_client.aclose()
        await redis_client.aclose()
        await pool.close()
        await verifier.client.aclose()


mcp = FastMCP("enterprise-mcp-hub", token_verifier=verifier, auth=auth, lifespan=mcp_lifespan)


@mcp.tool()
async def database_identity(ctx: Context) -> dict[str, str]:
    """Return the connected database and role names for diagnostics."""
    pool: asyncpg.Pool = ctx.request_context.lifespan_context["postgres_pool"]
    row = await pool.fetchrow("SELECT current_database() AS database, current_user AS role")
    return {"database": row["database"], "role": row["role"]}


@mcp.tool()
async def recent_orders(ctx: Context, limit: Annotated[int, Field(ge=1, le=100)] = 10) -> list[dict[str, Any]]:
    """Read a bounded recent-orders report; the SQL is fixed and parameterized."""
    pool: asyncpg.Pool = ctx.request_context.lifespan_context["postgres_pool"]
    rows = await pool.fetch(
        "SELECT id::text AS id, created_at::text AS created_at, status "
        "FROM public.orders ORDER BY created_at DESC LIMIT $1",
        limit,
    )
    return [dict(row) for row in rows]


@mcp.tool()
async def read_public_cache(key: str, ctx: Context) -> str | None:
    """Read one entry under the explicitly public cache namespace."""
    if not key or len(key) > 128 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-" for char in key):
        raise ValueError("key must be 1-128 safe characters")
    client: redis.Redis = ctx.request_context.lifespan_context["redis_client"]
    value = await client.get(f"public:{key}")
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


@mcp.tool()
async def fetch_allowed_page(url: AnyHttpUrl, ctx: Context) -> dict[str, str]:
    """Fetch text from an allowlisted HTTPS host without following redirects."""
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or not parsed.hostname or not host_is_allowed(parsed.hostname, settings.allowed_web_hosts):
        raise ValueError("Only HTTPS URLs on ALLOWED_WEB_HOSTS are accepted")
    await assert_public_host(parsed.hostname)
    client: httpx.AsyncClient = ctx.request_context.lifespan_context["http_client"]
    async with client.stream("GET", str(url), follow_redirects=False, headers={"Accept": "text/html,text/plain"}) as response:
        if response.is_redirect or response.status_code >= 400:
            raise ValueError(f"Upstream returned HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "")
        if not any(kind in content_type.lower() for kind in ("text/html", "text/plain")):
            raise ValueError("Only HTML and plain-text responses are supported")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > settings.max_response_bytes:
                raise ValueError("Upstream response exceeds configured size limit")
            chunks.append(chunk)
    raw = b"".join(chunks).decode("utf-8", errors="replace")
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True) if "html" in content_type.lower() else raw
    return {"url": str(url), "text": text[:20000]}


@mcp.tool()
async def inspect_browser_page(url: AnyHttpUrl) -> dict[str, str]:
    """Read page title and visible text on an allowlisted host; no interaction or downloads."""
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or not parsed.hostname or not host_is_allowed(parsed.hostname, settings.allowed_browser_hosts):
        raise ValueError("Only HTTPS URLs on ALLOWED_BROWSER_HOSTS are accepted")
    await assert_public_host(parsed.hostname)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("Install the optional browser runtime with `playwright install chromium`") from exc
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(java_script_enabled=False)
        page = await context.new_page()

        async def guard_browser_request(route: Any) -> None:
            request_url = urlparse(route.request.url)
            if request_url.scheme != "https" or request_url.hostname != parsed.hostname:
                await route.abort()
                return
            try:
                await assert_public_host(request_url.hostname)
            except ValueError:
                await route.abort()
                return
            await route.continue_()

        await page.route("**/*", guard_browser_request)
        try:
            await page.goto(str(url), wait_until="domcontentloaded", timeout=int(settings.timeout_seconds * 1000))
            title = await page.title()
            text = await page.locator("body").inner_text(timeout=int(settings.timeout_seconds * 1000))
        finally:
            await browser.close()
    return {"url": str(url), "title": title[:500], "text": text[:20000]}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


# FastMCP owns resources used by the mounted tool handlers. The outer ASGI host
# explicitly starts the MCP session manager because mounted apps do not own lifespan.
app = FastAPI(title="Enterprise MCP Hub", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", mcp.streamable_http_app())
