export type Group<T> = { label: string; items: T[] };

const DAY = 86_400_000;

/** Start of the local calendar day. */
function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Buckets (newest first) as Today, Yesterday, Previous 7 days, Previous 30 days, Older. Empty buckets are omitted. */
export function groupByDate<T extends { created_at: string }>(rows: T[], now: Date = new Date()): Group<T>[] {
  const today = startOfDay(now);
  const buckets: Group<T>[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Previous 7 days", items: [] },
    { label: "Previous 30 days", items: [] },
    { label: "Older", items: [] },
  ];
  const sorted = [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at));
  for (const r of sorted) {
    const age = today - startOfDay(new Date(r.created_at));
    const i = age < DAY ? 0 : age < 2 * DAY ? 1 : age < 7 * DAY ? 2 : age < 30 * DAY ? 3 : 4;
    buckets[i].items.push(r);
  }
  return buckets.filter((b) => b.items.length > 0);
}
