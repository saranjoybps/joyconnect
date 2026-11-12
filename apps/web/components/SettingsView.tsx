"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/Card";
import { useTheme, type ThemePref } from "@/components/ui/theme";
import { memoryApi } from "@/lib/memory";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

const THEMES: { value: ThemePref; label: string; hint: string }[] = [
  { value: "system", label: "System", hint: "Match your device" },
  { value: "light", label: "Light", hint: "Warm off-white" },
  { value: "dark", label: "Dark", hint: "Near-black, easy on the eyes" },
];

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card className="p-6">
      <h2 className="text-base font-semibold">{title}</h2>
      {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      <div className="mt-5">{children}</div>
    </Card>
  );
}

export function SettingsView() {
  const router = useRouter();
  const { pref, setPref } = useTheme();
  const [email, setEmail] = useState<string | null>(null);
  const [memoryOn, setMemoryOn] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    try {
      getSupabaseBrowserClient().auth.getSession().then(
        ({ data }) => alive && setEmail(data.session?.user?.email ?? null), () => undefined);
    } catch { /* no session available */ }
    memoryApi.list().then((r) => alive && setMemoryOn(r.enabled), () => undefined);
    return () => { alive = false; };
  }, []);

  async function signOut() {
    await getSupabaseBrowserClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  return (
    <section aria-labelledby="settings-title" className="space-y-6">
      <PageHeader id="settings-title" title="Settings" description="Appearance, memory and your account." />

      <Section title="Appearance" description="Light, dark or follow your device. Your choice is saved for your account in this browser.">
        <div role="radiogroup" aria-label="Theme" className="grid gap-3 sm:grid-cols-3">
          {THEMES.map((t) => (
            <label key={t.value}
              className={`flex cursor-pointer flex-col gap-0.5 rounded-xl border p-4 text-sm transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 ${pref === t.value ? "border-m-text bg-m-soft" : "border-line bg-field hover:border-line-strong"}`}>
              <input type="radio" name="theme" value={t.value} checked={pref === t.value} onChange={() => setPref(t.value)} className="sr-only" />
              <span className="font-medium">{t.label}</span>
              <span className="text-muted">{t.hint}</span>
            </label>
          ))}
        </div>
      </Section>

      <Section title="Memory" description="What the assistant remembers between chats.">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm">Memory is <strong>{memoryOn === null ? "…" : memoryOn ? "on" : "off"}</strong>.</p>
          <Link href="/memory" className="inline-flex h-9 items-center rounded-full border border-m-line-strong px-4 text-[13px] font-medium hover:bg-m-soft">
            Manage memory
          </Link>
        </div>
      </Section>

      <Section title="Connections" description="Apps the assistant can use, and your developer credentials for each.">
        <Link href="/connections" className="inline-flex h-9 items-center rounded-full border border-m-line-strong px-4 text-[13px] font-medium hover:bg-m-soft">
          Manage connections
        </Link>
      </Section>

      <Section title="Account">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm"><span className="text-muted">Signed in as </span>{email ?? "your account"}</p>
          <Button variant="secondary" onClick={signOut}>Sign out</Button>
        </div>
      </Section>
    </section>
  );
}
