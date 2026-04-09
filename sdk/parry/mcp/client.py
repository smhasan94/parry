"""``SentinelMCPClient`` — Parry-aware wrapper over ``mcp.ClientSession``.

Lifecycle (stdio example):

1. ``__aenter__`` opens the underlying ``mcp.ClientSession``, calls
   ``initialize()``, fetches ``list_tools()``, hashes the manifest,
   and POSTs it to Parry's ``/api/v1/mcp/connections`` endpoint.
2. Parry returns the trust verdict + any detection findings.
   - 403 → raise :class:`MCPBlockedError` (server is hard-blocked).
   - Any ``critical`` detection → raise :class:`MCPBlockedError`
     (server is attempting manifest injection).
   - Everything else → proceed.
3. ``list_tools()`` returns the cached manifest — no extra call.
4. ``call_tool(name, args)`` invokes the underlying client, returns
   the raw result. (v1 does not scan tool results — that's the
   indirect-injection detector work from plan 13 Task 5; deferred
   to keep the first release compact.)
5. ``__aexit__`` closes everything cleanly even on error.

``mcp`` is an optional SDK dependency — importing this module
without ``pip install parry[mcp]`` raises a helpful error only when
a constructor is actually called, not at module import time.
"""

from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack
from typing import Any

import httpx

from parry.mcp.errors import MCPBlockedError, MCPManifestError
from parry.mcp.normalize import manifest_hash

logger = logging.getLogger("parry.mcp")

_DEFAULT_BASE_URL = "https://api.parry.dev"


def _require_mcp() -> Any:
    try:
        import mcp  # noqa: F401 — module is the value we return

        return mcp
    except ImportError as e:  # pragma: no cover — exercised manually
        raise ImportError(
            "SentinelMCPClient requires the `mcp` extra. "
            "Install with: pip install 'parry[mcp]'"
        ) from e


class SentinelMCPClient:
    """Async context manager wrapping an ``mcp.ClientSession``.

    Construct via one of the three factory classmethods:

        SentinelMCPClient.stdio(command=..., args=..., **parry_kwargs)
        SentinelMCPClient.http(url=..., **parry_kwargs)
        SentinelMCPClient.sse(url=..., **parry_kwargs)

    Only ``stdio`` is implemented in v1 — ``http`` and ``sse`` raise
    ``NotImplementedError`` and will be filled in once Claude Desktop
    customers are stable on stdio.
    """

    def __init__(
        self,
        *,
        transport: str,
        transport_kwargs: dict[str, Any],
        agent_id: str,
        api_key: str | None = None,
        parry_base_url: str | None = None,
        blocking: bool = True,
        sandbox: bool = False,
        server_name: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._transport = transport
        self._transport_kwargs = transport_kwargs
        self.agent_id = agent_id
        self.api_key = api_key or os.environ.get("PARRY_API_KEY")
        if not self.api_key and not sandbox:
            raise ValueError(
                "Parry API key required (pass api_key= or set PARRY_API_KEY)"
            )
        self.base_url = (parry_base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.blocking = blocking
        self.sandbox = sandbox
        self.server_name = server_name
        self.timeout = timeout

        self._stack: AsyncExitStack | None = None
        self._session: Any = None
        self._manifest: dict[str, Any] | None = None
        self._server_uri: str | None = None
        self._http: httpx.AsyncClient | None = None
        # Test hook: a prebuilt manifest to use instead of opening a
        # real stdio subprocess. Only intended for unit tests — we
        # still hit the Parry backend so the register-with-parry
        # round trip is exercised.
        self._fake_manifest: dict[str, Any] | None = None

    # ── Constructors ───────────────────────────────────────────────

    @classmethod
    def stdio(
        cls,
        *,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        **parry_kwargs: Any,
    ) -> SentinelMCPClient:
        args = args or []
        server_uri = f"stdio://{command} {' '.join(args)}".strip()
        return cls(
            transport="stdio",
            transport_kwargs={
                "command": command,
                "args": args,
                "env": env or {},
                "server_uri": server_uri,
            },
            **parry_kwargs,
        )

    @classmethod
    def http(cls, *, url: str, **parry_kwargs: Any) -> SentinelMCPClient:  # pragma: no cover
        raise NotImplementedError(
            "HTTP transport is not implemented in v1. Use stdio() for now."
        )

    @classmethod
    def sse(cls, *, url: str, **parry_kwargs: Any) -> SentinelMCPClient:  # pragma: no cover
        raise NotImplementedError(
            "SSE transport is not implemented in v1. Use stdio() for now."
        )

    # ── Context manager lifecycle ──────────────────────────────────

    async def __aenter__(self) -> SentinelMCPClient:
        self._stack = AsyncExitStack()

        if not self.sandbox:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "X-Parry-Secret": self.api_key or "",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            await self._stack.enter_async_context(self._http)

        if self._transport == "stdio":
            self._server_uri = self._transport_kwargs["server_uri"]
            if self.sandbox:
                self._manifest = {"tools": []}
            elif self._fake_manifest is not None:
                self._manifest = self._fake_manifest
            else:
                await self._open_stdio_session()
        else:  # pragma: no cover
            raise NotImplementedError(self._transport)

        if not self.sandbox:
            await self._register_with_parry()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None
        self._http = None

    # ── Underlying session ─────────────────────────────────────────

    async def _open_stdio_session(self) -> None:
        mcp = _require_mcp()  # noqa: F841 — validates the extra is installed
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self._transport_kwargs["command"],
            args=self._transport_kwargs["args"],
            env=self._transport_kwargs.get("env") or None,
        )
        assert self._stack is not None
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()
        tools_result = await self._session.list_tools()
        # mcp returns a ListToolsResult with .tools list of Tool objects.
        # We normalize to the wire-level dict shape Parry's backend expects.
        self._manifest = _tools_result_to_manifest(tools_result)

    # ── Parry backend round-trip ───────────────────────────────────

    async def _register_with_parry(self) -> None:
        assert self._http is not None
        assert self._manifest is not None
        assert self._server_uri is not None

        payload = {
            "agent_id": self.agent_id,
            "server_uri": self._server_uri,
            "server_name": self.server_name,
            "manifest": self._manifest,
        }
        try:
            resp = await self._http.post("/api/v1/mcp/connections", json=payload)
        except Exception as e:
            # Fail open — Parry backend unreachable should not block the
            # developer's work. Log + continue.
            logger.warning(
                "parry.mcp: backend unreachable, skipping manifest check: %s", e
            )
            return

        if resp.status_code == 403:
            await self._close_underlying()
            raise MCPBlockedError(
                resp.text or "MCP server blocked by org policy",
                server_uri=self._server_uri,
            )
        if resp.status_code >= 400:
            logger.warning(
                "parry.mcp: backend rejected manifest (%s): %s",
                resp.status_code,
                resp.text[:200],
            )
            return

        data = resp.json()
        self._server_id = data.get("server_id")
        self._trust_level = data.get("trust_level")

        detections = data.get("detections") or []
        critical = [d for d in detections if d.get("severity") == "critical"]

        if self.blocking and critical:
            await self._close_underlying()
            raise MCPBlockedError(
                critical[0].get("reason", "Critical MCP detection"),
                detections=detections,
                server_uri=self._server_uri,
            )

        if detections:
            logger.warning(
                "parry.mcp: %d non-critical findings on %s",
                len(detections),
                self._server_uri,
            )

    async def _close_underlying(self) -> None:
        # Close just the MCP session — leave the httpx client open so
        # that any follow-up /events calls can still succeed if the
        # caller catches the exception and retries.
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:  # pragma: no cover
                pass
            self._session = None

    # ── Public methods ─────────────────────────────────────────────

    async def list_tools(self) -> dict[str, Any]:
        """Return the cached manifest fetched at connect time."""
        if self._manifest is None:
            raise MCPManifestError(
                "SentinelMCPClient not entered — use `async with` first"
            )
        return self._manifest

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> Any:
        """Invoke a tool on the underlying MCP session.

        v1 just passes through — we rely on the server-side detection
        pipeline (via `/proxy/scan-response`) for tool-result scanning.
        """
        if self._session is None:
            raise MCPManifestError(
                "SentinelMCPClient not entered — use `async with` first"
            )
        return await self._session.call_tool(name, arguments or {})

    # Hash helper for external callers / tests
    def manifest_hash(self) -> str:
        if self._manifest is None:
            return ""
        return manifest_hash(self._manifest)


def _tools_result_to_manifest(tools_result: Any) -> dict[str, Any]:
    """Convert an mcp ListToolsResult to the wire-level dict shape."""
    tools_out: list[dict[str, Any]] = []
    raw_tools = getattr(tools_result, "tools", None) or []
    for tool in raw_tools:
        tools_out.append(
            {
                "name": getattr(tool, "name", None) or "",
                "description": getattr(tool, "description", None) or "",
                "inputSchema": getattr(tool, "inputSchema", None) or {},
            }
        )
    return {"tools": tools_out}
