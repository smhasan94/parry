import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { usePolicies, useCreatePolicy, useDeletePolicy } from "@/hooks/usePolicies";
import { FileCheck, Plus, Trash2 } from "lucide-react";
import { ErrorState, LoadingState } from "@/components/ui/states";

export function PoliciesPage() {
  const { data: policies = [], isLoading, isError, error, refetch } = usePolicies();
  const createPolicy = useCreatePolicy();
  const deletePolicy = useDeletePolicy();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    allowed_tools: "",
    blocked_tools: "",
    max_token_budget: "",
    forbidden_patterns: "",
  });

  const handleCreate = () => {
    if (!form.name.trim()) return;
    createPolicy.mutate(
      {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        allowed_tools: form.allowed_tools ? form.allowed_tools.split(",").map((s) => s.trim()) : undefined,
        blocked_tools: form.blocked_tools ? form.blocked_tools.split(",").map((s) => s.trim()) : undefined,
        max_token_budget: form.max_token_budget ? Number(form.max_token_budget) : undefined,
        forbidden_patterns: form.forbidden_patterns
          ? form.forbidden_patterns.split(",").map((s) => s.trim())
          : undefined,
      },
      {
        onSuccess: () => {
          setForm({ name: "", description: "", allowed_tools: "", blocked_tools: "", max_token_budget: "", forbidden_patterns: "" });
          setShowCreate(false);
        },
      }
    );
  };

  return (
    <div>
      <Header
        title="Policies"
        description="Define what your agents can and cannot do"
        actions={
          <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
            <Plus className="h-4 w-4" />
            New Policy
          </Button>
        }
      />

      <div className="space-y-4 p-6">
        {showCreate && (
          <Card>
            <CardHeader>
              <CardTitle>Create Policy</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Name</label>
                  <Input
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="e.g. production-agents"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Max Token Budget</label>
                  <Input
                    type="number"
                    value={form.max_token_budget}
                    onChange={(e) => setForm({ ...form, max_token_budget: e.target.value })}
                    placeholder="e.g. 100000"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Description</label>
                <Textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="What this policy enforces"
                  rows={2}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Allowed Tools (comma-separated)</label>
                  <Input
                    value={form.allowed_tools}
                    onChange={(e) => setForm({ ...form, allowed_tools: e.target.value })}
                    placeholder="search, read_file, calculate"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Blocked Tools (comma-separated)</label>
                  <Input
                    value={form.blocked_tools}
                    onChange={(e) => setForm({ ...form, blocked_tools: e.target.value })}
                    placeholder="exec_code, shell, delete"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Forbidden Patterns (comma-separated)</label>
                <Input
                  value={form.forbidden_patterns}
                  onChange={(e) => setForm({ ...form, forbidden_patterns: e.target.value })}
                  placeholder="ignore previous, system prompt"
                />
              </div>
              <Button onClick={handleCreate} disabled={createPolicy.isPending}>
                {createPolicy.isPending ? "Creating..." : "Create Policy"}
              </Button>
            </CardContent>
          </Card>
        )}

        {isLoading ? (
          <Card>
            <CardContent>
              <LoadingState label="Loading policies" />
            </CardContent>
          </Card>
        ) : isError ? (
          <Card>
            <CardContent>
              <ErrorState
                error={error}
                title="Couldn't load policies"
                onRetry={() => refetch()}
              />
            </CardContent>
          </Card>
        ) : policies.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
              <FileCheck className="h-12 w-12 text-muted-foreground" />
              <p className="text-sm font-medium">No policies defined yet</p>
              <p className="max-w-sm text-xs text-muted-foreground">
                Policies tell Parry what tools your agents can call, which
                domains they can touch, and which patterns to block. Without
                a policy the detection engine still catches prompt injection
                and jailbreaks, but tool guardrails are off.
              </p>
              <Button
                size="sm"
                className="mt-2"
                onClick={() => setShowCreate(true)}
              >
                <Plus className="h-4 w-4" />
                Create your first policy
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {policies.map((policy) => (
              <Card key={policy.id}>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="font-medium">{policy.name}</h3>
                        <Badge variant={policy.is_active ? "secondary" : "outline"}>
                          {policy.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </div>
                      {policy.description && (
                        <p className="mt-1 text-sm text-muted-foreground">{policy.description}</p>
                      )}
                      <div className="mt-3 flex flex-wrap gap-2">
                        {policy.allowed_tools?.map((tool) => (
                          <Badge key={tool} variant="outline" className="text-green-400">
                            + {tool}
                          </Badge>
                        ))}
                        {policy.blocked_tools?.map((tool) => (
                          <Badge key={tool} variant="outline" className="text-red-400">
                            - {tool}
                          </Badge>
                        ))}
                        {policy.max_token_budget && (
                          <Badge variant="outline">Max {policy.max_token_budget.toLocaleString()} tokens</Badge>
                        )}
                      </div>
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => deletePolicy.mutate(policy.id)}
                    >
                      <Trash2 className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
