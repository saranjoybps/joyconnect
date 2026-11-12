"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/ui/Card";
import { formatDuration, formatJson, runsApi, type Run, type RunsPage } from "@/lib/runs";

const PAGE_SIZE = 25;

const STATUS_CLS: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200",
  error: "bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-200",
  rejected: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  pending: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  approved: "bg-sky-100 text-sky-900 dark:bg-sky-900/40 dark:text-sky-200",
};
const RISK_CLS: Record<string, string> = {
  read: "text-neutral-600 dark:text-neutral-400",
  write: "text-amber-800 dark:text-amber-300",
  destructive: "text-red-700 dark:text-red-400",
};

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function RunRow({ run }: { run: Run }) {
  return (
    <li className="glass rounded-2xl">
      <details>
        <summary className="grid cursor-pointer grid-cols-2 items-center gap-x-3 gap-y-1 p-3 text-sm sm:grid-cols-[11rem_9rem_1fr_6rem_6rem_5rem]">
          <span className="text-neutral-600 dark:text-neutral-400">{when(run.created_at)}</span>
          <span className="font-medium">{run.connector_name}</span>
          <span>{run.action}</span>
          <span className={`text-xs font-medium uppercase ${RISK_CLS[run.risk ?? "read"] ?? ""}`}>{run.risk ?? "—"}</span>
          <span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_CLS[run.status] ?? STATUS_CLS.rejected}`}>
              {run.status}
            </span>
          </span>
          <span className="text-neutral-600 dark:text-neutral-400">{formatDuration(run.duration_ms)}</span>
        </summary>
        <div className="grid gap-3 border-t border-neutral-200 p-3 text-xs dark:border-neutral-800 md:grid-cols-2">
          <div>
            <h3 className="mb-1 font-medium">Input (secrets redacted)</h3>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-neutral-50 p-2 dark:bg-neutral-900">{formatJson(run.input)}</pre>
          </div>
          <div>
            <h3 className="mb-1 font-medium">Output (secrets redacted)</h3>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-neutral-50 p-2 dark:bg-neutral-900">{formatJson(run.output)}</pre>
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
  const select = "rounded-xl border border-line-strong bg-field px-2 py-1.5 text-sm";

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
        <span className="text-sm text-neutral-500">{data ? `${total} run${total === 1 ? "" : "s"}` : ""}</span>
      </div>

      {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
      {!data && !error && <p className="text-sm text-neutral-500">Loading…</p>}
      {data && data.runs.length === 0 && (
        <p className="glass rounded-2xl border-dashed p-6 text-center text-sm text-muted">
          No runs match. Ask the assistant to do something in Chat and it will show up here.
        </p>
      )}

      {data && data.runs.length > 0 && (
        <>
          <div aria-hidden className="hidden grid-cols-[11rem_9rem_1fr_6rem_6rem_5rem] gap-x-3 px-3 text-xs font-medium uppercase text-neutral-500 sm:grid">
            <span>Time</span><span>Connector</span><span>Tool</span><span>Risk</span><span>Status</span><span>Took</span>
          </div>
          <ul className="space-y-2">{data.runs.map((r) => <RunRow key={r.id} run={r} />)}</ul>
          <div className="flex items-center gap-3 text-sm">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded-xl border border-line-strong bg-field px-3 py-1 disabled:opacity-50">Previous</button>
            <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
            <button type="button" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}
              className="rounded-xl border border-line-strong bg-field px-3 py-1 disabled:opacity-50">Next</button>
          </div>
        </>
      )}
    </section>
  );
}
