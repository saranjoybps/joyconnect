"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import type { Workflow, WorkflowNode } from "@/lib/workflow-schema";
import {
  workflowsApi, type ConnectionLite, type NodeRecord, type NodeType, type Operation, type TestResult, type Trigger,
} from "@/lib/workflows";
import { ParamField } from "./ParamField";
import { ScheduleEditor, type ScheduleParams } from "./ScheduleEditor";

export function Items({ title, items }: { title: string; items: { json: unknown }[] | undefined }) {
  if (!items) return null;
  return (
    <div>
      <p className="text-xs font-medium">{title} · {items.length} item{items.length === 1 ? "" : "s"}</p>
      <pre className="max-h-56 overflow-auto rounded-md bg-neutral-100 p-2 text-xs dark:bg-neutral-800">
        {JSON.stringify(items.map((i) => i.json), null, 2)}
      </pre>
    </div>
  );
}

type Props = {
  workflowId: string;
  workflow: Workflow;
  node: WorkflowNode | null;
  nodeType: NodeType | undefined;
  published: boolean;
  lastRun: NodeRecord | undefined;
  triggers: Trigger[];
  onApply: (ops: Operation[]) => Promise<boolean>;
  onDeleteNode: (id: string) => void;
  onTested: () => void;
};

export function ConfigPanel(p: Props) {
  const { node } = p;
  if (!node) return <WorkflowSettings workflow={p.workflow} onApply={p.onApply} />;
  return <NodeConfig key={node.id} {...p} node={node} />;
}

function WorkflowSettings({ workflow, onApply }: { workflow: Workflow; onApply: Props["onApply"] }) {
  const s = workflow.settings ?? {};
  return (
    <aside aria-label="Workflow settings" className="w-80 shrink-0 space-y-3 overflow-y-auto border-l border-neutral-200 p-3 dark:border-neutral-800">
      <h2 className="text-sm font-semibold">Workflow settings</h2>
      <p className="text-xs text-neutral-600 dark:text-neutral-400">Select a node to configure it.</p>
      <label className="block space-y-1 text-xs font-medium">
        Approvals for unattended runs
        <select
          className="w-full rounded-md border border-neutral-300 bg-transparent px-2 py-1.5 text-sm font-normal dark:border-neutral-700"
          value={s.auto_approve ?? "off"}
          onChange={(e) => void onApply([{ op: "set_settings", settings: { auto_approve: e.target.value } }])}
        >
          <option value="off">Ask before every write and delete</option>
          <option value="writes">Auto-approve writes, ask before deletes</option>
          <option value="all">Auto-approve everything (including deletes)</option>
        </select>
      </label>
      <p className="text-xs text-neutral-600 dark:text-neutral-400">
        Schedule and webhook runs pause at an approval when a node changes data, unless you allow it here.
      </p>
    </aside>
  );
}

function NodeConfig({ workflowId, node, nodeType, published, lastRun, triggers, onApply, onDeleteNode, onTested }: Props & { node: WorkflowNode }) {
  const [connections, setConnections] = useState<ConnectionLite[]>([]);
  const [name, setName] = useState(node.name);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [needsConfirm, setNeedsConfirm] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  useEffect(() => setName(node.name), [node.name]);
  useEffect(() => {
    if (nodeType?.connector) workflowsApi.connections().then(setConnections).catch(() => setConnections([]));
  }, [nodeType?.connector]);

  const props = nodeType?.parameters.properties ?? {};
  const required = new Set(nodeType?.parameters.required ?? []);
  const update = (key: string, value: unknown) =>
    void onApply([{ op: "update_node", id: node.id, parameters: { [key]: value } }]);

  async function runTest(confirm: boolean) {
    setTesting(true);
    setTestError(null);
    setNeedsConfirm(null);
    try {
      setTest(await workflowsApi.testNode(workflowId, node.id, confirm));
      onTested();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail.requires_confirmation) setNeedsConfirm(e.message);
      else setTestError(e instanceof ApiError ? e.message : "The test could not run.");
    } finally {
      setTesting(false);
    }
  }

  const trigger = triggers.find((t) => t.node_id === node.id);
  const mine = connections.filter((c) => c.provider === nodeType?.connector && c.status === "active");
  const shownOutput = test?.output ?? lastRun?.output ?? null;
  const shownError = test ? test.error : lastRun?.error;

  return (
    <aside aria-label={`Configure ${node.name}`} className="w-96 shrink-0 space-y-4 overflow-y-auto border-l border-neutral-200 p-3 dark:border-neutral-800">
      <div>
        <p className="text-xs text-neutral-600 dark:text-neutral-400">{nodeType?.name ?? node.type}</p>
        <label className="sr-only" htmlFor="node-name">Node name</label>
        <input
          id="node-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => name.trim() && name !== node.name && void onApply([{ op: "rename", id: node.id, name: name.trim() }])}
          className="w-full rounded-md border border-neutral-300 bg-transparent px-2 py-1 font-semibold dark:border-neutral-700"
        />
        {nodeType && <p className="mt-1 text-xs text-neutral-600 dark:text-neutral-400">{nodeType.description}</p>}
      </div>

      {nodeType?.connector && (
        <div className="space-y-1">
          <label htmlFor="conn" className="text-xs font-medium">Account <span aria-hidden className="text-red-600">*</span></label>
          {mine.length ? (
            <select
              id="conn"
              className="w-full rounded-md border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
              value={node.connection_id ?? ""}
              onChange={(e) => void onApply([{ op: "update_node", id: node.id, connection_id: e.target.value || null }])}
            >
              <option value="">Choose an account…</option>
              {mine.map((c) => <option key={c.id} value={c.id}>{c.account_label ?? c.provider}</option>)}
            </select>
          ) : (
            <p className="text-sm">
              No connected account for this app. <Link href="/connections" className="underline">Connect it first</Link>.
            </p>
          )}
        </div>
      )}

      {node.type === "schedule_trigger" ? (
        <ScheduleEditor value={node.parameters as ScheduleParams} onChange={(v) => void onApply([{ op: "update_node", id: node.id, parameters: v as Record<string, unknown> }])} />
      ) : (
        Object.entries(props).map(([key, schema]) => (
          <ParamField key={key} name={key} schema={schema} value={node.parameters[key]} required={required.has(key)} onCommit={update} />
        ))
      )}

      {trigger?.type === "schedule" && (
        <p className="text-xs">
          {trigger.active ? <>Next run: <strong>{trigger.next_run_at ? new Date(trigger.next_run_at).toLocaleString() : "—"}</strong></> : "Inactive: publish to activate."}
        </p>
      )}
      {node.type === "webhook_trigger" && (
        <div className="space-y-2 rounded-md border border-neutral-200 p-2 text-xs dark:border-neutral-800">
          {published && trigger?.url ? (
            <>
              <p className="font-medium">Production URL</p>
              <code className="block break-all rounded bg-neutral-100 p-1 dark:bg-neutral-800">{trigger.url}</code>
              {trigger.has_secret && (
                <>
                  <p>Send the secret in the <code>{trigger.secret_header}</code> header. It is shown only once.</p>
                  <button
                    type="button"
                    className="underline"
                    onClick={async () => setSecret((await workflowsApi.rotateSecret(workflowId, node.id)).secret)}
                  >
                    Generate a new secret
                  </button>
                  {secret && <code role="status" className="block break-all rounded bg-amber-100 p-1 text-amber-950">{secret}</code>}
                </>
              )}
            </>
          ) : (
            <p>Publish the workflow to get this webhook&apos;s URL. Only the published version answers.</p>
          )}
        </div>
      )}

      <div className="space-y-2 border-t border-neutral-200 pt-3 dark:border-neutral-800">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={testing || nodeType?.category === "trigger"}
            onClick={() => void runTest(false)}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
          >
            {testing ? "Testing…" : "Test node"}
          </button>
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={Boolean(node.disabled)} onChange={(e) => void onApply([{ op: "update_node", id: node.id, disabled: e.target.checked }])} />
            Disabled
          </label>
          <button type="button" onClick={() => onDeleteNode(node.id)} className="ml-auto text-xs text-red-700 underline dark:text-red-400">
            Delete node
          </button>
        </div>
        {nodeType?.category === "trigger" && <p className="text-xs text-neutral-600">Triggers start a run; use Run workflow.</p>}
        {needsConfirm && (
          <div role="alert" className="space-y-2 rounded-md bg-amber-50 p-2 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100">
            <p>{needsConfirm}</p>
            <button type="button" onClick={() => void runTest(true)} className="rounded-md bg-amber-700 px-2 py-1 text-xs font-medium text-white">
              Run it for real
            </button>
          </div>
        )}
        {testError && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{testError}</p>}
        {shownError && <p role="alert" className="text-sm text-red-700 dark:text-red-400">Error: {shownError.message ?? "The node failed."}</p>}
        {shownOutput && Object.entries(shownOutput).map(([k, items]) => (
          <Items key={k} title={`${test ? "Test output" : "Last run"}${k === "main" ? "" : ` · ${k}`}`} items={items} />
        ))}
        {!shownOutput && !shownError && !testError && !needsConfirm && (
          <p className="text-xs text-neutral-600 dark:text-neutral-400">No output yet. Press Test node to run just this node with real data.</p>
        )}
      </div>
    </aside>
  );
}
