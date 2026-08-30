"""Parry MCP security wrapper.

Public surface:

    from parry.mcp import SentinelMCPClient, MCPBlockedError

    async with SentinelMCPClient.stdio(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        agent_id="dev-assistant",
        api_key="sk-parry-...",
    ) as client:
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "/tmp/notes.md"})

The wrapper sits between your MCP `ClientSession` and the Parry
backend. On connect it fetches the manifest, hashes it, and sends
it to Parry for drift detection + manifest injection scanning. On
any CRITICAL detection or a 403 from the backend (server blocked by
org policy) it raises :class:`MCPBlockedError` and closes the
underlying client cleanly.

The ``mcp`` package is an optional extra — install via
``pip install parry[mcp]``.
"""

from parry.mcp.client import SentinelMCPClient
from parry.mcp.errors import MCPBlockedError, MCPManifestError, MCPURLError
from parry.mcp.normalize import canonical_manifest, manifest_hash

__all__ = [
    "SentinelMCPClient",
    "MCPBlockedError",
    "MCPManifestError",
    "MCPURLError",
    "canonical_manifest",
    "manifest_hash",
]
