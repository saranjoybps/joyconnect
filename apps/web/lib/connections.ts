import { apiFetch } from "@/lib/api";

export type Risk = "read" | "write" | "destructive";

export type Connector = {
  id: string;
  name: string;
  icon: string;
  description: string;
  auth_type: "oauth2" | "api_key" | "connection_string";
  configured: boolean;
  setup_url: string | null;
  tools: { name: string; risk: Risk }[];
};

export type ConnectionStatus = "active" | "needs_reauth" | "revoked";

export type Connection = {
  id: string;
  provider: string;
  status: ConnectionStatus;
  account_label: string | null;
  scopes: string[];
  expires_at: string | null;
  auto_approve_writes: boolean;
  created_at: string;
};

export const connectionsApi = {
  connectors: () => apiFetch<Connector[]>("/api/connectors"),
  list: () => apiFetch<Connection[]>("/api/connections"),
  start: (provider: string) =>
    apiFetch<{ authorize_url: string }>(`/api/connections/${encodeURIComponent(provider)}/start`, { method: "POST" }),
  disconnect: (id: string) => apiFetch<{ ok: boolean }>(`/api/connections/${id}/disconnect`, { method: "POST" }),
  setAutoApprove: (id: string, value: boolean) =>
    apiFetch<Connection>(`/api/connections/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ auto_approve_writes: value }),
    }),
};

const ERROR_TEXT: Record<string, string> = {
  access_denied: "You cancelled the connection.",
  invalid_state: "The connection link expired or was already used. Please try again.",
  provider_unavailable: "The app could not be reached. Please try again.",
};

export function describeOAuthError(code: string): string {
  return ERROR_TEXT[code] ?? `The app returned an error (${code}).`;
}
