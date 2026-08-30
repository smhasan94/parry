"""``SentinelMCPClient`` — Parry-aware wrapper over ``mcp.ClientSession``.

Lifecycle (stdio example; http and sse follow the same shape):

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

import json
import logging
import os
from contextlib import AsyncExitStack
from typing import Any

import anyio
import httpx

from parry.mcp.errors import MCPBlockedError, MCPManifestError
from parry.mcp.normalize import manifest_hash
from parry.mcp.validate import Resolver, validate_server_url

logger = logging.getLogger("parry.mcp")

_DEFAULT_BASE_URL = "https://api.parry.dev"

# A remote server controls how long it takes to answer, so the manifest
# handshake gets its own bound rather than inheriting the backend HTTP
# timeout.
_DEFAULT_MANIFEST_TIMEOUT = 30.0

# Bounds on what a remote server may hand back. Failing closed is right
# here: a manifest this size is not a tool list, and the alternative is
# hashing and scanning attacker-chosen bulk on the caller's thread.
#
# These reject a manifest that has already been received and parsed, so
# they bound what we *do* with it, not what a server can make us buffer.
# Bounding that means capping bytes before the JSON-RPC parse, inside
# the transport — and it has to be per message, since an SSE session's
# response body stays open for the life of the session and a cap on the
# whole body would kill long-running sessions. Until then the real
# bound on a server streaming bulk at us is ``manifest_timeout``.
MAX_MANIFEST_TOOLS = 500
MAX_MANIFEST_CHARS = 1_000_000


def _no_redirect_client(
    headers: dict[str, str] | None = None,
    timeout: Any = None,
    auth: Any = None,
) -> httpx.AsyncClient:
    """httpx client for the MCP transports, with redirects disabled.

    Validating the URL only proves the *first* hop is acceptable. A
    permitted host answering 302 → http://169.254.169.254/ would walk
    straight past every check, so the transport never follows.
    """
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
        verify=True,
    )


def _check_manifest_bounds(manifest: dict[str, Any] | None) -> None:
    """Refuse a manifest too large to be a real tool list.

    Both limits matter: a few enormous tool descriptions weigh nothing
    by count, and thousands of tiny tools weigh nothing by size.
    """
    if not manifest:
        return

    tools = manifest.get("tools")
    if isinstance(tools, list) and len(tools) > MAX_MANIFEST_TOOLS:
        raise MCPManifestError(
            f"MCP server declared {len(tools)} tools, above the {MAX_MANIFEST_TOOLS} limit"
        )

    size = len(json.dumps(manifest, ensure_ascii=False, default=str))
    if size > MAX_MANIFEST_CHARS:
        raise MCPManifestError(
            f"MCP manifest is {size} characters, above the {MAX_MANIFEST_CHARS} limit"
        )


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

    ``http`` and ``sse`` reach remote servers and so validate their
    URL before dialling: see ``parry.mcp.validate``. Auth material
    passed to them stays in this process and never reaches Parry.
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
        manifest_timeout: float = _DEFAULT_MANIFEST_TIMEOUT,
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
        self.manifest_timeout = manifest_timeout

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
    def http(
        cls,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        auth: Any = None,
        allow_insecure: bool = False,
        allow_private: bool = False,
        resolver: Resolver | None = None,
        **parry_kwargs: Any,
    ) -> SentinelMCPClient:
        """Connect to a remote MCP server over streamable HTTP.

        ``headers``/``auth`` stay in this process: they are handed to
        the transport and never included in the payload sent to Parry,
        so a bearer token cannot end up in the server registry.

        ``resolver`` overrides how the hostname is turned into addresses
        for the SSRF checks — see ``parry.mcp.validate``.
        """
        return cls._remote(
            "http",
            url=url,
            headers=headers,
            auth=auth,
            allow_insecure=allow_insecure,
            allow_private=allow_private,
            resolver=resolver,
            **parry_kwargs,
        )

    @classmethod
    def sse(
        cls,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        auth: Any = None,
        allow_insecure: bool = False,
        allow_private: bool = False,
        resolver: Resolver | None = None,
        **parry_kwargs: Any,
    ) -> SentinelMCPClient:
        """Connect to a remote MCP server over SSE."""
        return cls._remote(
            "sse",
            url=url,
            headers=headers,
            auth=auth,
            allow_insecure=allow_insecure,
            allow_private=allow_private,
            resolver=resolver,
            **parry_kwargs,
        )

    @classmethod
    def _remote(
        cls,
        transport: str,
        *,
        url: str,
        headers: dict[str, str] | None,
        auth: Any,
        allow_insecure: bool,
        allow_private: bool,
        resolver: Resolver | None,
        **parry_kwargs: Any,
    ) -> SentinelMCPClient:
        # Validate before construction so a refused URL fails at the
        # call site the developer wrote, not later inside a context
        # manager where the traceback points at our internals.
        server_uri = validate_server_url(
            url,
            allow_insecure=allow_insecure,
            allow_private=allow_private,
            resolver=resolver,
        )
        return cls(
            transport=transport,
            transport_kwargs={
                "url": server_uri,
                "headers": headers or {},
                "auth": auth,
                "server_uri": server_uri,
            },
            **parry_kwargs,
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

        if self._transport not in _OPENERS:  # pragma: no cover
            raise NotImplementedError(self._transport)

        self._server_uri = self._transport_kwargs["server_uri"]
        if self.sandbox:
            self._manifest = {"tools": []}
        elif self._fake_manifest is not None:
            self._manifest = self._fake_manifest
            _check_manifest_bounds(self._manifest)
        else:
            await _OPENERS[self._transport](self)
            _check_manifest_bounds(self._manifest)

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

    async def _open_http_session(self) -> None:
        """Streamable HTTP. Yields a 3-tuple; the session id is unused."""
        _require_mcp()
        # Renamed in newer mcp releases; the old spelling still exists
        # but emits a DeprecationWarning, so prefer the current one and
        # fall back for anyone pinned to an older version.
        try:
            from mcp.client.streamable_http import streamable_http_client
        except ImportError:  # pragma: no cover — mcp < 1.16
            from mcp.client.streamable_http import (
                streamablehttp_client as streamable_http_client,
            )

        assert self._stack is not None
        read, write, _get_session_id = await self._stack.enter_async_context(
            streamable_http_client(
                self._transport_kwargs["url"],
                headers=self._transport_kwargs.get("headers") or None,
                auth=self._transport_kwargs.get("auth"),
                timeout=self.timeout,
                httpx_client_factory=_no_redirect_client,
            )
        )
        await self._finish_remote_session(read, write)

    async def _open_sse_session(self) -> None:
        """SSE. Same handshake, but this transport yields a 2-tuple."""
        _require_mcp()
        from mcp.client.sse import sse_client

        assert self._stack is not None
        read, write = await self._stack.enter_async_context(
            sse_client(
                self._transport_kwargs["url"],
                headers=self._transport_kwargs.get("headers") or None,
                auth=self._transport_kwargs.get("auth"),
                timeout=self.timeout,
                httpx_client_factory=_no_redirect_client,
            )
        )
        await self._finish_remote_session(read, write)

    async def _finish_remote_session(self, read: Any, write: Any) -> None:
        """Handshake shared by both remote transports.

        Bounded by a timeout because a remote server controls how long
        it takes to answer: without this, a server that accepts the
        connection and then never responds hangs the caller's startup
        indefinitely.
        """
        from mcp import ClientSession

        assert self._stack is not None
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        try:
            with anyio.fail_after(self.manifest_timeout):
                await self._session.initialize()
                tools_result = await self._session.list_tools()
        except TimeoutError as e:
            raise MCPManifestError(
                f"MCP server did not return a manifest within "
                f"{self.manifest_timeout}s: {self._server_uri}"
            ) from e
        self._manifest = _tools_result_to_manifest(tools_result)

    # ── Parry backend round-trip ───────────────────────────────────

    async def _register_with_parry(self) -> None:
        assert self._http is not None
        assert self._manifest is not None
        assert self._server_uri is not None

        payload = {
            "agent_id": self.agent_id,
            "server_uri": self._server_uri,
            "transport": self._transport,
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


# Registered after the class body so __aenter__ can dispatch without a
# chain of transport conditionals.
_OPENERS: dict[str, Any] = {
    "stdio": SentinelMCPClient._open_stdio_session,
    "http": SentinelMCPClient._open_http_session,
    "sse": SentinelMCPClient._open_sse_session,
}
