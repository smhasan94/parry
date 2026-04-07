import { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  useCustomRules,
  useCreateCustomRule,
  useDeleteCustomRule,
  useTestCustomRule,
  useUpdateCustomRule,
} from "@/hooks/useCustomRules";
import { useRole } from "@/hooks/useRole";
import type { CustomRule, CustomRuleInput } from "@/lib/api";
import { FileCode, Plus, Trash2, X } from "lucide-react";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-950/50 text-red-300 border-red-900",
  high: "bg-orange-950/50 text-orange-300 border-orange-900",
  medium: "bg-yellow-950/50 text-yellow-300 border-yellow-900",
  low: "bg-blue-950/50 text-blue-300 border-blue-900",
};

const EMPTY_DRAFT: CustomRuleInput = {
  name: "",
  pattern: "",
  target: "both",
  severity: "medium",
  enabled: true,
};

export function CustomRulesPage() {
  const { data: rules = [], isLoading } = useCustomRules();
  const createRule = useCreateCustomRule();
  const updateRule = useUpdateCustomRule();
  const deleteRule = useDeleteCustomRule();
  const { can } = useRole();
  const canMutate = can("admin");

  const [showCreate, setShowCreate] = useState(false);

  return (
    <div>
      <Header
        title="Custom Rules"
        description="Regex rules that run alongside Parry's built-in detectors"
        actions={
          canMutate ? (
            <Button size="sm" onClick={() => setShowCreate((v) => !v)}>
              <Plus className="h-4 w-4" />
              New Rule
            </Button>
          ) : undefined
        }
      />

      <div className="space-y-4 p-6">
        {showCreate && canMutate && (
          <RuleEditor
            onSubmit={(draft) =>
              createRule.mutate(draft, {
                onSuccess: () => setShowCreate(false),
              })
            }
            onCancel={() => setShowCreate(false)}
            submitLabel={createRule.isPending ? "Saving…" : "Save rule"}
          />
        )}

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading rules…</p>
        ) : rules.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <FileCode className="mb-4 h-12 w-12 text-muted-foreground" />
              <p className="text-sm font-medium">No custom rules yet</p>
              <p className="max-w-md text-center text-xs text-muted-foreground">
                Custom rules are regex patterns that run against prompts and
                responses. Use them to block competitor mentions, catch
                org-specific secrets, or enforce tone guidelines beyond Parry's
                built-in detectors.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="px-4 py-2 text-left font-medium">Name</th>
                    <th className="px-4 py-2 text-left font-medium">Pattern</th>
                    <th className="px-4 py-2 text-left font-medium">Target</th>
                    <th className="px-4 py-2 text-left font-medium">Severity</th>
                    <th className="px-4 py-2 text-left font-medium">Enabled</th>
                    {canMutate && <th className="px-4 py-2" />}
                  </tr>
                </thead>
                <tbody>
                  {rules.map((rule) => (
                    <RuleRow
                      key={rule.id}
                      rule={rule}
                      canMutate={canMutate}
                      onToggle={() =>
                        updateRule.mutate({
                          ruleId: rule.id,
                          body: { enabled: !rule.enabled },
                        })
                      }
                      onDelete={() => {
                        if (confirm(`Delete rule "${rule.name}"?`)) {
                          deleteRule.mutate(rule.id);
                        }
                      }}
                    />
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

interface RuleRowProps {
  rule: CustomRule;
  canMutate: boolean;
  onToggle: () => void;
  onDelete: () => void;
}

function RuleRow({ rule, canMutate, onToggle, onDelete }: RuleRowProps) {
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-4 py-3 font-medium">{rule.name}</td>
      <td className="px-4 py-3">
        <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">
          {rule.pattern}
        </code>
      </td>
      <td className="px-4 py-3 text-xs text-muted-foreground">{rule.target}</td>
      <td className="px-4 py-3">
        <Badge
          variant="outline"
          className={`border text-xs ${SEVERITY_STYLES[rule.severity] ?? ""}`}
        >
          {rule.severity}
        </Badge>
      </td>
      <td className="px-4 py-3">
        <button
          type="button"
          onClick={onToggle}
          disabled={!canMutate}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            rule.enabled ? "bg-primary" : "bg-secondary"
          } ${canMutate ? "" : "cursor-not-allowed opacity-50"}`}
          aria-label={`Toggle ${rule.name}`}
        >
          <span
            className={`inline-block h-3 w-3 transform rounded-full bg-background transition-transform ${
              rule.enabled ? "translate-x-5" : "translate-x-1"
            }`}
          />
        </button>
      </td>
      {canMutate && (
        <td className="px-4 py-3 text-right">
          <Button size="sm" variant="ghost" onClick={onDelete}>
            <Trash2 className="h-4 w-4 text-red-400" />
          </Button>
        </td>
      )}
    </tr>
  );
}

interface EditorProps {
  onSubmit: (draft: CustomRuleInput) => void;
  onCancel: () => void;
  submitLabel: string;
}

function RuleEditor({ onSubmit, onCancel, submitLabel }: EditorProps) {
  const [draft, setDraft] = useState<CustomRuleInput>(EMPTY_DRAFT);
  const [sample, setSample] = useState("");
  const testMutation = useTestCustomRule();

  // Auto-test when pattern or sample changes (debounced via effect)
  useEffect(() => {
    if (!draft.pattern || !sample) return;
    const handle = setTimeout(() => {
      testMutation.mutate({ pattern: draft.pattern, sample });
    }, 250);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.pattern, sample]);

  const testResult = testMutation.data;
  const testError = testResult?.error;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>New custom rule</CardTitle>
          <CardDescription>
            Patterns are case-insensitive by default and run on every event.
          </CardDescription>
        </div>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          <X className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Name</label>
            <Input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="Block competitor mentions"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Pattern (regex)</label>
            <Input
              value={draft.pattern}
              onChange={(e) => setDraft({ ...draft, pattern: e.target.value })}
              placeholder="\\b(CompetitorA|CompetitorB)\\b"
              className={testError ? "border-red-500" : ""}
            />
            {testError && (
              <p className="text-xs text-red-400">Invalid regex: {testError}</p>
            )}
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Target</label>
            <select
              value={draft.target}
              onChange={(e) =>
                setDraft({ ...draft, target: e.target.value as CustomRuleInput["target"] })
              }
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="prompt">Prompt only</option>
              <option value="response">Response only</option>
              <option value="both">Both (default)</option>
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Severity</label>
            <select
              value={draft.severity}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  severity: e.target.value as CustomRuleInput["severity"],
                })
              }
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Test sample (live match preview)
          </label>
          <textarea
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            placeholder="Paste sample text to check if your pattern matches…"
            rows={3}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          {sample && draft.pattern && !testError && testResult && (
            <p
              className={`text-xs ${testResult.matched ? "text-emerald-400" : "text-muted-foreground"}`}
            >
              {testResult.matched
                ? `✓ Matched: "${testResult.match}"`
                : "✗ No match"}
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => onSubmit(draft)}
            disabled={!draft.name || !draft.pattern || !!testError}
          >
            {submitLabel}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
