"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePref = "system" | "light" | "dark";
const KEY = "theme";

/** Runs before paint (inline in <head>) so there is no flash of the wrong theme. */
export const THEME_SCRIPT = `(function(){try{var p=localStorage.getItem("${KEY}")||"system";var d=p==="dark"||(p==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d)}catch(e){}})()`;

type Ctx = { pref: ThemePref; resolved: "light" | "dark"; setPref: (p: ThemePref) => void; toggle: () => void };
const ThemeCtx = createContext<Ctx | null>(null);

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function systemDark(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>("system");
  const [sysDark, setSysDark] = useState(false);
  const [ready, setReady] = useState(false);   // until the stored choice is read, keep the class the inline script set

  useEffect(() => {
    // Read browser-only state after mount (the server render cannot know it).
    /* eslint-disable react-hooks/set-state-in-effect */
    setPrefState(readPref());
    setSysDark(systemDark());
    /* eslint-enable react-hooks/set-state-in-effect */
    setReady(true);
    if (typeof matchMedia !== "function") return;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => setSysDark(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);

  const resolved: "light" | "dark" = pref === "system" ? (sysDark ? "dark" : "light") : pref;

  useEffect(() => {
    if (ready) document.documentElement.classList.toggle("dark", resolved === "dark");
  }, [resolved, ready]);

  const setPref = useCallback((p: ThemePref) => {
    setPrefState(p);
    try { localStorage.setItem(KEY, p); } catch { /* storage unavailable: theme still applies for this visit */ }
  }, []);
  const toggle = useCallback(() => setPref(resolved === "dark" ? "light" : "dark"), [resolved, setPref]);

  const value = useMemo(() => ({ pref, resolved, setPref, toggle }), [pref, resolved, setPref, toggle]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): Ctx {
  const c = useContext(ThemeCtx);
  if (c) return c;
  // Outside a provider (isolated component tests): inert.
  return { pref: "system", resolved: "light", setPref: () => {}, toggle: () => {} };
}
