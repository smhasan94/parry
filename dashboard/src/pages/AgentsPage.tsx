import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAgents, useCreateAgent, useRecomputeAllBaselines } from "@/hooks/useAgents";
import { useRole } from "@/hooks/useRole";
import { Bot, Plus, RefreshCw } from "lucide-react";

export function AgentsPage() {
  const { data: agents = [], isLoading } = useAgents();
  const createAgent = useCreateAgent();
  const recomputeAll = useRecomputeAllBaselines();
  const { can } = useRole();
  const canMutate = can("admin");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const handleCreate = () => {
    if (!newName.trim()) return;
    createAgent.mutate(
      { name: newName.trim(), description: newDesc.trim() || undefined },
      {
        onSuccess: () => {
          setNewName("");
          setNewDesc("");
          setShowCreate(false);
        },
      }
    );
  };

  return (
    <div>
      <Header
        title="Agents"
        description="Manage your registered AI agents"
        actions={
          canMutate ? (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => recomputeAll.mutate()}
                disabled={recomputeAll.isPending || agents.length === 0}
                title="Recompute baselines for every agent in this org"
              >
                <RefreshCw
                  className={`h-4 w-4 ${recomputeAll.isPending ? "animate-spin" : ""}`}
                />
                {recomputeAll.isPending ? "Recomputing..." : "Recompute all baselines"}
              </Button>
              <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
                <Plus className="h-4 w-4" />
                New Agent
              </Button>
            </div>
          ) : undefined
        }
      />

      <div className="space-y-4 p-6">
        {showCreate && (
          <Card>
            <CardContent className="flex items-end gap-4 p-4">
              <div className="flex-1 space-y-2">
                <label className="text-sm font-medium">Name</label>
                <Input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="my-agent"
                />
              </div>
              <div className="flex-1 space-y-2">
                <label className="text-sm font-medium">Description</label>
                <Input
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="Optional description"
                />
              </div>
              <Button onClick={handleCreate} disabled={createAgent.isPending}>
                {createAgent.isPending ? "Creating..." : "Create"}
              </Button>
            </CardContent>
          </Card>
        )}

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading agents...</p>
        ) : agents.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Bot className="mb-4 h-12 w-12 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">No agents registered yet.</p>
              <p className="text-xs text-muted-foreground">
                Install the Parry SDK and call parry.init() to register your first agent.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => (
              <Link key={agent.id} to="/agents/$agentId" params={{ agentId: agent.id }}>
                <Card className="cursor-pointer transition-colors hover:border-primary/50">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <Bot className="h-5 w-5 text-muted-foreground" />
                        <div>
                          <p className="font-medium">{agent.name}</p>
                          {agent.description && (
                            <p className="text-sm text-muted-foreground">{agent.description}</p>
                          )}
                        </div>
                      </div>
                      <div
                        className={`h-2.5 w-2.5 rounded-full ${agent.is_active ? "bg-green-500" : "bg-zinc-500"}`}
                      />
                    </div>
                    <div className="mt-4 flex gap-4 text-xs text-muted-foreground">
                      <span>Created {new Date(agent.created_at).toLocaleDateString()}</span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
