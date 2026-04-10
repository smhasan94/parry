import { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRole } from "@/hooks/useRole";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";
import { Download, FileText, Loader2, Clock, Plus, Trash2 } from "lucide-react";
import type { ScheduledReport } from "@/lib/types";

/**
 * Compliance Report export UI.
 *
 * Admin+ only. Calls GET /api/v1/reports/compliance with a start/end
 * window (backend caps at 90 days for the sync path), streams the PDF
 * back, and triggers a browser download. The last 5 generated reports
 * are tracked in localStorage so admins can re-download recent exports
 * without rebuilding them — metadata only, we do not cache PDF bytes.
 */

const RECENT_KEY = "parry.reports.recent";
const MAX_RECENT = 5;
const MAX_DAYS = 90;

interface RecentReport {
  start: string;
  end: string;
  generatedAt: string;
  bytes: number;
}

function loadRecent(): RecentReport[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.slice(0, MAX_RECENT) : [];
  } catch {
    return [];
  }
}

function saveRecent(entries: RecentReport[]): void {
  localStorage.setItem(RECENT_KEY, JSON.stringify(entries.slice(0, MAX_RECENT)));
}

function daysBetween(start: string, end: string): number {
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  if (Number.isNaN(s) || Number.isNaN(e)) return 0;
  return Math.round((e - s) / (1000 * 60 * 60 * 24));
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function defaultRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 30);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

export function ReportsPage() {
  const { can } = useRole();
  const canExport = can("admin");

  const initial = defaultRange();
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentReport[]>([]);

  useEffect(() => {
    setRecent(loadRecent());
  }, []);

  const span = daysBetween(start, end);
  const spanInvalid = span <= 0 || span > MAX_DAYS;

  async function handleGenerate(useStart: string, useEnd: string) {
    if (!canExport) return;
    setError(null);
    setLoading(true);
    try {
      const blob = await api.downloadComplianceReport(useStart, useEnd);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `parry-compliance-${useStart}-${useEnd}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      const entry: RecentReport = {
        start: useStart,
        end: useEnd,
        generatedAt: new Date().toISOString(),
        bytes: blob.size,
      };
      const next = [entry, ...recent.filter(
        (r) => !(r.start === useStart && r.end === useEnd),
      )].slice(0, MAX_RECENT);
      setRecent(next);
      saveRecent(next);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Report generation failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <Header
        title="Compliance Reports"
        description="Generate SOC 2 / EU AI Act-ready PDFs summarizing agent activity, detections, and policy posture"
      />

      <div className="space-y-6 p-6">
        {!canExport && (
          <Card>
            <CardContent className="py-6">
              <p className="text-sm text-muted-foreground">
                You have read-only access. Compliance reports can be generated
                by an organization admin.
              </p>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Generate Report
            </CardTitle>
            <CardDescription>
              Reports summarize events, detections, incidents, policies, and
              agents for the selected window. Raw prompt and response content
              is intentionally excluded. Maximum window: {MAX_DAYS} days.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-end gap-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  Start date
                </label>
                <Input
                  type="date"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                  disabled={!canExport || loading}
                  className="w-44"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  End date
                </label>
                <Input
                  type="date"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  disabled={!canExport || loading}
                  className="w-44"
                />
              </div>
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">
                  Window
                </div>
                <div
                  className={`text-sm ${
                    spanInvalid ? "text-red-400" : "text-foreground"
                  }`}
                >
                  {span > 0 ? `${span} day${span === 1 ? "" : "s"}` : "—"}
                </div>
              </div>
              <Button
                onClick={() => handleGenerate(start, end)}
                disabled={!canExport || loading || spanInvalid}
              >
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Generating…
                  </>
                ) : (
                  <>
                    <Download className="h-4 w-4" />
                    Generate PDF
                  </>
                )}
              </Button>
            </div>

            {spanInvalid && span > MAX_DAYS && (
              <p className="text-xs text-red-400">
                Windows longer than {MAX_DAYS} days are not yet supported. Narrow
                the range and retry.
              </p>
            )}
            {error && <p className="text-xs text-red-400">{error}</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent Reports</CardTitle>
            <CardDescription>
              The last {MAX_RECENT} reports generated from this browser.
              Re-generating re-renders from current data.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {recent.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <FileText className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm font-medium">No reports generated yet</p>
                <p className="max-w-sm text-xs text-muted-foreground">
                  Pick a date range above and click Generate PDF. The last
                  {" "}
                  {MAX_RECENT} reports you generate from this browser will
                  show up here so you can re-download without re-selecting
                  the window.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {recent.map((r) => (
                  <li
                    key={`${r.start}-${r.end}-${r.generatedAt}`}
                    className="flex items-center justify-between py-3"
                  >
                    <div>
                      <div className="text-sm font-medium">
                        {r.start} → {r.end}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Generated {new Date(r.generatedAt).toLocaleString()} ·{" "}
                        {formatBytes(r.bytes)}
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!canExport || loading}
                      onClick={() => handleGenerate(r.start, r.end)}
                    >
                      <Download className="h-4 w-4" />
                      Re-generate
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        {/* Scheduled Reports */}
        <ScheduledReportsCard />
      </div>
    </div>
  );
}

function ScheduledReportsCard() {
  const qc = useQueryClient();
  const { data: schedules = [], isLoading } = useQuery({
    queryKey: ["scheduled-reports"],
    queryFn: () => api.listScheduledReports(),
  });
  const createSchedule = useMutation({
    mutationFn: (data: { schedule: string; recipients: string[]; report_type?: string }) =>
      api.createScheduledReport(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scheduled-reports"] });
      toast("Report schedule created", "success");
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
  const deleteSchedule = useMutation({
    mutationFn: (id: string) => api.deleteScheduledReport(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scheduled-reports"] });
      toast("Schedule removed", "success");
    },
  });

  const { can } = useRole();
  const canCreate = can("admin");
  const [showCreate, setShowCreate] = useState(false);
  const [schedule, setSchedule] = useState("weekly");
  const [emails, setEmails] = useState("");

  function handleCreate() {
    const recipients = emails.split(",").map((e) => e.trim()).filter(Boolean);
    if (!recipients.length) return;
    createSchedule.mutate(
      { schedule, recipients },
      { onSuccess: () => { setEmails(""); setShowCreate(false); } },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Scheduled Reports
          </span>
          {canCreate && (
            <Button size="sm" variant="outline" onClick={() => setShowCreate(!showCreate)}>
              <Plus className="mr-1 h-3 w-3" />
              New Schedule
            </Button>
          )}
        </CardTitle>
        <CardDescription>
          Automated security report digests delivered to your team via email
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {showCreate && (
          <div className="space-y-2 rounded border p-3">
            <div className="flex gap-2">
              <select
                className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
                value={schedule}
                onChange={(e) => setSchedule(e.target.value)}
              >
                <option value="weekly">Weekly (Monday)</option>
                <option value="monthly">Monthly (1st)</option>
              </select>
              <Input
                value={emails}
                onChange={(e) => setEmails(e.target.value)}
                placeholder="alice@acme.com, bob@acme.com"
                className="flex-1 text-sm"
              />
              <Button size="sm" onClick={handleCreate} disabled={createSchedule.isPending}>
                {createSchedule.isPending ? "Creating..." : "Create"}
              </Button>
            </div>
          </div>
        )}

        {isLoading ? (
          <p className="text-xs text-muted-foreground">Loading...</p>
        ) : schedules.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No report schedules configured. Create one to receive automated
            security digests.
          </p>
        ) : (
          schedules.map((s: ScheduledReport) => (
            <div key={s.id} className="flex items-center justify-between rounded border p-3 text-xs">
              <div>
                <span className="font-medium capitalize">{s.schedule}</span>
                <span className="mx-2 text-muted-foreground">→</span>
                <span className="text-muted-foreground">
                  {s.recipients.join(", ")}
                </span>
                <div className="mt-1 text-muted-foreground">
                  Next: {new Date(s.next_send_at).toLocaleDateString()}
                  {s.last_sent_at && (
                    <span className="ml-2">
                      Last: {new Date(s.last_sent_at).toLocaleDateString()}
                    </span>
                  )}
                  {!s.is_active && (
                    <span className="ml-2 rounded bg-red-100 px-1 text-red-700">Paused</span>
                  )}
                </div>
              </div>
              {canCreate && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => deleteSchedule.mutate(s.id)}
                  disabled={deleteSchedule.isPending}
                  className="text-destructive hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
