import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  usePosture,
  useAISystems,
  useCreateAISystem,
  useDeleteAISystem,
  useSuppliers,
  useSystemFRIAs,
  useSeriousIncidents,
  useRequestAuditorBundle,
} from "@/hooks/useCompliance";
import { useRole } from "@/hooks/useRole";
import { ErrorState, LoadingState } from "@/components/ui/states";
import {
  Shield,
  Plus,
  Download,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  MinusCircle,
  Trash2,
} from "lucide-react";
import type {
  AISystem,
  Obligation,
  ObligationStatus,
  RiskLevel,
} from "@/lib/types";

type Tab = "posture" | "systems" | "suppliers" | "fria" | "incidents";

const STATUS_CONFIG: Record<
  ObligationStatus,
  { icon: typeof CheckCircle2; color: string; bg: string }
> = {
  green: { icon: CheckCircle2, color: "text-green-600", bg: "border-green-200 bg-green-50" },
  yellow: { icon: AlertTriangle, color: "text-yellow-600", bg: "border-yellow-200 bg-yellow-50" },
  red: { icon: XCircle, color: "text-red-600", bg: "border-red-200 bg-red-50" },
  na: { icon: MinusCircle, color: "text-gray-400", bg: "border-gray-200 bg-gray-50" },
};

const RISK_COLORS: Record<RiskLevel, string> = {
  unacceptable: "bg-red-100 text-red-800",
  high: "bg-orange-100 text-orange-800",
  limited: "bg-yellow-100 text-yellow-800",
  minimal: "bg-green-100 text-green-800",
};

function ObligationCard({ obligation }: { obligation: Obligation }) {
  const config = STATUS_CONFIG[obligation.status];
  const Icon = config.icon;
  return (
    <Card className={`border ${config.bg}`}>
      <CardContent className="flex items-start gap-3 p-4">
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${config.color}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-muted-foreground">
              {obligation.article}
            </span>
            <span className="text-sm font-medium">{obligation.title}</span>
          </div>
          {obligation.remediation && (
            <p className="mt-1 text-xs text-muted-foreground">
              {obligation.remediation}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function PostureTab() {
  const { data, isLoading, isError, error, refetch } = usePosture();
  const bundle = useRequestAuditorBundle();
  const { can } = useRole();

  if (isLoading) return <LoadingState label="Loading compliance posture" />;
  if (isError) return <ErrorState error={error} title="Couldn't load posture" onRetry={() => refetch()} />;
  if (!data) return null;

  const overallConfig = STATUS_CONFIG[data.overall_status];
  const OverallIcon = overallConfig.icon;

  return (
    <div className="space-y-4">
      <Card className={`border-2 ${overallConfig.bg}`}>
        <CardContent className="flex items-center justify-between p-6">
          <div className="flex items-center gap-3">
            <OverallIcon className={`h-8 w-8 ${overallConfig.color}`} />
            <div>
              <p className="text-lg font-semibold">
                Overall Compliance: {data.overall_status.toUpperCase()}
              </p>
              <p className="text-sm text-muted-foreground">
                {data.obligations.filter((o) => o.status === "green").length} of{" "}
                {data.obligations.filter((o) => o.status !== "na").length} obligations met
              </p>
            </div>
          </div>
          {can("owner") && (
            <Button
              onClick={() => bundle.mutate({})}
              disabled={bundle.isPending}
              variant="outline"
            >
              <Download className="mr-2 h-4 w-4" />
              {bundle.isPending ? "Generating..." : "Download Auditor Bundle"}
            </Button>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-3">
        {data.obligations.map((o) => (
          <ObligationCard key={o.id} obligation={o} />
        ))}
      </div>
    </div>
  );
}

function SystemsTab() {
  const { data: systems = [], isLoading, isError, error, refetch } = useAISystems();
  const createSystem = useCreateAISystem();
  const deleteSystem = useDeleteAISystem();
  const { can } = useRole();
  const canMutate = can("admin");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    name: "",
    risk_level: "minimal" as RiskLevel,
    intended_purpose: "",
    deployer_name: "",
  });

  const handleCreate = () => {
    if (!form.name.trim() || !form.intended_purpose.trim()) return;
    createSystem.mutate(
      {
        name: form.name.trim(),
        risk_level: form.risk_level,
        intended_purpose: form.intended_purpose.trim(),
        deployer_name: form.deployer_name.trim() || undefined,
      },
      {
        onSuccess: () => {
          setForm({ name: "", risk_level: "minimal", intended_purpose: "", deployer_name: "" });
          setShowCreate(false);
        },
      },
    );
  };

  if (isLoading) return <LoadingState label="Loading AI systems" />;
  if (isError) return <ErrorState error={error} title="Couldn't load systems" onRetry={() => refetch()} />;

  return (
    <div className="space-y-4">
      {canMutate && (
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
            <Plus className="mr-1 h-4 w-4" />
            Add System
          </Button>
        </div>
      )}

      {showCreate && (
        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium">System Name *</label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Customer Support AI"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Risk Level *</label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={form.risk_level}
                  onChange={(e) =>
                    setForm({ ...form, risk_level: e.target.value as RiskLevel })
                  }
                >
                  <option value="minimal">Minimal</option>
                  <option value="limited">Limited</option>
                  <option value="high">High (FRIA required)</option>
                  <option value="unacceptable">Unacceptable</option>
                </select>
              </div>
            </div>
            <div>
              <label className="text-sm font-medium">Intended Purpose *</label>
              <Input
                value={form.intended_purpose}
                onChange={(e) => setForm({ ...form, intended_purpose: e.target.value })}
                placeholder="Automated customer inquiry routing and response generation"
              />
            </div>
            <div>
              <label className="text-sm font-medium">Deployer Name</label>
              <Input
                value={form.deployer_name}
                onChange={(e) => setForm({ ...form, deployer_name: e.target.value })}
                placeholder="Acme Corp"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                Cancel
              </Button>
              <Button onClick={handleCreate} disabled={createSystem.isPending}>
                {createSystem.isPending ? "Creating..." : "Register System"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {systems.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <Shield className="h-12 w-12 text-muted-foreground" />
            <p className="text-sm font-medium">No AI systems registered</p>
            <p className="max-w-sm text-xs text-muted-foreground">
              Register your AI systems to track compliance obligations under the EU AI Act.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {systems.map((s: AISystem) => (
            <Card key={s.id}>
              <CardContent className="flex items-center justify-between p-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{s.name}</span>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${RISK_COLORS[s.risk_level]}`}
                    >
                      {s.risk_level}
                    </span>
                    {s.fria_required && (
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${
                          s.fria_status === "approved"
                            ? "bg-green-100 text-green-800"
                            : s.fria_status === "missing"
                              ? "bg-red-100 text-red-800"
                              : "bg-yellow-100 text-yellow-800"
                        }`}
                      >
                        FRIA: {s.fria_status}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {s.intended_purpose}
                  </p>
                </div>
                {canMutate && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => deleteSystem.mutate(s.id)}
                    disabled={deleteSystem.isPending}
                  >
                    <Trash2 className="h-4 w-4 text-muted-foreground" />
                  </Button>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function SuppliersTab() {
  const { data: systems = [], isLoading } = useAISystems();

  if (isLoading) return <LoadingState label="Loading suppliers" />;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Suppliers are auto-populated daily from your agent event data. Each supplier
        record maps a model provider to the AI system that uses it.
      </p>
      {systems.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No systems registered. Register AI systems to see their suppliers.
          </CardContent>
        </Card>
      ) : (
        systems.map((s: AISystem) => (
          <SupplierList key={s.id} system={s} />
        ))
      )}
    </div>
  );
}

function SupplierList({ system }: { system: AISystem }) {
  const { data: suppliers = [], isLoading } = useSuppliers(system.id);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{system.name}</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-xs text-muted-foreground">Loading...</p>
        ) : suppliers.length === 0 ? (
          <p className="text-xs text-muted-foreground">No supplier data yet</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="pb-2">Supplier</th>
                <th className="pb-2">Model</th>
                <th className="pb-2">Events</th>
                <th className="pb-2">Last Used</th>
                <th className="pb-2">Jurisdiction</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <tr key={s.id} className="border-b last:border-0">
                  <td className="py-2 font-medium">{s.supplier_name}</td>
                  <td className="py-2 font-mono">{s.model_id}</td>
                  <td className="py-2">{s.event_count.toLocaleString()}</td>
                  <td className="py-2">
                    {new Date(s.last_used_at).toLocaleDateString()}
                  </td>
                  <td className="py-2">{s.jurisdiction || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function FRIATab() {
  const { data: systems = [], isLoading } = useAISystems();

  if (isLoading) return <LoadingState label="Loading FRIAs" />;

  const highRisk = systems.filter((s: AISystem) => s.risk_level === "high");

  if (highRisk.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No high-risk systems registered. FRIAs are required for high-risk AI
          systems under Article 27.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {highRisk.map((s: AISystem) => (
        <FRIASystemCard key={s.id} system={s} />
      ))}
    </div>
  );
}

function FRIASystemCard({ system }: { system: AISystem }) {
  const { data: frias = [], isLoading } = useSystemFRIAs(system.id);
  const createFRIA = useCreateFRIA();
  const approveFRIA = useApproveFRIA();
  const { can } = useRole();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm">{system.name}</CardTitle>
        {can("admin") && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => createFRIA.mutate(system.id)}
            disabled={createFRIA.isPending}
          >
            {createFRIA.isPending ? "Creating..." : "New FRIA Draft"}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-xs text-muted-foreground">Loading...</p>
        ) : frias.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No FRIA generated yet for this system
          </p>
        ) : (
          <div className="space-y-2">
            {frias.map((doc) => (
              <div
                key={doc.id}
                className="flex items-center justify-between rounded border p-3 text-xs"
              >
                <div>
                  <span className="font-medium">v{doc.version}</span>
                  <span
                    className={`ml-2 rounded px-1.5 py-0.5 text-xs font-medium ${
                      doc.status === "approved"
                        ? "bg-green-100 text-green-800"
                        : doc.status === "draft"
                          ? "bg-yellow-100 text-yellow-800"
                          : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    {doc.status}
                  </span>
                  <span className="ml-2 text-muted-foreground">
                    {new Date(doc.generated_at).toLocaleDateString()}
                  </span>
                  {doc.approved_by && (
                    <span className="ml-2 text-muted-foreground">
                      by {doc.approved_by}
                    </span>
                  )}
                </div>
                {doc.status === "draft" && can("owner") && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => approveFRIA.mutate({ friaId: doc.id })}
                    disabled={approveFRIA.isPending}
                  >
                    Approve
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SeriousIncidentsTab() {
  const { data: reports = [], isLoading, isError, error, refetch } =
    useSeriousIncidents();
  const finalize = useFinalizeSeriousReport();
  const { can } = useRole();

  if (isLoading) return <LoadingState label="Loading serious incidents" />;
  if (isError) return <ErrorState error={error} title="Couldn't load reports" onRetry={() => refetch()} />;

  if (reports.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No serious incident reports. Reports are created from CRITICAL incidents
          that may require notification to authorities under Article 73.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {reports.map((r) => {
        const isOverdue =
          r.days_remaining !== null && r.days_remaining < 0 && !r.reported_to_authority_at;
        return (
          <Card key={r.id} className={isOverdue ? "border-red-300" : ""}>
            <CardContent className="flex items-center justify-between p-4">
              <div>
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">Report v{r.report_version}</span>
                  {r.reported_to_authority_at ? (
                    <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
                      Reported
                    </span>
                  ) : isOverdue ? (
                    <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                      OVERDUE ({Math.abs(r.days_remaining!)}d)
                    </span>
                  ) : (
                    <span className="rounded bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-800">
                      {r.days_remaining}d remaining
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Deadline: {new Date(r.deadline_at).toLocaleDateString()}
                  {r.authority_jurisdiction && ` | ${r.authority_jurisdiction}`}
                </p>
              </div>
              {!r.reported_to_authority_at && can("owner") && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => finalize.mutate(r.id)}
                  disabled={finalize.isPending}
                >
                  {finalize.isPending ? "Finalizing..." : "Finalize & Submit"}
                </Button>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

import {
  useCreateFRIA,
  useApproveFRIA,
  useFinalizeSeriousReport,
} from "@/hooks/useCompliance";

export function CompliancePage() {
  const [tab, setTab] = useState<Tab>("posture");

  const tabs: { id: Tab; label: string }[] = [
    { id: "posture", label: "Posture" },
    { id: "systems", label: "Systems" },
    { id: "suppliers", label: "Suppliers" },
    { id: "fria", label: "FRIA" },
    { id: "incidents", label: "Serious Incidents" },
  ];

  return (
    <div>
      <Header
        title="EU AI Act Compliance"
        description="Article 26 deployer obligations — posture, systems register, FRIA, incident reporting"
      />

      <div className="border-b border-border px-6">
        <div className="flex gap-4">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`border-b-2 px-1 py-3 text-sm font-medium transition-colors ${
                tab === t.id
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-6">
        {tab === "posture" && <PostureTab />}
        {tab === "systems" && <SystemsTab />}
        {tab === "suppliers" && <SuppliersTab />}
        {tab === "fria" && <FRIATab />}
        {tab === "incidents" && <SeriousIncidentsTab />}
      </div>
    </div>
  );
}
