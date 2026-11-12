"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/ui/Card";
import { formatDuration, formatJson, runsApi, type Run, type RunsPage } from "@/lib/runs";

const PAGE_SIZE = 25;

const STATUS_CLS: Record<string, string> = {
  ok: "text-m-ok", error: "text-m-bad", rejected: "text-m-muted", pending: "text-m-warn", approved: "text-m-info",
};
const RISK_CLS: Record<string, string> = {
  read: "text-m-muted",
  write: "text-m-warn",
  destructive: "text-m-bad",
};

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function RunRow({ run }: { run: Run }) {
  return (
    <li>
      <details>
        <summary className="grid cursor-pointer grid-cols-2 items-center gap-x-3 gap-y-1 px-4 py-3 text-[13px] transition-colors duration-150 hover:bg-m-soft sm:grid-cols-[11rem_9rem_1fr_6rem_6rem_5rem]">
          <span className="text-m-muted">{when(run.created_at)}</span>
          <span className="font-medium">{run.connector_name}</span>
          <span className="font-mono text-xs">{run.action}</span>
          <span className={`text-[11px] font-medium uppercase ${RISK_CLS[run.risk ?? "read"] ?? ""}`}>{run.risk ?? "—"}</span>
          <span>
            <span className={`inline-flex items-center gap-1.5 text-xs ${STATUS_CLS[run.status] ?? STATUS_CLS.rejected}`}>
              <span aria-hidden className="size-1.5 rounded-full bg-current" />{run.status}
            </span>
          </span>
          <span className="text-m-muted">{formatDuration(run.duration_ms)}</span>
        </summary>
        <div className="grid gap-3 border-t border-m-line p-3 text-xs  md:grid-cols-2">
          <div>
            <h3 className="mb-1 font-medium">Input (secrets redacted)</h3>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-m-soft p-2 font-mono ">{formatJson(run.input)}</pre>
          </div>
          <div>
            <h3 className="mb-1 font-medium">Output (secrets redacted)</h3>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-m-soft p-2 font-mono ">{formatJson(run.output)}</pre>
          </div>
        </div>
      </details>
    </li>
  );
}

export function RunsView() {
  const [connector, setConnector] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<RunsPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    runsApi.list({ connector, status, limit: PAGE_SIZE, offset }).then(
      (d) => alive && setData(d),
      (e: Error) => alive && setError(e.message),
    );
    return () => { alive = false; };
  }, [connector, status, offset]);

  const total = data?.total ?? 0;
  const select = "h-8 rounded-full border border-m-line-strong bg-m-panel px-3 text-[13px]";

  return (
    <section aria-labelledby="runs-title" className="space-y-4">
      <PageHeader id="runs-title" title="Runs"
        description="Every tool call the assistant made for you. Inputs and outputs have secrets redacted. Shows your most recent 500 runs." />

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          Connector
          <select className={select} value={connector} onChange={(e) => { setOffset(0); setConnector(e.target.value); }}>
            <option value="">All</option>
            {data?.connectors.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          Status
          <select className={select} value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value); }}>
            <option value="">All</option>
            {(data?.statuses ?? ["pending", "approved", "rejected", "ok", "error"]).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <span className="text-sm text-m-muted">{data ? `${total} run${total === 1 ? "" : "s"}` : ""}</span>
      </div>

      {error && <p role="alert" className="text-sm text-m-bad">{error}</p>}
      {!data && !error && <p className="text-sm text-m-muted">Loading…</p>}
      {data && data.runs.length === 0 && (
        <p className="rounded-2xl border border-dashed border-m-line-strong p-6 text-center text-[13px] text-m-muted">
          No runs match. Ask the assistant to do something in Chat and it will show up here.
        </p>
      )}

      {data && data.runs.length > 0 && (
        <>
          <div aria-hidden className="hidden grid-cols-[11rem_9rem_1fr_6rem_6rem_5rem] gap-x-3 px-3 text-[11px] font-medium uppercase tracking-wide text-m-muted sm:grid">
            <span>Time</span><span>Connector</span><span>Tool</span><span>Risk</span><span>Status</span><span>Took</span>
          </div>
          <ul className="divide-y divide-m-line overflow-hidden rounded-2xl border border-m-line bg-m-panel shadow-[var(--m-shadow)]">{data.runs.map((r) => <RunRow key={r.id} run={r} />)}</ul>
          <div className="flex items-center gap-3 text-sm">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="h-8 rounded-full border border-m-line-strong bg-m-panel px-4 text-[13px] disabled:opacity-50">Previous</button>
            <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
            <button type="button" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}
              className="h-8 rounded-full border border-m-line-strong bg-m-panel px-4 text-[13px] disabled:opacity-50">Next</button>
          </div>
        </>
      )}
    </section>
  );
}
