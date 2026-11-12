"use client";

import {
  applyNodeChanges, Background, Controls, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow,
  type Connection, type Edge, type Node, type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { nextPosition, pickRunTrigger, sampleTriggerData, toFlowEdges, toFlowNodes, type CanvasNodeData } from "@/lib/canvas";
import { useWorkflow } from "@/lib/useWorkflow";
import {
  addNodeOp, connectOp, disconnectOp, workflowsApi, type Execution, type NodeRecord, type NodeType, type Trigger,
} from "@/lib/workflows";
import { ConfigPanel } from "./ConfigPanel";
import { NodeCard } from "./NodeCard";
import { DRAG_MIME, NodePalette } from "./NodePalette";

const nodeTypes = { workflowNode: NodeCard };
const TERMINAL = new Set(["success", "error", "canceled"]);

export function WorkflowEditor({ id }: { id: string }) {
  return (
    <ReactFlowProvider>
      <Editor id={id} />
    </ReactFlowProvider>
  );
}

function latestByNode(records: NodeRecord[]): Record<string, NodeRecord> {
  const out: Record<string, NodeRecord> = {};
  for (const r of records) out[r.node_id] = r;
  return out;
}

function Editor({ id }: { id: string }) {
  const { workflow, publishedVersion, loadError, notice, setNotice, saving, apply, adopt } = useWorkflow(id);
  const [types, setTypes] = useState<NodeType[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [running, setRunning] = useState(false);
  const [secrets, setSecrets] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const flow = useReactFlow();
  const [nodes, setNodes] = useState<Node[]>([]);
  const typeMap = useMemo(() => new Map(types.map((t) => [t.type, t])), [types]);
  const results = useMemo(() => latestByNode(execution?.nodes ?? []), [execution]);

  useEffect(() => {
    workflowsApi.nodeTypes().then(setTypes).catch(() => setNotice({ kind: "error", message: "Could not load the node list." }));
  }, [setNotice]);

  const refreshTriggers = useCallback(async () => {
    try {
      setTriggers(await workflowsApi.triggers(id));
    } catch {
      setTriggers([]);
    }
  }, [id]);
  useEffect(() => {
    if (publishedVersion !== null) void refreshTriggers();
    else setTriggers([]);
  }, [publishedVersion, workflow?.version, refreshTriggers]);

  useEffect(() => setTitle(workflow?.name ?? ""), [workflow?.name]);

  // Canvas nodes follow the document (and the last run's statuses); selection is kept.
  useEffect(() => {
    if (!workflow) return;
    const status = Object.fromEntries(Object.entries(results).map(([k, r]) => [k, r.status]));
    setNodes(toFlowNodes(workflow, typeMap, status).map((n) => ({ ...n, selected: n.id === selected })));
  }, [workflow, typeMap, results, selected]);
  const edges: Edge[] = useMemo(() => (workflow ? toFlowEdges(workflow) : []), [workflow]);

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((ns) => applyNodeChanges(changes, ns)), []);

  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target) return;
      void apply([connectOp(c.source, c.target, c.sourceHandle ?? "main", c.targetHandle ?? "main")]);
    },
    [apply],
  );

  const onDelete = useCallback(
    ({ nodes: gone, edges: goneEdges }: { nodes: Node[]; edges: Edge[] }) => {
      if (!workflow) return;
      if (gone.length && publishedVersion !== null && !window.confirm(`Delete ${gone.length} node(s) from a published workflow?`)) {
        void workflowsApi.get(id).then((r) => adopt(r.workflow, r.published_version));
        return;
      }
      const goneIds = new Set(gone.map((n) => n.id));
      const ops = [
        ...goneEdges.filter((e) => !goneIds.has(e.source) && !goneIds.has(e.target))
          .map((e) => disconnectOp(e.source, e.target, e.sourceHandle ?? "main", e.targetHandle ?? "main")),
        ...gone.map((n) => ({ op: "remove_node", id: n.id })),
      ];
      if (ops.length) void apply(ops);
    },
    [apply, workflow, publishedVersion, id, adopt],
  );

  function addFromPalette(nt: NodeType, position?: { x: number; y: number }) {
    if (!workflow) return;
    const op = addNodeOp(nt, position ?? nextPosition(workflow), workflow.nodes.map((n) => n.name));
    void apply([op]).then((ok) => ok && setSelected((op.node as { id: string }).id));
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const type = e.dataTransfer.getData(DRAG_MIME);
    const nt = typeMap.get(type);
    if (nt) addFromPalette(nt, flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  }

  async function publish() {
    setBusy(true);
    try {
      const r = await workflowsApi.publish(id);
      adopt(r.workflow, r.workflow.version);
      setNotice(null);
      if (r.webhook_secrets && Object.keys(r.webhook_secrets).length) setSecrets(r.webhook_secrets);
    } catch (e) {
      const errors = e instanceof ApiError && Array.isArray(e.detail.errors) ? (e.detail.errors as unknown as string[]) : undefined;
      setNotice({ kind: "error", message: e instanceof ApiError ? e.message : "Could not publish.", details: errors });
    } finally {
      setBusy(false);
    }
  }

  async function unpublish() {
    setBusy(true);
    try {
      const r = await workflowsApi.unpublish(id);
      adopt(r.workflow, null);
    } catch (e) {
      setNotice({ kind: "error", message: e instanceof ApiError ? e.message : "Could not unpublish." });
    } finally {
      setBusy(false);
    }
  }

  const stillRunning = useRef(false);
  async function runWorkflow() {
    if (!workflow) return;
    const trigger = pickRunTrigger(workflow, typeMap);
    if (!trigger) {
      setNotice({ kind: "error", message: "Add a trigger node (Manual, Schedule or Webhook) before running." });
      return;
    }
    setRunning(true);
    stillRunning.current = true;
    setExecution(null);
    try {
      const started = await workflowsApi.run(id, { trigger_node_id: trigger.id, trigger_data: sampleTriggerData(trigger.type) });
      const t0 = Date.now();
      for (;;) {
        const ex = await workflowsApi.execution(started.id);
        setExecution(ex);
        if (TERMINAL.has(ex.execution.status) || ex.execution.status === "waiting" || !stillRunning.current) break;
        if (Date.now() - t0 > 120_000) break;
        await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (e) {
      const errors = e instanceof ApiError && Array.isArray(e.detail.errors) ? (e.detail.errors as unknown as string[]) : undefined;
      setNotice({ kind: "error", message: e instanceof ApiError ? e.message : "Could not start the run.", details: errors });
    } finally {
      setRunning(false);
    }
  }
  useEffect(() => () => void (stillRunning.current = false), []);

  async function decide(approvalId: string, approve: boolean) {
    await workflowsApi.decide(approvalId, approve);
    if (execution) setExecution(await workflowsApi.execution(execution.execution.id));
  }

  if (loadError) {
    return (
      <div className="space-y-3">
        <p role="alert" className="text-sm text-red-800 dark:text-red-200">{loadError}</p>
        <Link href="/workflows" className="underline">Back to workflows</Link>
      </div>
    );
  }
  if (!workflow) return <p className="text-sm text-neutral-600">Loading…</p>;

  const published = publishedVersion !== null;
  const dirty = published && publishedVersion !== workflow.version;
  const node = workflow.nodes.find((n) => n.id === selected) ?? null;

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] w-full flex-col md:h-dvh">
      <div className="flex flex-wrap items-center gap-3 border-b border-neutral-200 px-3 py-2 dark:border-neutral-800">
        <Link href="/workflows" className="text-sm underline">← Workflows</Link>
        <label className="sr-only" htmlFor="wf-title">Workflow name</label>
        <input
          id="wf-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title.trim() && title !== workflow.name && void apply([{ op: "rename", name: title.trim() }])}
          className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 font-semibold hover:border-neutral-300 dark:hover:border-neutral-700"
        />
        <span className="text-xs text-neutral-600 dark:text-neutral-400" aria-live="polite">
          {saving ? "Saving…" : `Saved · v${workflow.version}`}
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={published}
          aria-label="Published"
          disabled={busy}
          onClick={() => (published ? void unpublish() : void publish())}
          className="flex items-center gap-2 rounded-full border border-neutral-300 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-700"
        >
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${published ? "bg-emerald-500" : "bg-neutral-400"}`} />
          {published ? "Published" : "Draft"}
        </button>
        {dirty && (
          <button type="button" disabled={busy} onClick={() => void publish()} className="rounded-md border border-amber-600 px-3 py-1 text-sm text-amber-900 dark:text-amber-200">
            Publish changes
          </button>
        )}
        <button
          type="button"
          disabled={running}
          onClick={() => void runWorkflow()}
          className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {running ? "Running…" : "Run workflow"}
        </button>
      </div>

      {notice && (
        <div role={notice.kind === "error" ? "alert" : "status"} className={`px-3 py-2 text-sm ${notice.kind === "error" ? "bg-red-50 text-red-900 dark:bg-red-950 dark:text-red-100" : "bg-sky-50 text-sky-900 dark:bg-sky-950 dark:text-sky-100"}`}>
          {notice.message}
          {notice.details && <ul className="ml-5 list-disc">{notice.details.slice(0, 8).map((d) => <li key={d}>{d}</li>)}</ul>}
          <button type="button" className="ml-3 underline" onClick={() => setNotice(null)}>Dismiss</button>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <NodePalette types={types} onAdd={(nt) => addFromPalette(nt)} />
        <div className="relative min-w-0 flex-1" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onConnect={onConnect}
            onNodeDragStop={(_, n) => void apply([{ op: "move", id: n.id, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } }])}
            onNodeClick={(_, n) => setSelected(n.id)}
            onPaneClick={() => setSelected(null)}
            onDelete={onDelete}
            deleteKeyCode={["Backspace", "Delete"]}
            fitView
          >
            <Background />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
          {workflow.nodes.length === 0 && (
            <p className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-neutral-600">
              Drag a node from the palette to start. Begin with a trigger.
            </p>
          )}
        </div>
        <ConfigPanel
          workflowId={id}
          workflow={workflow}
          node={node}
          nodeType={node ? typeMap.get(node.type) : undefined}
          siblings={node && typeMap.get(node.type)?.connector ? types.filter((t) => t.connector === typeMap.get(node.type)?.connector) : []}
          published={published}
          lastRun={node ? results[node.id] : undefined}
          triggers={triggers}
          onApply={apply}
          onDeleteNode={(nid) => onDelete({ nodes: [{ id: nid } as Node], edges: [] })}
          onTested={() => undefined}
        />
      </div>

      {execution && (
        <section aria-label="Run result" className="max-h-52 overflow-y-auto border-t border-neutral-200 p-3 text-sm dark:border-neutral-800">
          <p className="font-medium">
            Run {execution.execution.status}
            {execution.execution.error?.message ? `: ${execution.execution.error.message}` : ""}
          </p>
          {execution.execution.status === "queued" && (
            <p className="text-xs text-neutral-600">Waiting for the worker. Start it with <code>python -m app.worker</code>.</p>
          )}
          <ul className="mt-1 space-y-0.5 text-xs">
            {execution.nodes.map((r, i) => (
              <li key={i}>
                <button type="button" className="underline" onClick={() => setSelected(r.node_id)}>{r.node_name}</button>{" "}
                — {r.status}{r.duration_ms != null ? ` · ${r.duration_ms} ms` : ""}{r.error?.message ? ` · ${r.error.message}` : ""}
              </li>
            ))}
          </ul>
          {execution.pending_approvals?.map((a) => (
            <div key={a.approval_id} className="mt-2 flex items-center gap-2 rounded-md bg-amber-50 p-2 text-amber-950 dark:bg-amber-950 dark:text-amber-100">
              <span>“{String(a.node_name)}” wants to change data in {String(a.connector_name)}.</span>
              <button type="button" onClick={() => void decide(a.approval_id, true)} className="rounded bg-emerald-700 px-2 py-1 text-xs text-white">Approve</button>
              <button type="button" onClick={() => void decide(a.approval_id, false)} className="rounded bg-neutral-700 px-2 py-1 text-xs text-white">Reject</button>
            </div>
          ))}
        </section>
      )}

      {secrets && (
        <div role="alertdialog" aria-modal="true" aria-labelledby="sec-title" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4">
          <div className="w-full max-w-md space-y-3 rounded-lg bg-white p-5 shadow-xl dark:bg-neutral-900">
            <h2 id="sec-title" className="font-semibold">Copy your webhook secret now</h2>
            <p className="text-sm">It is shown only once. Send it in the header named on the Webhook node.</p>
            {Object.entries(secrets).map(([nid, s]) => (
              <code key={nid} className="block break-all rounded bg-neutral-100 p-2 text-xs dark:bg-neutral-800">{s}</code>
            ))}
            <button type="button" onClick={() => setSecrets(null)} className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm text-white dark:bg-neutral-100 dark:text-neutral-900">
              I copied it
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export type { CanvasNodeData };
