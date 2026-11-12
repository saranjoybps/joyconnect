export const PROTECTED_PREFIXES = ["/chat", "/connections", "/workflows", "/runs"];
export const AUTH_PAGES = ["/login"];

export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/** Only allow same-site relative redirects after login (no open redirects). */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/chat";
  return next;
}
