import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useMCPServers } from "@/hooks/useMCP";
import { Plug } from "lucide-react";
import type { MCPTrustLevel } from "@/lib/api";

const TRUST_STYLES: Record<MCPTrustLevel, string> = {
  trusted: "bg-emerald-950/50 text-emerald-300 border-emerald-900",
  observed: "bg-blue-950/50 text-blue-300 border-blue-900",
  suspicious: "bg-orange-950/50 text-orange-300 border-orange-900",
  blocked: "bg-red-950/50 text-red-300 border-red-900",
};

export function MCPServersPage() {
  const { data: servers = [], isLoading } = useMCPServers();
  const [filter, setFilter] = useState<MCPTrustLevel | "all">("all");

  const visible =
    filter === "all" ? servers : servers.filter((s) => s.trust_level === filter);

  return (
    <div>
      <Header
        title="MCP Servers"
        description="Model Context Protocol servers your agents have connected to"
      />

      <div className="space-y-4 p-6">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Filter:</span>
          {(["all", "trusted", "observed", "suspicious", "blocked"] as const).map(
            (opt) => (
              <button
                key={opt}
                onClick={() => setFilter(opt)}
                className={`rounded-md border px-2 py-1 text-xs capitalize transition-colors ${
                  filter === opt
                    ? "border-primary bg-primary/10"
                    : "border-border hover:bg-muted/40"
                }`}
              >
                {opt}
              </button>
            ),
          )}
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading servers…</p>
        ) : servers.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
              <Plug className="h-12 w-12 text-muted-foreground" />
              <p className="text-sm font-medium">No MCP servers registered</p>
              <p className="max-w-md text-xs text-muted-foreground">
                Wrap your MCP client with{" "}
                <code className="rounded bg-secondary px-1 py-0.5 text-xs">
                  SentinelMCPClient
                </code>{" "}
                to register servers here. Parry catches manifest injection,
                detects drift on trusted servers, and gates tool calls at the
                protocol boundary.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="px-4 py-2 text-left font-medium">Server</th>
                    <th className="px-4 py-2 text-left font-medium">URI</th>
                    <th className="px-4 py-2 text-left font-medium">Trust</th>
                    <th className="px-4 py-2 text-right font-medium">Tools</th>
                    <th className="px-4 py-2 text-right font-medium">Rep</th>
                    <th className="px-4 py-2 text-left font-medium">
                      Last seen
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((server) => (
                    <tr
                      key={server.id}
                      className="border-b border-border last:border-0 hover:bg-muted/40"
                    >
                      <td className="px-4 py-3 font-medium">
                        <Link
                          to="/mcp/$serverId"
                          params={{ serverId: server.id }}
                          className="hover:underline"
                        >
                          {server.server_name || "(unnamed)"}
                        </Link>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        {server.server_uri}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant="outline"
                          className={`border text-xs ${TRUST_STYLES[server.trust_level]}`}
                        >
                          {server.trust_level}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {server.tool_count}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {server.reputation}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {new Date(server.last_seen_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
