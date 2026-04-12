import { useMemo, useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  useCommunityPacks,
  useCommunitySubscriptions,
  useInstallPack,
  useUninstallPack,
} from "@/hooks/useCommunityRules";
import { Download, Package, Search, Trash2 } from "lucide-react";
import type { CommunityPack } from "@/lib/api";

const CATEGORIES = [
  "all",
  "healthcare",
  "finance",
  "pii",
  "compliance",
  "prompt-injection",
  "data-exfiltration",
  "tool-misuse",
  "general",
];

const CATEGORY_COLORS: Record<string, string> = {
  healthcare: "bg-emerald-500/15 text-emerald-300",
  finance: "bg-blue-500/15 text-blue-300",
  pii: "bg-red-500/15 text-red-300",
  compliance: "bg-purple-500/15 text-purple-300",
  "prompt-injection": "bg-orange-500/15 text-orange-300",
  "data-exfiltration": "bg-rose-500/15 text-rose-300",
  "tool-misuse": "bg-amber-500/15 text-amber-300",
  general: "bg-zinc-500/15 text-zinc-300",
};

export function CommunityRulesPage() {
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  const { data: packs = [], isLoading } = useCommunityPacks({
    category: category === "all" ? undefined : category,
    search: debouncedSearch || undefined,
  });
  const { data: subscriptions = [] } = useCommunitySubscriptions();
  const installPack = useInstallPack();
  const uninstallPack = useUninstallPack();

  const subscribedIds = useMemo(
    () => new Set(subscriptions.map((s) => s.pack_id)),
    [subscriptions]
  );

  // Simple debounce for search
  const timerRef = useState<ReturnType<typeof setTimeout> | null>(null);
  const handleSearch = (value: string) => {
    setSearch(value);
    if (timerRef[0]) clearTimeout(timerRef[0]);
    timerRef[1](setTimeout(() => setDebouncedSearch(value), 300));
  };

  return (
    <div>
      <Header
        title="Community Rules"
        description="Browse and install shared detection rule packs from the Parry community."
      />

      <div className="space-y-6 p-6">
        {/* Search + Filters */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder="Search rule packs..."
              className="w-full rounded-md border border-border bg-background py-2 pl-10 pr-4 text-sm outline-none focus:border-primary"
            />
          </div>
          <div className="flex flex-wrap gap-1">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                  category === cat
                    ? "bg-primary text-primary-foreground"
                    : "bg-secondary text-muted-foreground hover:text-foreground"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        {/* Installed packs summary */}
        {subscriptions.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                Installed ({subscriptions.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {subscriptions.map((sub) => {
                  const pack = packs.find((p) => p.id === sub.pack_id);
                  return (
                    <div
                      key={sub.id}
                      className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5"
                    >
                      <span className="text-sm font-medium">
                        {pack?.name ?? sub.pack_id.slice(0, 8)}
                      </span>
                      <span className="text-xs text-muted-foreground">v{sub.installed_version}</span>
                      <button
                        onClick={() => uninstallPack.mutate(sub.pack_id)}
                        className="text-muted-foreground hover:text-red-400"
                        title="Uninstall"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Pack Grid */}
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading packs...</p>
        ) : packs.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Package className="h-10 w-10 text-muted-foreground" />
              <p className="text-sm font-medium">No rule packs found</p>
              <p className="max-w-sm text-xs text-muted-foreground">
                {search
                  ? "Try a different search term or category."
                  : "Be the first to publish a community rule pack!"}
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {packs.map((pack) => (
              <PackCard
                key={pack.id}
                pack={pack}
                isInstalled={subscribedIds.has(pack.id)}
                onInstall={() => installPack.mutate(pack.id)}
                onUninstall={() => uninstallPack.mutate(pack.id)}
                installing={installPack.isPending}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PackCard({
  pack,
  isInstalled,
  onInstall,
  onUninstall,
  installing,
}: {
  pack: CommunityPack;
  isInstalled: boolean;
  onInstall: () => void;
  onUninstall: () => void;
  installing: boolean;
}) {
  const colorClass = CATEGORY_COLORS[pack.category] || CATEGORY_COLORS.general;
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold">{pack.name}</h3>
            <div className="mt-1 flex items-center gap-2">
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${colorClass}`}>
                {pack.category}
              </span>
              <span className="text-[10px] text-muted-foreground">
                v{pack.version}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Download className="h-3 w-3" />
            {pack.install_count}
          </div>
        </div>

        {pack.description && (
          <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
            {pack.description}
          </p>
        )}

        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {pack.rules.length} rule{pack.rules.length !== 1 ? "s" : ""}
          </span>
          {isInstalled ? (
            <Button size="sm" variant="outline" onClick={onUninstall}>
              Uninstall
            </Button>
          ) : (
            <Button size="sm" onClick={onInstall} disabled={installing}>
              Install
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
