"use client";

import { useEffect, useState, type ReactNode } from "react";
import { BrandMark } from "@/components/ui/BrandLogo";
import { ApprovalCard, AssistantText, ChatHome, Composer, ThinkingDots, ToolRow, UserBlock } from "@/components/min/Chat";
import { ConnectorGrid, type ConnectorItem } from "@/components/min/Connect";
import { HistoryPanel, type ChatSummary } from "@/components/min/History";
import { AppWindow, Sidebar, type NavId, type Theme, type ThemePref } from "@/components/min/Shell";

function mark(id: string, name: string, size = 15): ReactNode {
  return BrandMark({ id, name, size }) ?? <span className="text-[11px] font-semibold text-[#161620]">{name.charAt(0)}</span>;
}

const CHATS: ChatSummary[] = [
  { id: "1", title: "Q4 leads sheet", preview: "Found 3 spreadsheets, reading the Leads tab…", time: "2h ago" },
  { id: "2", title: "Weekly report workflow", preview: "Drafted a workflow with a schedule trigger and Slack.", time: "3h ago" },
  { id: "3", title: "Calendar this week", preview: "You have 4 meetings, the first at 9:30.", time: "Yesterday" },
  { id: "4", title: "GitHub issues triage", preview: "Listed 12 open issues labelled bug.", time: "Yesterday" },
  { id: "5", title: "Stripe payments digest", preview: "Summed last week's payments by currency.", time: "Mon" },
  { id: "6", title: "Notion roadmap search", preview: "Three pages mention the Q1 roadmap.", time: "Mon" },
];

const CONNECTORS: ConnectorItem[] = [
  { id: "notion", name: "Notion", description: "Search pages and databases, create and update pages.", logo: mark("notion", "Notion", 20), status: "ready" },
  { id: "sheets", name: "Google Sheets", description: "Read and write spreadsheets, tabs and rows.", logo: mark("google_sheets", "Google Sheets", 20), status: "connected", account: "saran@example.com" },
  { id: "github", name: "GitHub", description: "Repositories, issues and pull requests.", logo: mark("github", "GitHub", 20), status: "partial", account: "2 accounts" },
  { id: "slack", name: "Slack", description: "Send messages and list channels.", logo: mark("slack", "Slack", 20), status: "not_set_up" },
  { id: "linear", name: "Linear", description: "Search, create and update issues.", logo: mark("linear", "Linear", 20), status: "connected", account: "team@example.com" },
  { id: "stripe", name: "Stripe", description: "Read payments, customers and invoices.", logo: mark("stripe", "Stripe", 20), status: "ready" },
  { id: "drive", name: "Google Drive", description: "Find folders and files you give access to.", logo: mark("google_drive", "Google Drive", 20), status: "connected", account: "saran@example.com" },
  { id: "airtable", name: "Airtable", description: "Bases, tables and records.", logo: mark("airtable", "Airtable", 20), status: "ready" },
  { id: "trello", name: "Trello", description: "Boards, lists and cards.", logo: mark("trello", "Trello", 20), status: "not_set_up" },
];

const INPUT = `{\n  "spreadsheet_id": "1AbCdEfGhIjKlMn…",\n  "range": "Leads!A1:F20"\n}`;
const OUTPUT = `{\n  "rows": 19,\n  "header": ["Name", "Email", "Status"]\n}`;

type Screen = "home" | "chat" | "connections";

function useResolved(pref: ThemePref, fallback: Theme): Theme {
  const [sys, setSys] = useState<Theme>(fallback);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => setSys(mq.matches ? "dark" : "light");
    on();
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return pref === "system" ? sys : pref;
}

function Window({ screen, initialTheme }: { screen: Screen; initialTheme: Theme }) {
  const [pref, setPref] = useState<ThemePref>(initialTheme);
  const theme = useResolved(pref, initialTheme);
  const [nav, setNav] = useState<NavId>(screen === "connections" ? "connections" : "home");
  const [mode, setMode] = useState("custom");
  const [value, setValue] = useState("");
  const [memory, setMemory] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(screen === "home");
  const [chatId, setChatId] = useState<string | null>(screen === "chat" ? "1" : null);
  const [view, setView] = useState<"home" | "chat">(screen === "chat" ? "chat" : "home");


  const sidebar = (
    <Sidebar active={nav} onNavigate={setNav} mode={mode} onMode={setMode}
      user={{ name: "Allison Lipshutz", email: "allison@example.com" }} pref={pref} onPref={setPref} />
  );

  const showConnections = nav === "connections";
  const title = showConnections ? "Connections" : view === "chat" ? "Q4 leads sheet" : "Home";

  return (
    <AppWindow theme={theme} sidebar={sidebar} title={title} historyOpen={historyOpen} onToggleHistory={() => setHistoryOpen((o) => !o)}
      history={showConnections ? undefined : (
        <HistoryPanel chats={CHATS} activeId={chatId} onNew={() => { setView("home"); setChatId(null); }}
          onOpen={(id) => { setChatId(id); setView("chat"); }} />
      )}>
      {showConnections ? <ConnectorGrid items={CONNECTORS} /> : (
        <div className="flex h-full flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            {view === "home" ? (
              <ChatHome name="Allison" onPick={setValue} />
            ) : (
              <div className="mx-auto max-w-2xl space-y-6 px-6 pb-6 pt-2">
                <UserBlock>List my Google Sheets and add Ada to the Leads one.</UserBlock>
                <AssistantText>
                  <p>I found <strong>3 spreadsheets</strong>. “Leads” looks right, so I read its first rows to match the format.</p>
                </AssistantText>
                <div className="space-y-2">
                  <ToolRow name="search_files" app="Google Drive" logo={mark("google_drive", "Google Drive")} status="ok" duration="230 ms" />
                  <ToolRow name="read_range" app="Google Sheets" logo={mark("google_sheets", "Google Sheets")} status="ok" duration="412 ms" input={INPUT} output={OUTPUT} defaultOpen />
                  <ToolRow name="create_issue" app="Linear" logo={mark("linear", "Linear")} status="error" duration="1.2 s" error="Linear rejected the token. Reconnect Linear to continue." />
                </div>
                <ApprovalCard app="Google Sheets" logo={mark("google_sheets", "Google Sheets")} action="Append row" risk="write"
                  description="Adds one row to the Leads sheet."
                  args={{ spreadsheet_id: "1AbCdEf…", range: "Leads!A:C", values: '["Ada","ada@example.com","new"]' }} />
                <AssistantText streaming><p>Once you approve, I will add Ada and confirm</p></AssistantText>
                <ThinkingDots />
              </div>
            )}
          </div>
          <Composer value={value} onChange={setValue} mode={mode} onMode={setMode} memory={memory} onMemory={setMemory} model="gpt-4o-mini" />
        </div>
      )}
    </AppWindow>
  );
}

export function MinPreview() {
  const [view, setView] = useState<"dark" | "light" | "both">("light");
  const themes: Theme[] = view === "both" ? ["light", "dark"] : [view];
  const screens: { id: Screen; label: string }[] = [
    { id: "home", label: "1. Chat home, with the history panel" },
    { id: "chat", label: "2. Active conversation: tool calls and an approval card" },
    { id: "connections", label: "3. Connections grid (Connected first)" },
  ];
  return (
    <div className="fixed inset-0 z-[60] overflow-auto bg-[#101014] text-[#ececf0]">
      <div className="mx-auto max-w-[1240px] space-y-6 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold">Design preview: minimal</h1>
            <p className="text-xs text-[#9b9ba6]">Development only. Use the Theme control in each window&apos;s user card, or the switch here.</p>
          </div>
          <div role="tablist" aria-label="Theme view" className="inline-flex rounded-full border border-white/10 bg-white/5 p-0.5">
            {(["light", "dark", "both"] as const).map((v) => (
              <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
                className={`h-7 rounded-full px-3 text-xs font-medium capitalize transition-colors ${view === v ? "bg-white text-[#101014]" : "text-[#9b9ba6] hover:text-white"}`}>
                {v === "both" ? "Both" : v}
              </button>
            ))}
          </div>
        </div>
        {screens.map((s) => (
          <section key={s.id} aria-label={s.label} className="space-y-3">
            <h2 className="text-[13px] font-medium text-[#9b9ba6]">{s.label}</h2>
            <div className="space-y-5">
              {themes.map((t) => <Window key={`${s.id}-${t}`} screen={s.id} initialTheme={t} />)}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
