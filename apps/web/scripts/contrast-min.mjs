// WCAG AA check for the minimal (--m-*) tokens in app/globals.css. Keep the values in sync.
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const over = (fg, a, bg) => fg.map((c, i) => Math.round(c * a + bg[i] * (1 - a)));
const lum = ([r, g, b]) => { const f = (c) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4); return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const T = {
  light: { surfaces: { window: "#fbfaf8", panel: "#ffffff", soft: "#f3f2ef", soft2: "#eae9e5" }, text: "#141416", muted: "#666670", accent: "#5247c4",
    ok: "#2d7456", warn: "#8a5a0a", bad: "#ae403c", info: "#2e6593", ink: "#141416", inkFg: "#ffffff", soft: [[82, 71, 196], 0.09], page: ["#f5d9c9", "#ecdcec", "#d9d7f4"] },
  dark: { surfaces: { window: "#0c0c0f", panel: "#131317", soft: "#19191e", soft2: "#212128" }, text: "#ececf0", muted: "#9b9ba6", accent: "#a39cf5",
    ok: "#6dc29a", warn: "#d6a346", bad: "#e5837e", info: "#7bafdc", ink: "#f2f2f5", inkFg: "#0c0c0f", soft: [[163, 156, 245], 0.13], page: ["#16161a", "#1a1a2c", "#25233f"] },
};
let fail = 0;
const check = (l, a, b, min = 4.5) => { const r = ratio(a, b); const ok = r >= min; if (!ok) fail++; console.log(`${ok ? "PASS" : "FAIL"} ${r.toFixed(2).padStart(5)}  ${l}`); };
for (const [n, t] of Object.entries(T)) {
  for (const [sn, s] of Object.entries(t.surfaces)) {
    for (const k of ["text", "muted", "accent", "ok", "warn", "bad", "info"]) check(`${n}: ${k} on ${sn}`, hex(t[k]), hex(s));
    check(`${n}: accent on accent-soft over ${sn}`, hex(t.accent), over(t.soft[0], t.soft[1], hex(s)));
  }
  check(`${n}: ink-fg on ink (primary pill)`, hex(t.inkFg), hex(t.ink));
  // Page backdrop only carries the window; text never sits directly on it, but the window edge must separate (3:1 not required).
}
console.log(fail ? `\n${fail} failing` : "\nAll pairs pass WCAG AA");
process.exit(fail ? 1 : 0);
