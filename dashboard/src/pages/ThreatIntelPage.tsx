import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  useThreatFeed,
  useThreatFeedStats,
  useUpdateThreatSharing,
} from "@/hooks/useThreatIntel";
import { useRole } from "@/hooks/useRole";
import { ErrorState, LoadingState } from "@/components/ui/states";
import {
  Radio,
  Shield,
  AlertTriangle,
  TrendingUp,
  Eye,
} from "lucide-react";
import type { ThreatIndicator } from "@/lib/types";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-800",
  high: "bg-orange-100 text-orange-800",
  medium: "bg-yellow-100 text-yellow-800",
  low: "bg-gray-100 text-gray-600",
};

const CATEGORY_LABELS: Record<string, string> = {
  instruction_override: "Instruction Override",
  jailbreak: "Jailbreak",
  data_exfil: "Data Exfiltration",
  tool_hijack: "Tool Hijack",
  mcp_injection: "MCP Injection",
  unicode_smuggling: "Unicode Smuggling",
  cost_exploit: "Cost Exploit",
  anomaly: "Anomaly",
  custom_rule: "Custom Rule",
  policy_violation: "Policy Violation",
  unknown: "Unknown",
};

function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score * 100));
  const color =
    pct > 70
      ? "bg-red-500"
      : pct > 40
        ? "bg-yellow-500"
        : "bg-gray-400";
  return (
    <div className="h-1.5 w-16 rounded-full bg-muted">
      <div
        className={`h-full rounded-full ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function ThreatIntelPage() {
  const { data: feed = [], isLoading, isError, error, refetch } = useThreatFeed();
  const { data: stats } = useThreatFeedStats();
  const updateSharing = useUpdateThreatSharing();
  const { can } = useRole();

  return (
    <div>
      <Header
        title="Threat Intelligence"
        description="Cross-organization threat feed — attack patterns seen across the Parry network"
      />

      <div className="space-y-4 p-6">
        {/* Stats cards */}
        {stats && (
          <div className="grid grid-cols-3 gap-4">
            <Card>
              <CardContent className="flex items-center gap-3 p-4">
                <Radio className="h-5 w-5 text-primary" />
                <div>
                  <p className="text-2xl font-bold">{stats.active_indicators}</p>
                  <p className="text-xs text-muted-foreground">Active Indicators</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex items-center gap-3 p-4">
                <Eye className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-2xl font-bold">{stats.total_indicators}</p>
                  <p className="text-xs text-muted-foreground">Total Tracked</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex items-center gap-3 p-4">
                <TrendingUp className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-2xl font-bold">
                    {Object.keys(stats.by_category).length}
                  </p>
                  <p className="text-xs text-muted-foreground">Attack Categories</p>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Sharing settings */}
        {can("owner") && (
          <Card>
            <CardContent className="flex items-center justify-between p-4">
              <div>
                <p className="text-sm font-medium">Threat Sharing</p>
                <p className="text-xs text-muted-foreground">
                  Contribute anonymized detection patterns to the shared feed.
                  Your raw data is never shared — only pattern signatures.
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => updateSharing.mutate(true)}
                disabled={updateSharing.isPending}
              >
                {updateSharing.isPending ? "Updating..." : "Sharing Enabled"}
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Feed table */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Shield className="h-4 w-4" />
              Active Threat Feed
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <LoadingState label="Loading threat feed" />
            ) : isError ? (
              <ErrorState
                error={error}
                title="Couldn't load feed"
                onRetry={() => refetch()}
              />
            ) : feed.length === 0 ? (
              <div className="flex flex-col items-center gap-3 py-12 text-center">
                <AlertTriangle className="h-12 w-12 text-muted-foreground" />
                <p className="text-sm font-medium">No confirmed threats — feed is clean</p>
                <p className="max-w-sm text-xs text-muted-foreground">
                  Indicators appear when an attack pattern is confirmed across
                  3+ organizations in the Parry network. A clean feed means no
                  network-wide campaigns are currently active.
                </p>
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2">Category</th>
                    <th className="pb-2">Severity</th>
                    <th className="pb-2">Orgs</th>
                    <th className="pb-2">Sightings</th>
                    <th className="pb-2">Score</th>
                    <th className="pb-2">Last Seen</th>
                    <th className="pb-2">Pattern</th>
                  </tr>
                </thead>
                <tbody>
                  {feed.map((ind: ThreatIndicator) => (
                    <tr key={ind.id} className="border-b last:border-0">
                      <td className="py-2">
                        <span className="rounded bg-primary/10 px-2 py-0.5 font-medium text-primary">
                          {CATEGORY_LABELS[ind.category] || ind.category}
                        </span>
                      </td>
                      <td className="py-2">
                        <span
                          className={`rounded px-2 py-0.5 font-medium ${
                            SEVERITY_COLORS[ind.severity] || SEVERITY_COLORS.low
                          }`}
                        >
                          {ind.severity}
                        </span>
                      </td>
                      <td className="py-2 font-medium">{ind.org_count}</td>
                      <td className="py-2">{ind.sighting_count}</td>
                      <td className="py-2">
                        <ScoreBar score={ind.score} />
                      </td>
                      <td className="py-2 text-muted-foreground">
                        {new Date(ind.last_seen_at).toLocaleDateString()}
                      </td>
                      <td className="max-w-xs truncate py-2 font-mono text-muted-foreground">
                        {ind.sample_reason || ind.pattern_hash.slice(0, 16) + "..."}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
