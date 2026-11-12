"use client";

import { useCallback, useState, type ReactNode } from "react";
import {
  Brain, Clock, Command as CommandIcon, GitBranch, Link2, MessageSquarePlus, PlayCircle, Plug, Plus,
  Settings, Sparkles, Webhook, Workflow,
} from "lucide-react";
import { BrandMark } from "@/components/ui/BrandLogo";
import { CanvasPreview, WorkflowNode } from "@/components/pro/Canvas";
import {
  ActivityTimeline, ApprovalCard, AssistantMessage, Composer, StatusBar, Thinking, ToolCallCard, UserMessage, type Step,
} from "@/components/pro/chat";
import { CommandPalette, usePaletteShortcut, type Command } from "@/components/pro/CommandPalette";
import { ConnectorCard, RunRow, SetupModalPreview } from "@/components/pro/Connect";
import {
  Chip, Kbd, PBadge, PButton, PEmptyState, PIconButton, PInput, PLabel, PSkeleton, Surface,
} from "@/components/pro/ui";

type Theme = "light" | "dark";
type View = "dark" | "light" | "both";

function mark(id: string, name: string, size = 16): ReactNode {
  return BrandMark({ id, name, size }) ?? <span className="text-[11px] font-semibold text-[#161620]">{name.charAt(0)}</span>;
}

const COMMANDS: Command[] = [
  { id: "new", group: "Chat", label: "New chat", icon: MessageSquarePlus, shortcut: ["⌘", "N"] },
  { id: "go-chat", group: "Navigate", label: "Go to Chat", icon: Sparkles },
  { id: "go-conn", group: "Navigate", label: "Go to Connections", icon: Plug },
  { id: "go-wf", group: "Navigate", label: "Go to Workflows", icon: Workflow },
  { id: "go-runs", group: "Navigate", label: "Go to Runs", icon: PlayCircle },
  { id: "go-mem", group: "Navigate", label: "Go to Memory", icon: Brain },
  { id: "go-set", group: "Navigate", label: "Go to Settings", icon: Settings },
  { id: "m-custom", group: "Switch mode", label: "/custom", hint: "All connected apps", icon: Sparkles },
  { id: "m-wf", group: "Switch mode", label: "/workflow", hint: "Build workflows", icon: GitBranch },
  { id: "m-sheets", group: "Switch mode", label: "/google-sheets", hint: "Only Google Sheets", logo: <span className="flex size-[18px] items-center justify-center rounded bg-white">{mark("google_sheets", "Google Sheets", 12)}</span> },
  { id: "run-1", group: "Run workflow", label: "New lead to Slack", hint: "Published · v4", icon: PlayCircle },
  { id: "run-2", group: "Run workflow", label: "Weekly report", hint: "Draft · v2", icon: PlayCircle },
];

const STEPS: Step[] = [
  { id: "1", kind: "plan", label: "Planned the request", detail: "list spreadsheets, then read the first tab", state: "done" },
  { id: "2", kind: "search", label: "Searched Google Drive", detail: "mimeType = spreadsheet · 12 results", state: "done" },
  { id: "3", kind: "tool", label: "Calling google_sheets__read_range", detail: "Leads!A1:F20", state: "running" },
  { id: "4", kind: "approval", label: "Awaiting your approval", detail: "append_row · Google Sheets", state: "queued" },
];

const INPUT = `{
  "spreadsheet_id": "1AbCdEfGhIjKlMn…",
  "range": "Leads!A1:F20"
}`;
const OUTPUT = `{
  "rows": 19,
  "header": ["Name", "Email", "Status"],
  "updated_range": "Leads!A1:F20"
}`;

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-[13px] font-semibold tracking-tight text-p-text">{title}</h2>
        {note && <p className="text-xs text-p-muted">{note}</p>}
      </div>
      {children}
    </section>
  );
}

function Preview({ theme, paletteHost }: { theme: Theme; paletteHost: boolean }) {
  const [msg, setMsg] = useState("");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [last, setLast] = useState<string | null>(null);
  const toggle = useCallback(() => setPaletteOpen((o) => !o), []);
  usePaletteShortcut(paletteHost ? toggle : () => undefined);

  return (
    <div className={`${theme} p-ambient relative isolate min-w-0 space-y-10 overflow-hidden rounded-2xl border border-p-line p-5 text-p-text sm:p-7`}
      data-theme-panel={theme}>
      <header className="relative z-10 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className="flex size-7 items-center justify-center rounded-lg bg-p-accent text-p-accent-fg shadow-[inset_0_1px_0_rgba(255,255,255,0.2)]">
            <Link2 size={14} strokeWidth={2} aria-hidden />
          </span>
          <span className="text-sm font-semibold tracking-tight">Connect</span>
          <PBadge tone="accent">{theme === "dark" ? "Dark" : "Light"}</PBadge>
        </div>
        <PButton variant="secondary" icon={CommandIcon} kbd="⌘K" onClick={() => setPaletteOpen(true)}>Command palette</PButton>
      </header>

      <div className="relative z-10 space-y-10">
        <Section title="Buttons and inputs" note="28 / 32 / 36 px. One accent, flat fill, hairline borders.">
          <Surface className="space-y-4 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <PButton size="lg">Primary</PButton>
              <PButton>Primary</PButton>
              <PButton size="sm">Small</PButton>
              <PButton variant="secondary">Secondary</PButton>
              <PButton variant="ghost">Ghost</PButton>
              <PButton variant="danger">Delete</PButton>
              <PButton icon={Plus} kbd="⌘N">New chat</PButton>
              <PButton disabled>Disabled</PButton>
              <PIconButton label="Settings" icon={Settings} />
              <PIconButton label="Active" icon={Sparkles} active />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div><PLabel htmlFor={`i1-${theme}`}>Workflow name</PLabel><PInput id={`i1-${theme}`} placeholder="Weekly report" /></div>
              <div><PLabel htmlFor={`i2-${theme}`} hint="(mono for IDs)">Spreadsheet ID</PLabel><PInput id={`i2-${theme}`} className="font-mono" defaultValue="1AbCdEfGhIjKlMn" /></div>
              <div><PLabel htmlFor={`i3-${theme}`}>With error</PLabel><PInput id={`i3-${theme}`} aria-invalid="true" defaultValue="not-an-id" /></div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <PBadge tone="ok" dot>Connected</PBadge><PBadge tone="warn" dot>Partial access</PBadge>
              <PBadge tone="bad" dot>Failed</PBadge><PBadge tone="info" dot>Info</PBadge>
              <PBadge tone="accent">/workflow</PBadge><PBadge>Draft</PBadge>
              <Chip icon={Link2}>Sheets · Leads</Chip><Chip href="https://example.com">notion.so/roadmap</Chip>
              <span className="text-xs text-p-muted">Shortcuts: <Kbd>⌘K</Kbd> <Kbd>⌘N</Kbd> <Kbd>/</Kbd></span>
            </div>
          </Surface>
        </Section>

        <Section title="Chat" note="Streaming cursor, thinking shimmer, agent activity, tool chips, approval, composer and status bar.">
          <Surface className="space-y-5 p-4 sm:p-5">
            <UserMessage>List my Google Sheets and add Ada to the Leads one.</UserMessage>
            <Thinking label="Planning" />
            <ActivityTimeline steps={STEPS} />
            <AssistantMessage streaming chips={<><Chip icon={Link2} href="https://example.com">Leads (Google Sheets)</Chip><Chip icon={Clock}>2 tool calls · 1.4 s</Chip></>}>
              <p>I found <strong>3 spreadsheets</strong>. “Leads” looks right. Reading the first rows now so I can append Ada in the same format</p>
            </AssistantMessage>
            <div className="space-y-2 pl-9">
              <ToolCallCard name="read_range" app="Google Sheets" logo={mark("google_sheets", "Google Sheets")} status="ok" duration="412 ms" input={INPUT} output={OUTPUT} defaultOpen />
              <ToolCallCard name="search_files" app="Google Drive" logo={mark("google_drive", "Google Drive")} status="running" />
              <ToolCallCard name="create_issue" app="Linear" logo={mark("linear", "Linear")} status="error" duration="1.2 s"
                error="Linear rejected the token. Reconnect Linear to continue." />
              <ApprovalCard app="Google Sheets" logo={mark("google_sheets", "Google Sheets")} action="Append row" risk="write"
                description="Adds one row to the Leads sheet."
                args={{ spreadsheet_id: "1AbCdEf…", range: "Leads!A:C", values: '["Ada","ada@example.com","new"]' }} />
            </div>
            <div>
              <Composer mode="custom" modeLogo={<Sparkles size={11} aria-hidden />} value={msg} onChange={setMsg} />
              <StatusBar mode="custom" model="gpt-4o-mini" memory />
            </div>
          </Surface>
        </Section>

        <Section title="Connections" note="Flat cards; the logo sits on a small tile. The setup dialog is a floating glass layer.">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <ConnectorCard name="Google Sheets" description="Read and write spreadsheets, tabs and rows." logo={mark("google_sheets", "Google Sheets", 18)} status="Connected" tone="ok" action="Manage" accounts="saran@example.com" />
            <ConnectorCard name="Notion" description="Search pages and databases, create and update pages." logo={mark("notion", "Notion", 18)} status="Ready to connect" tone="neutral" action="Connect" />
            <ConnectorCard name="GitHub" description="Repositories, issues and pull requests." logo={mark("github", "GitHub", 18)} status="Partial access" tone="warn" action="Reconnect" accounts="2 accounts" />
          </div>
          <div className="rounded-xl border border-p-line bg-p-bg/60 p-4 sm:p-6">
            <SetupModalPreview name="Google Sheets" logo={mark("google_sheets", "Google Sheets", 18)}
              redirectUri="http://localhost:8000/api/oauth/callback/google" />
          </div>
        </Section>

        <Section title="Workflow canvas" note="Dotted grid, slim nodes, thin lines. The line into the running node flows; the selected node glows softly. No blur on the canvas.">
          <CanvasPreview running="n3" nodes={[
            { id: "n1", x: 24, y: 24, node: <WorkflowNode name="Schedule" kind="Trigger" icon={Clock} status="ok" /> },
            { id: "n2", x: 270, y: 96, node: <WorkflowNode name="Read leads" kind="Google Sheets · read_range" logo={mark("google_sheets", "Google Sheets", 15)} status="ok" selected /> },
            { id: "n3", x: 516, y: 24, node: <WorkflowNode name="Post to Slack" kind="Slack · post_message" logo={<span className="text-[11px] font-semibold text-[#161620]">S</span>} status="running" risk="write" /> },
            { id: "n4", x: 516, y: 150, node: <WorkflowNode name="If new" kind="Condition" icon={GitBranch} /> },
          ]} />
          <div className="flex items-center gap-2 text-xs text-p-muted"><Webhook size={13} aria-hidden /> Core nodes use our own line icons; app nodes use the app mark.</div>
        </Section>

        <Section title="Runs" note="Dense table, mono for tool names and times; click a row for input and output.">
          <Surface className="overflow-hidden">
            <div aria-hidden className="hidden grid-cols-[9rem_10rem_1fr_5rem_5rem_4rem] gap-x-3 border-b border-p-line px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-p-muted sm:grid">
              <span>Time</span><span>App</span><span>Tool</span><span>Risk</span><span>Status</span><span>Took</span>
            </div>
            <RunRow time="12 Nov 16:41:07" app="Google Sheets" logo={mark("google_sheets", "Google Sheets", 13)} tool="google_sheets__append_row" risk="write" status="ok" took="412 ms" input={INPUT} output={OUTPUT} />
            <RunRow time="12 Nov 16:40:52" app="Linear" logo={mark("linear", "Linear", 13)} tool="linear__create_issue" risk="write" status="error" took="1.2 s" input={'{ "title": "Bug" }'} output={'{ "error": "401 Unauthorized" }'} />
            <RunRow time="12 Nov 16:39:10" app="Notion" logo={mark("notion", "Notion", 13)} tool="notion__search" risk="read" status="ok" took="230 ms" input={'{ "query": "roadmap" }'} output={'{ "results": 4 }'} />
          </Surface>
        </Section>

        <Section title="Empty state and loading" note="One clear action. Skeletons are plain, no shimmer storm.">
          <div className="grid gap-3 md:grid-cols-2">
            <PEmptyState icon={Workflow} title="No workflows yet" action={<PButton icon={Plus}>New workflow</PButton>}>
              Build one on the canvas, or describe it in chat and the assistant drafts it for you.
            </PEmptyState>
            <Surface className="space-y-2.5 p-4"><PSkeleton className="h-4 w-1/3" /><PSkeleton className="h-3 w-full" /><PSkeleton className="h-3 w-5/6" /><PSkeleton className="h-8 w-24" /></Surface>
          </div>
        </Section>

        {last && <p role="status" className="font-mono text-xs text-p-muted">Palette ran: {last}</p>}
      </div>

      {paletteHost && (
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={COMMANDS} onRun={(c) => setLast(c.label)} />
      )}
    </div>
  );
}

export function DesignPreview() {
  const [view, setView] = useState<View>("dark");
  const views: { id: View; label: string }[] = [{ id: "dark", label: "Dark" }, { id: "light", label: "Light" }, { id: "both", label: "Side by side" }];
  return (
    <div className="fixed inset-0 z-[60] overflow-auto bg-[#0a0a0f] text-[#ececf1]">
      <div className="mx-auto max-w-[1500px] space-y-5 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold">Design preview</h1>
            <p className="text-xs text-[#9a9aa8]">Development only. Premium, restrained direction. Press ⌘K / Ctrl+K inside a panel.</p>
          </div>
          <div role="tablist" aria-label="Theme view" className="inline-flex rounded-lg border border-white/10 bg-white/5 p-0.5">
            {views.map((v) => (
              <button key={v.id} type="button" role="tab" aria-selected={view === v.id} onClick={() => setView(v.id)}
                className={`h-7 rounded-md px-3 text-xs font-medium transition-colors ${view === v.id ? "bg-[#5b57e8] text-white" : "text-[#9a9aa8] hover:text-white"}`}>
                {v.label}
              </button>
            ))}
          </div>
        </div>
        <div className={view === "both" ? "grid gap-5 xl:grid-cols-2" : "mx-auto max-w-4xl"}>
          {view !== "light" && <Preview theme="dark" paletteHost />}
          {view !== "dark" && <Preview theme="light" paletteHost={view === "light"} />}
        </div>
      </div>
    </div>
  );
}
