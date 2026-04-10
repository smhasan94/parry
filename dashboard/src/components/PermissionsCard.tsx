import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useAgentPermissions,
  useSetAgentPermissions,
  useDeleteAgentPermissions,
} from "@/hooks/usePermissions";
import { useRole } from "@/hooks/useRole";
import { Shield, Plus, X, AlertTriangle } from "lucide-react";

const MODE_LABELS: Record<string, { label: string; color: string }> = {
  enforcing: { label: "Enforcing", color: "bg-green-100 text-green-800" },
  dry_run: { label: "Dry Run", color: "bg-yellow-100 text-yellow-800" },
  disabled: { label: "Disabled", color: "bg-gray-100 text-gray-600" },
};

export function PermissionsCard({ agentId }: { agentId: string }) {
  const { data: perm, isLoading } = useAgentPermissions(agentId);
  const setPerm = useSetAgentPermissions();
  const deletePerm = useDeleteAgentPermissions();
  const { can } = useRole();
  const canEdit = can("admin");

  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<string>("disabled");
  const [defaultAction, setDefaultAction] = useState<string>("allow");
  const [allowedTools, setAllowedTools] = useState<string[]>([]);
  const [blockedTools, setBlockedTools] = useState<string[]>([]);
  const [newTool, setNewTool] = useState("");

  function startEditing() {
    setMode(perm?.mode || "disabled");
    setDefaultAction(perm?.default_action || "allow");
    setAllowedTools(perm?.allowed_tools || []);
    setBlockedTools(perm?.blocked_tools || []);
    setEditing(true);
  }

  function handleSave() {
    setPerm.mutate(
      {
        agentId,
        data: {
          mode,
          default_action: defaultAction,
          allowed_tools: allowedTools,
          blocked_tools: blockedTools,
        },
      },
      { onSuccess: () => setEditing(false) },
    );
  }

  function addTool(list: "allowed" | "blocked") {
    const name = newTool.trim();
    if (!name) return;
    if (list === "allowed") {
      setAllowedTools([...allowedTools, name]);
    } else {
      setBlockedTools([...blockedTools, name]);
    }
    setNewTool("");
  }

  function removeTool(list: "allowed" | "blocked", idx: number) {
    if (list === "allowed") {
      setAllowedTools(allowedTools.filter((_, i) => i !== idx));
    } else {
      setBlockedTools(blockedTools.filter((_, i) => i !== idx));
    }
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            Permission Boundaries
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">Loading...</p>
        </CardContent>
      </Card>
    );
  }

  const currentMode = perm?.mode || "disabled";
  const modeInfo = MODE_LABELS[currentMode] || { label: "Disabled", color: "bg-gray-100 text-gray-600" };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-sm">
          <span className="flex items-center gap-2">
            <Shield className="h-4 w-4" />
            Permission Boundaries
          </span>
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${modeInfo.color}`}>
            {modeInfo.label}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {editing ? (
          <div className="space-y-4">
            {/* Mode */}
            <div>
              <label className="text-xs font-medium">Mode</label>
              <select
                className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="disabled">Disabled</option>
                <option value="dry_run">Dry Run (log only)</option>
                <option value="enforcing">Enforcing (block violations)</option>
              </select>
            </div>

            {mode !== "disabled" && (
              <>
                {/* Default action */}
                <div>
                  <label className="text-xs font-medium">Default Action</label>
                  <select
                    className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    value={defaultAction}
                    onChange={(e) => setDefaultAction(e.target.value)}
                  >
                    <option value="allow">Allow (blocklist mode)</option>
                    <option value="deny">Deny (allowlist mode)</option>
                  </select>
                </div>

                {defaultAction === "deny" && (
                  <div className="flex items-start gap-2 rounded border border-yellow-200 bg-yellow-50 p-2 text-xs text-yellow-800">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    Only tools in the allowlist will be permitted. All others are denied.
                  </div>
                )}

                {/* Allowed tools */}
                <div>
                  <label className="text-xs font-medium">
                    {defaultAction === "deny" ? "Allowed Tools (required)" : "Allowed Tools"}
                  </label>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {allowedTools.map((tool, i) => (
                      <span
                        key={i}
                        className="flex items-center gap-1 rounded bg-green-100 px-2 py-0.5 text-xs font-mono text-green-800"
                      >
                        {tool}
                        <button onClick={() => removeTool("allowed", i)}>
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                  <div className="mt-1 flex gap-1">
                    <Input
                      value={newTool}
                      onChange={(e) => setNewTool(e.target.value)}
                      placeholder="tool_name"
                      className="h-8 font-mono text-xs"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addTool("allowed");
                        }
                      }}
                    />
                    <Button size="sm" variant="ghost" onClick={() => addTool("allowed")}>
                      <Plus className="h-3 w-3" />
                    </Button>
                  </div>
                </div>

                {/* Blocked tools */}
                <div>
                  <label className="text-xs font-medium">Blocked Tools</label>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {blockedTools.map((tool, i) => (
                      <span
                        key={i}
                        className="flex items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-xs font-mono text-red-800"
                      >
                        {tool}
                        <button onClick={() => removeTool("blocked", i)}>
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                  <div className="mt-1 flex gap-1">
                    <Input
                      value={newTool}
                      onChange={(e) => setNewTool(e.target.value)}
                      placeholder="tool_name"
                      className="h-8 font-mono text-xs"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addTool("blocked");
                        }
                      }}
                    />
                    <Button size="sm" variant="ghost" onClick={() => addTool("blocked")}>
                      <Plus className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </>
            )}

            <div className="flex gap-2">
              <Button size="sm" onClick={handleSave} disabled={setPerm.isPending}>
                {setPerm.isPending ? "Saving..." : "Save"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {!perm || perm.mode === "disabled" ? (
              <p className="text-xs text-muted-foreground">
                No permission boundaries configured. This agent can call any tool.
              </p>
            ) : (
              <>
                {perm.mode === "dry_run" && (
                  <div className="flex items-start gap-2 rounded border border-yellow-200 bg-yellow-50 p-2 text-xs text-yellow-800">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    Dry run — violations are logged but not blocked
                  </div>
                )}
                <div className="text-xs">
                  <span className="text-muted-foreground">Default: </span>
                  <span className="font-medium">
                    {perm.default_action === "deny"
                      ? "Deny (allowlist mode)"
                      : "Allow (blocklist mode)"}
                  </span>
                </div>
                {perm.allowed_tools.length > 0 && (
                  <div>
                    <p className="text-xs text-muted-foreground">Allowed:</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {perm.allowed_tools.map((t) => (
                        <span
                          key={t}
                          className="rounded bg-green-100 px-2 py-0.5 text-xs font-mono text-green-800"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {perm.blocked_tools.length > 0 && (
                  <div>
                    <p className="text-xs text-muted-foreground">Blocked:</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {perm.blocked_tools.map((t) => (
                        <span
                          key={t}
                          className="rounded bg-red-100 px-2 py-0.5 text-xs font-mono text-red-800"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {canEdit && (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={startEditing}>
                  {perm ? "Edit Permissions" : "Configure Permissions"}
                </Button>
                {perm && perm.mode !== "disabled" && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => deletePerm.mutate(agentId)}
                    disabled={deletePerm.isPending}
                    className="text-destructive hover:text-destructive"
                  >
                    Remove
                  </Button>
                )}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
