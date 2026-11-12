// WCAG AA check for the premium (--p-*) tokens in app/globals.css. Keep values in sync.
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const over = (fg, a, bg) => fg.map((c, i) => Math.round(c * a + bg[i] * (1 - a)));
const lum = ([r, g, b]) => { const f = (c) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4); return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const T = {
  light: { bg: "#faf9f7", surfaces: ["#ffffff", "#f4f3f0", "#ecebe7"], text: "#16161d", muted: "#5e5e6b", accentText: "#4338ca", accent: "#4f46d8", accentHover: "#4339c4",
    ok: "#25704f", warn: "#8a5a08", bad: "#b13c38", info: "#2b6598", soft: [[79, 70, 216], 0.09] },
  dark: { bg: "#0a0a0f", surfaces: ["#101016", "#15151c", "#1c1c25"], text: "#ececf1", muted: "#9a9aa8", accentText: "#a5a2ff", accent: "#5b57e8", accentHover: "#4f4bd8",
    ok: "#6cc59a", warn: "#d9a441", bad: "#e8807b", info: "#78aedd", soft: [[124, 120, 255], 0.14] },
};
let fail = 0;
const check = (l, a, b, min = 4.5) => { const r = ratio(a, b); const ok = r >= min; if (!ok) fail++; console.log(`${ok ? "PASS" : "FAIL"} ${r.toFixed(2).padStart(5)}  ${l}`); };
for (const [n, t] of Object.entries(T)) {
  for (const s of [t.bg, ...t.surfaces]) {
    for (const k of ["text", "muted", "accentText", "ok", "warn", "bad", "info"]) check(`${n}: ${k} on ${s}`, hex(t[k]), hex(s));
    // text on the soft accent tint (active states, accent badges) composited over the surface
    check(`${n}: accentText on accent-soft over ${s}`, hex(t.accentText), over(t.soft[0], t.soft[1], hex(s)));
  }
  check(`${n}: white on accent button`, [255, 255, 255], hex(t.accent));
  check(`${n}: white on accent button hover`, [255, 255, 255], hex(t.accentHover));
}
console.log(fail ? `\n${fail} failing` : "\nAll pairs pass WCAG AA");
process.exit(fail ? 1 : 0);
