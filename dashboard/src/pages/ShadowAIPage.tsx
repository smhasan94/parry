import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent } from "@/components/ui/card";
import { ShadowAITable } from "@/components/ShadowAITable";
import { useShadowAI, useSyncOkta } from "@/hooks/useDiscovery";
import { Radar } from "lucide-react";

const TIER_ORDER = ["unacceptable", "high", "limited", "minimal", "unclassified"];

export function ShadowAIPage() {
  const { data, isLoading } = useShadowAI();
  const syncOkta = useSyncOkta();
  const [oktaDomain, setOktaDomain] = useState("");
  const [apiToken, setApiToken] = useState("");

  const counts = data?.by_risk_level ?? {};
  const tiers = TIER_ORDER.filter((t) => counts[t]);

  return (
    <div>
      <Header
        title="Shadow AI"
        description="AI systems discovered in your environment that no Parry agent is monitoring"
      />

      <div className="space-y-6 p-6">
        <Card>
          <CardContent className="p-5">
            <h2 className="mb-1 text-sm font-medium">Scan Okta</h2>
            <p className="mb-4 text-xs text-zinc-500">
              A read-only API token is enough. Nothing is installed and no code changes in
              your agents. The token is used for this scan only and never stored.
            </p>
            <div className="flex flex-wrap gap-2">
              <input
                className="flex-1 rounded-md border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                placeholder="acme.okta.com"
                value={oktaDomain}
                onChange={(e) => setOktaDomain(e.target.value)}
              />
              <input
                className="flex-1 rounded-md border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                placeholder="API token"
                type="password"
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
              />
              <button
                className="rounded-md bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                disabled={!oktaDomain || !apiToken || syncOkta.isPending}
                onClick={() => syncOkta.mutate({ oktaDomain, apiToken })}
              >
                {syncOkta.isPending ? "Scanning…" : "Scan"}
              </button>
            </div>
          </CardContent>
        </Card>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 rounded-lg border border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <Radar className="h-4 w-4 text-zinc-400" />
            <span className="text-2xl font-semibold">{data?.total ?? 0}</span>
            <span className="text-sm text-zinc-500">unmonitored</span>
          </div>
          {tiers.map((tier) => (
            <div
              key={tier}
              className="rounded-lg border border-zinc-200 px-4 py-3 dark:border-zinc-800"
            >
              <div className="text-2xl font-semibold">{counts[tier]}</div>
              <div className="text-xs capitalize text-zinc-500">{tier}</div>
            </div>
          ))}
        </div>

        <Card>
          <CardContent className="p-5">
            {isLoading ? (
              <p className="text-sm text-zinc-500">Loading…</p>
            ) : (
              <ShadowAITable systems={data?.systems ?? []} />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
