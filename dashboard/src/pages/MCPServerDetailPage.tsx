import { Link, useParams } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useMCPServer, useSetMCPServerTrust } from "@/hooks/useMCP";
import { useRole } from "@/hooks/useRole";
import type { MCPTrustLevel } from "@/lib/api";

const TRUST_OPTIONS: MCPTrustLevel[] = [
  "observed",
  "trusted",
  "suspicious",
  "blocked",
];

const TRUST_STYLES: Record<MCPTrustLevel, string> = {
  trusted: "text-emerald-400",
  observed: "text-blue-400",
  suspicious: "text-orange-400",
  blocked: "text-red-400",
};

export function MCPServerDetailPage() {
  const { serverId } = useParams({ from: "/mcp/$serverId" });
  const { data: server, isLoading, error } = useMCPServer(serverId);
  const setTrust = useSetMCPServerTrust();
  const { can } = useRole();
  const canMutate = can("admin");

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }
  if (error || !server) {
    return (
      <div className="p-6 text-sm text-destructive">
        Couldn't load server: {error?.message ?? "not found"}
      </div>
    );
  }

  return (
    <div>
      <Header
        title={server.server_name || "MCP Server"}
        description={server.server_uri}
      />
      <div className="px-6 pt-4">
        <Link to="/mcp" className="text-sm text-muted-foreground hover:underline">
          ← Back to servers
        </Link>
      </div>

      <div className="space-y-4 p-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Trust</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <span className={`text-3xl font-bold ${TRUST_STYLES[server.trust_level]}`}>
                {server.trust_level}
              </span>
              <Badge variant="outline">reputation {server.reputation}</Badge>
              <Badge variant="outline">{server.tool_count} tools</Badge>
            </div>
            {canMutate && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  Set trust level:
                </span>
                {TRUST_OPTIONS.map((opt) => (
                  <Button
                    key={opt}
                    size="sm"
                    variant={opt === server.trust_level ? "default" : "outline"}
                    disabled={setTrust.isPending}
                    onClick={() =>
                      setTrust.mutate({
                        serverId: server.id,
                        trustLevel: opt,
                      })
                    }
                  >
                    {opt}
                  </Button>
                ))}
              </div>
            )}
            <div className="font-mono text-xs text-muted-foreground">
              hash: {server.manifest_hash}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Tools ({server.manifest.tools?.length ?? 0})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {(server.manifest.tools ?? []).map((tool) => (
              <div key={tool.name} className="rounded-md border p-3">
                <div className="font-mono text-sm font-semibold">
                  {tool.name}
                </div>
                <div className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
                  {tool.description || <em>(no description)</em>}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Manifest hash history</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {server.hash_history.length === 0 ? (
              <div className="text-sm text-muted-foreground">
                No changes recorded yet.
              </div>
            ) : (
              <ul className="space-y-2 text-xs">
                {[...server.hash_history].reverse().map((entry, idx) => (
                  <li key={idx} className="rounded border p-2 font-mono">
                    <div>{entry.hash}</div>
                    {entry.changed_at && (
                      <div className="text-muted-foreground">
                        changed at {new Date(entry.changed_at).toLocaleString()}
                      </div>
                    )}
                    {entry.previous_hash && (
                      <div className="text-muted-foreground">
                        previous: {entry.previous_hash.slice(0, 16)}…
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
