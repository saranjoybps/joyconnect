import { apiFetch } from "@/lib/api";

export type Risk = "read" | "write" | "destructive";

export type CredentialField = {
  key: string;
  label: string;
  secret: boolean;
  help_text: string;
  required: boolean;
  pattern_hint: string;
};

/** Safe view of the user's saved credentials: never contains secret values. */
export type SetupInfo = {
  provider: string;
  source: "user" | "platform" | "none";
  client_id_masked: string | null;
  fields: Record<string, string>;
  secrets_set: string[];
  platform_available: boolean;
  created_at: string | null;
};

export type Connector = {
  id: string;
  name: string;
  icon: string;
  description: string;
  auth_type: "oauth2" | "api_key" | "connection_string";
  app_provider: string;
  configured: boolean;
  setup: SetupInfo;
  credential_fields: CredentialField[];
  redirect_uris: string[];
  scopes: string[];
  console_url: string | null;
  setup_guide: string[];
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
  provider_app_id: string | null;
};

export type CardState = "not_set_up" | "ready" | "connected" | "needs_reconnect";

export function cardState(connector: Connector, connections: Connection[]): CardState {
  if (connections.some((c) => c.status === "needs_reauth")) return "needs_reconnect";
  if (connections.length > 0) return "connected";
  return connector.configured ? "ready" : "not_set_up";
}

export type StartResult = { authorize_url?: string; connected?: boolean };
export type TestResult = { ok: boolean; source: string; message: string; errors: Record<string, string> };

export const connectionsApi = {
  connectors: () => apiFetch<Connector[]>("/api/connectors"),
  list: () => apiFetch<Connection[]>("/api/connections"),
  start: (provider: string) =>
    apiFetch<StartResult>(`/api/connections/${encodeURIComponent(provider)}/start`, { method: "POST" }),
  disconnect: (id: string) => apiFetch<{ ok: boolean }>(`/api/connections/${id}/disconnect`, { method: "POST" }),
  setAutoApprove: (id: string, value: boolean) =>
    apiFetch<Connection>(`/api/connections/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ auto_approve_writes: value }),
    }),
};

export const providerAppsApi = {
  save: (provider: string, values: Record<string, string>) =>
    apiFetch<SetupInfo>(`/api/provider-apps/${encodeURIComponent(provider)}`, {
      method: "POST",
      body: JSON.stringify({ values }),
    }),
  test: (provider: string) =>
    apiFetch<TestResult>(`/api/provider-apps/${encodeURIComponent(provider)}/test`, { method: "POST" }),
  remove: (provider: string, confirm: boolean) =>
    apiFetch<{ ok: boolean; disconnected: number }>(
      `/api/provider-apps/${encodeURIComponent(provider)}${confirm ? "?confirm=true" : ""}`,
      { method: "DELETE" },
    ),
};

const ERROR_TEXT: Record<string, string> = {
  access_denied: "You cancelled the connection.",
  invalid_state: "The connection link expired or was already used. Please try again.",
  provider_unavailable: "The app could not be reached. Please try again.",
  setup_required: "This app's credentials were removed. Set it up again, then connect.",
  redirect_uri_mismatch: "The redirect URI registered with the provider doesn't match. Copy it from Set up.",
};

export function describeOAuthError(code: string): string {
  return ERROR_TEXT[code] ?? `The app returned an error (${code}).`;
}
