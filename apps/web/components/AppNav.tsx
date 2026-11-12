"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

const LINKS = [
  { href: "/chat", label: "Chat" },
  { href: "/connections", label: "Connections" },
  { href: "/runs", label: "Runs" },
];

export function AppNav() {
  const pathname = usePathname();
  const router = useRouter();

  async function signOut() {
    await getSupabaseBrowserClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  return (
    <header className="border-b border-neutral-200 dark:border-neutral-800">
      <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <span className="font-semibold">Connect</span>
        <ul className="flex gap-1">
          {LINKS.map((l) => {
            const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <li key={l.href}>
                <Link
                  href={l.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-neutral-100 font-medium dark:bg-neutral-800" : "hover:bg-neutral-50 dark:hover:bg-neutral-900"}`}
                >
                  {l.label}
                </Link>
              </li>
            );
          })}
        </ul>
        <button type="button" onClick={signOut} className="ml-auto text-sm underline">
          Sign out
        </button>
      </nav>
    </header>
  );
}
