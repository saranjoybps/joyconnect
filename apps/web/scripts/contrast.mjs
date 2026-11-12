// WCAG AA contrast check for the design tokens in app/globals.css (keep the values in sync).
// Glass is composited over the worst-case aurora blob, then text colours are measured against the result.
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const over = (fg, a, bg) => fg.map((c, i) => Math.round(c * a + bg[i] * (1 - a)));
const lum = ([r, g, b]) => {
  const f = (c) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

const themes = {
  light: {
    bg: hex("#f3f2ff"), aurora: [[129, 140, 248, 0.42], [196, 181, 253, 0.5], [103, 232, 249, 0.34]],
    glass: [255, 255, 255, 0.66], glassStrong: [255, 255, 255, 0.86], field: [255, 255, 255, 0.72],
    text: { foreground: "#1b1a3a", muted: "#55587a", success: "#047857", warning: "#92400e", error: "#be123c", info: "#0369a1", accent: "#4f46e5" },
  },
  dark: {
    bg: hex("#0a0f24"), aurora: [[99, 102, 241, 0.34], [139, 92, 246, 0.34], [34, 211, 238, 0.2]],
    glass: [22, 26, 60, 0.58], glassStrong: [18, 22, 52, 0.86], field: [255, 255, 255, 0.07],
    text: { foreground: "#eceaff", muted: "#a9acd0", success: "#34d399", warning: "#fbbf24", error: "#fda4af", info: "#38bdf8", accent: "#a5b4fc" },
  },
};

let failures = 0;
const check = (label, a, b, min = 4.5) => {
  const r = ratio(a, b);
  const ok = r >= min;
  if (!ok) failures++;
  console.log(`${ok ? "PASS" : "FAIL"} ${r.toFixed(2).padStart(5)}  (min ${min})  ${label}`);
};

for (const [name, t] of Object.entries(themes)) {
  const backdrops = [["base", t.bg], ...t.aurora.map((a, i) => [`aurora${i}`, over(a.slice(0, 3), a[3], t.bg)])];
  for (const [bn, back] of backdrops) {
    for (const [sn, s] of [["glass", t.glass], ["glass-strong", t.glassStrong], ["field", t.field]]) {
      const surface = over(s.slice(0, 3), s[3], back);
      for (const [tn, hx] of Object.entries(t.text)) {
        if (tn === "accent" && name === "light" && sn === "field") continue;
        check(`${name}: ${tn} on ${sn} over ${bn}`, hex(hx), surface);
      }
    }
  }
}
// White text on the gradient button and user bubbles (worst stop).
for (const [n, h] of [["indigo #4f46e5", "#4f46e5"], ["violet #7c3aed", "#7c3aed"], ["cyan #0e7490", "#0e7490"]]) {
  check(`white on gradient stop ${n}`, [255, 255, 255], hex(h));
}
// Large gradient headings (3:1) on the page background.
for (const [n, h, bg] of [["light indigo", "#4f46e5", themes.light.bg], ["light cyan", "#0e7490", themes.light.bg],
  ["dark indigo-300", "#a5b4fc", themes.dark.bg], ["dark violet-300", "#c4b5fd", themes.dark.bg], ["dark cyan-300", "#67e8f9", themes.dark.bg]]) {
  check(`heading stop ${n}`, hex(h), bg, 3);
}
console.log(failures ? `\n${failures} failing pair(s)` : "\nAll pairs pass WCAG AA");
process.exit(failures ? 1 : 0);
