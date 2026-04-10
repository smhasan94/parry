import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useAgentGroups,
  useCreateAgentGroup,
  useDeleteAgentGroup,
} from "@/hooks/useAgentGroups";
import { useRole } from "@/hooks/useRole";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Users, Plus, Trash2, Bot } from "lucide-react";
import type { AgentGroup } from "@/lib/types";

export function AgentGroupsPage() {
  const { data: groups = [], isLoading, isError, error, refetch } = useAgentGroups();
  const createGroup = useCreateAgentGroup();
  const deleteGroup = useDeleteAgentGroup();
  const { can } = useRole();
  const canCreate = can("admin");

  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  function handleCreate() {
    if (!name.trim()) return;
    createGroup.mutate(
      { name: name.trim(), description: description.trim() || undefined },
      {
        onSuccess: () => {
          setName("");
          setDescription("");
          setShowCreate(false);
        },
      },
    );
  }

  return (
    <div>
      <Header
        title="Agent Groups"
        description="Organize agents into teams with inherited permissions and policies"
        actions={
          canCreate ? (
            <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
              <Plus className="mr-1 h-4 w-4" />
              New Group
            </Button>
          ) : undefined
        }
      />

      <div className="space-y-4 p-6">
        {showCreate && (
          <Card>
            <CardContent className="flex items-end gap-4 p-4">
              <div className="flex-1 space-y-1">
                <label className="text-sm font-medium">Group Name</label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Production Agents"
                />
              </div>
              <div className="flex-1 space-y-1">
                <label className="text-sm font-medium">Description</label>
                <Input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Customer-facing production agents"
                />
              </div>
              <Button onClick={handleCreate} disabled={createGroup.isPending || !name.trim()}>
                {createGroup.isPending ? "Creating..." : "Create"}
              </Button>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                Cancel
              </Button>
            </CardContent>
          </Card>
        )}

        {isLoading ? (
          <LoadingState label="Loading agent groups" />
        ) : isError ? (
          <ErrorState error={error} title="Couldn't load groups" onRetry={() => refetch()} />
        ) : groups.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Users className="h-12 w-12 text-muted-foreground" />
              <p className="text-sm font-medium">No agent groups yet</p>
              <p className="max-w-sm text-xs text-muted-foreground">
                Create groups to organize your agents into teams. Groups can have
                their own permission boundaries that all member agents inherit.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {groups.map((g: AgentGroup) => (
              <Card key={g.id}>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="font-medium">{g.name}</p>
                      {g.description && (
                        <p className="mt-0.5 text-xs text-muted-foreground">{g.description}</p>
                      )}
                    </div>
                    {canCreate && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => deleteGroup.mutate(g.id)}
                        disabled={deleteGroup.isPending}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                  <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                    <Bot className="h-3.5 w-3.5" />
                    <span>
                      {g.agent_count} agent{g.agent_count !== 1 ? "s" : ""}
                    </span>
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
