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
  /** The redirect URI changed (e.g. a tunnel started) since the user registered the app. */
  redirect_uri_changed: boolean;
  registered_redirect_uri: string | null;
};

/** How the redirect URI is reachable; built server-side from PUBLIC_API_BASE_URL. */
export type RedirectInfo = {
  mode: "localhost" | "tunnel";
  localhost_redirect: "yes" | "no" | "unverified";
  note: string | null;
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
  redirect_uri: string | null;
  redirect_info: RedirectInfo;
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
  /** Permissions the connector needs that the provider did not grant (user unticked them). */
  missing_scopes?: string[];
  partial?: boolean;
};

export type CardState = "not_set_up" | "ready" | "connected" | "partial" | "needs_reconnect";

const SCOPE_NAMES: Record<string, string> = {
  openid: "Sign-in (openid)",
  email: "Email address",
  "https://www.googleapis.com/auth/userinfo.email": "Email address",
  "https://www.googleapis.com/auth/spreadsheets": "Google Sheets (read and write)",
  "https://www.googleapis.com/auth/documents": "Google Docs (read and write)",
  "https://www.googleapis.com/auth/calendar.events": "Google Calendar events",
  "https://www.googleapis.com/auth/calendar.calendarlist.readonly": "Calendar list (read)",
  "https://www.googleapis.com/auth/calendar.freebusy": "Calendar free/busy",
  "https://www.googleapis.com/auth/gmail.send": "Send email (Gmail)",
  "https://www.googleapis.com/auth/gmail.labels": "Gmail labels",
  "https://www.googleapis.com/auth/drive.file": "Google Drive (files this app created)",
  "https://www.googleapis.com/auth/presentations": "Google Slides (read and write)",
  "https://www.googleapis.com/auth/forms.body": "Google Forms (create and edit)",
  "https://www.googleapis.com/auth/forms.responses.readonly": "Form responses (read)",
  "https://www.googleapis.com/auth/tasks": "Google Tasks (read and write)",
  "https://www.googleapis.com/auth/contacts": "Google Contacts (read and write)",
  "https://www.googleapis.com/auth/meetings.space.created": "Google Meet spaces this app created",
};

/** Human name for a granted scope; unknown scopes show their last path segment. */
export function scopeLabel(scope: string): string {
  return SCOPE_NAMES[scope] ?? scope.split("/").pop() ?? scope;
}

export function cardState(connector: Connector, connections: Connection[]): CardState {
  if (connections.some((c) => c.status === "needs_reauth")) return "needs_reconnect";
  if (connections.some((c) => c.partial)) return "partial";
  if (connections.length > 0) return "connected";
  return connector.configured ? "ready" : "not_set_up";
}

export type StartResult = { authorize_url?: string; connected?: boolean };
export type TestResult = { ok: boolean; source: string; message: string; errors: Record<string, string> };

export const connectionsApi = {
  connectors: async () => {
    const list = await apiFetch<Connector[]>("/api/connectors");
    // Tolerate an older API that predates provider setup info.
    return list.map((c) => ({
      ...c,
      setup: c.setup ?? {
        provider: c.app_provider ?? c.id, source: "none" as const, client_id_masked: null,
        fields: {}, secrets_set: [], platform_available: false, created_at: null,
        redirect_uri_changed: false, registered_redirect_uri: null,
      },
      redirect_uri: c.redirect_uri ?? null,
      redirect_info: c.redirect_info ?? { mode: "localhost" as const, localhost_redirect: "unverified" as const, note: null },
      credential_fields: c.credential_fields ?? [],
      scopes: c.scopes ?? [],
      setup_guide: c.setup_guide ?? [],
    }));
  },
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
  /** The user updated the redirect URI in the provider console: clear the "changed" banner. */
  ackRedirectUri: (provider: string) =>
    apiFetch<SetupInfo>(`/api/provider-apps/${encodeURIComponent(provider)}/redirect-uri/ack`, { method: "POST" }),
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
