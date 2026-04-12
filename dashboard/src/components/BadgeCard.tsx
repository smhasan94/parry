import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useUpdateAgent } from "@/hooks/useAgents";
import { useRole } from "@/hooks/useRole";
import { Check, Copy, Shield } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "https://api.parry.dev";

interface BadgeCardProps {
  agentId: string;
  agentName: string;
  badgePublic: boolean;
}

export function BadgeCard({ agentId, agentName, badgePublic }: BadgeCardProps) {
  const updateAgent = useUpdateAgent();
  const { can } = useRole();
  const isAdmin = can("admin");
  const [copied, setCopied] = useState<string | null>(null);

  const badgeUrl = `${API_BASE}/api/v1/badges/${agentId}.svg`;
  const markdownSnippet = `[![Parry Security](${badgeUrl})](https://app.parry.dev/agents/${agentId})`;
  const htmlSnippet = `<a href="https://app.parry.dev/agents/${agentId}"><img src="${badgeUrl}" alt="Parry Security Score for ${agentName}"></a>`;

  function copyToClipboard(text: string, label: string) {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Shield className="h-4 w-4" />
          Security Badge
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">
              {badgePublic
                ? "Badge is public. Embed it in your README or docs."
                : "Enable the public badge to share your agent's security score."}
            </p>
          </div>
          {isAdmin && (
            <Button
              size="sm"
              variant={badgePublic ? "outline" : "default"}
              disabled={updateAgent.isPending}
              onClick={() =>
                updateAgent.mutate({
                  agentId,
                  data: { badge_public: !badgePublic },
                })
              }
            >
              {updateAgent.isPending
                ? "Saving..."
                : badgePublic
                  ? "Disable"
                  : "Enable"}
            </Button>
          )}
        </div>

        {badgePublic && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-3">
              <img
                src={badgeUrl}
                alt={`Parry security badge for ${agentName}`}
                className="h-5"
              />
              <span className="text-xs text-muted-foreground">Live preview</span>
            </div>

            <div className="space-y-2">
              <SnippetRow
                label="Markdown"
                value={markdownSnippet}
                copied={copied === "md"}
                onCopy={() => copyToClipboard(markdownSnippet, "md")}
              />
              <SnippetRow
                label="HTML"
                value={htmlSnippet}
                copied={copied === "html"}
                onCopy={() => copyToClipboard(htmlSnippet, "html")}
              />
              <SnippetRow
                label="URL"
                value={badgeUrl}
                copied={copied === "url"}
                onCopy={() => copyToClipboard(badgeUrl, "url")}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SnippetRow({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-xs font-medium text-muted-foreground">
        {label}
      </span>
      <code className="flex-1 truncate rounded bg-secondary px-2 py-1 font-mono text-xs text-foreground">
        {value}
      </code>
      <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={onCopy}>
        {copied ? (
          <Check className="h-3 w-3 text-green-400" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
      </Button>
    </div>
  );
}
