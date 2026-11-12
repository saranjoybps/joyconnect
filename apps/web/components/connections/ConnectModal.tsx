"use client";

import { useState } from "react";
import { CredentialsForm } from "@/components/connections/CredentialsForm";
import { CopyButton } from "@/components/Markdown";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Card";
import { ExternalIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/Modal";
import {
  CARD_BADGE, cardState, providerAppsApi, scopeLabel, timeAgo, type Connection, type Connector,
} from "@/lib/connections";

export type ConnectModalProps = {
  connector: Connector;
  connections: Connection[];
  busy: boolean;
  onClose: () => void;
  onConnect: (connector: Connector) => void;
  onDisconnect: (connection: Connection) => void;
  onToggleAutoApprove: (connection: Connection, value: boolean) => void;
  onTest?: (connection: Connection) => void;
  onSetupChanged: () => void;
};

const STEPS = ["Create credentials", "Enter credentials", "Authorize", "Test and done"] as const;

function RedirectUri({ value }: { value: string }) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-line bg-surface p-2 pl-3">
      <code className="min-w-0 flex-1 select-all break-all font-mono text-xs">{value}</code>
      <CopyButton text={value} label="Copy" />
    </div>
  );
}

export function ConnectModal(props: ConnectModalProps) {
  const { connector, connections, busy, onClose, onConnect, onDisconnect, onToggleAutoApprove, onTest, onSetupChanged } = props;
  const state = cardState(connector, connections);
  const { setup } = connector;
  const [step, setStep] = useState<number>(() =>
    state === "not_set_up" ? 0 : state === "ready" ? 2 : 3);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [ackBusy, setAckBusy] = useState(false);
  const [ackError, setAckError] = useState<string | null>(null);
  const badge = CARD_BADGE[state];

  const configured = setup.source !== "none";
  const done = [configured, configured, connections.length > 0, connections.length > 0 && connections.every((c) => c.last_check_ok)];
  const hasOAuthSteps = connector.auth_type === "oauth2";
  const connectLabel = state === "needs_reconnect" || state === "partial" ? "Reconnect"
    : state === "connected" ? "Add another account" : "Connect";

  async function acknowledge() {
    setAckBusy(true);
    setAckError(null);
    try {
      await providerAppsApi.ackRedirectUri(connector.app_provider);
      onSetupChanged();
    } catch (e) {
      setAckError((e as Error).message);
    } finally {
      setAckBusy(false);
    }
  }

  const stepper = (
    <ol aria-label="Setup steps" className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
      {STEPS.map((label, i) => (
        <li key={label}>
          <button type="button" onClick={() => setStep(i)} aria-current={step === i ? "step" : undefined}
            className={`flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-xs transition-colors ${step === i ? "border-foreground" : "border-line hover:border-line-strong"}`}>
            <span aria-hidden className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${done[i] ? "bg-accent text-accent-fg" : "border border-line-strong text-muted"}`}>
              {done[i] ? "✓" : i + 1}
            </span>
            <span className={step === i ? "font-medium" : "text-muted"}>{label}</span>
            {done[i] && <span className="sr-only">(done)</span>}
          </button>
        </li>
      ))}
    </ol>
  );

  return (
    <Modal open onClose={onClose} size="lg"
      title={`${connector.name}`}
      description={connector.description}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} className="mr-auto">Close</Button>
          <Button variant="secondary" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
          {step < 3 && <Button onClick={() => setStep(step + 1)}>Next</Button>}
        </>
      }>
      <div className="mb-5 flex items-center gap-3">
        <BrandLogo id={connector.id} name={connector.name} size={24} />
        <Badge tone={badge.tone}>{badge.text}</Badge>
        {setup.source === "platform" && <span className="text-xs text-muted">Using this server&apos;s default app</span>}
      </div>

      {stepper}

      {step === 0 && (
        <section aria-labelledby="step-title" className="space-y-5">
          <h3 id="step-title" className="text-sm font-semibold">1. Create credentials</h3>
          {connector.setup_guide.length > 0 ? (
            <ol className="list-decimal space-y-2 pl-5 text-sm">
              {connector.setup_guide.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
          ) : (
            <p className="text-sm text-muted">Create the credentials in {connector.name}&apos;s developer settings.</p>
          )}
          {connector.console_url && (
            <a href={connector.console_url} target="_blank" rel="noreferrer"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-line-strong px-4 text-sm font-medium hover:bg-surface-2">
              Open the developer console <ExternalIcon width={14} height={14} />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          )}

          {setup.source === "user" && setup.redirect_uri_changed && connector.redirect_uri && (
            <div role="alert" className="space-y-2 rounded-xl border border-warn/40 p-3 text-sm">
              <p>
                The redirect URI changed since you saved this app. Update it in the provider console to
                the one below, or connecting will fail with a redirect URI mismatch.
              </p>
              {setup.registered_redirect_uri && (
                <p className="text-xs text-muted">Previously: <code className="break-all">{setup.registered_redirect_uri}</code></p>
              )}
              <Button size="sm" variant="secondary" onClick={acknowledge} disabled={ackBusy}>I&apos;ve updated it</Button>
              {ackError && <p className="text-xs text-bad">{ackError}</p>}
            </div>
          )}

          {connector.redirect_uri && (
            <div className="space-y-2">
              <p className="text-sm font-medium">Redirect URI</p>
              <RedirectUri value={connector.redirect_uri} />
              <p className="text-xs text-muted">
                {connector.redirect_info.mode === "tunnel"
                  ? "public HTTPS tunnel"
                  : "localhost (works for Google and GitHub in dev)"}
              </p>
              {connector.redirect_info.note && <p className="text-xs text-muted">{connector.redirect_info.note}</p>}
              {connector.redirect_info.mode === "localhost" && connector.redirect_info.localhost_redirect === "no" && (
                <p role="note" className="text-xs font-medium text-warn">
                  {connector.name} will not accept this localhost URI. Run the tunnel (scripts/dev-tunnel) and
                  register the HTTPS URI it prints.
                </p>
              )}
            </div>
          )}

          {connector.scopes.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-medium">Scopes to enable</p>
              <ul className="flex flex-wrap gap-1.5">
                {connector.scopes.map((s) => (
                  <li key={s}><code className="rounded-md border border-line bg-surface px-1.5 py-0.5 text-xs">{s}</code></li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {step === 1 && (
        <section aria-labelledby="step-title" className="space-y-4">
          <h3 id="step-title" className="text-sm font-semibold">2. Enter credentials</h3>
          <CredentialsForm connector={connector} onSaved={onSetupChanged} onRemoved={() => { onSetupChanged(); setStep(0); }} />
        </section>
      )}

      {step === 2 && (
        <section aria-labelledby="step-title" className="space-y-4">
          <h3 id="step-title" className="text-sm font-semibold">3. Authorize</h3>
          {!configured ? (
            <p className="text-sm text-muted">Save your credentials in step 2 first, then authorize.</p>
          ) : (
            <>
              <p className="text-sm text-muted">
                {hasOAuthSteps
                  ? `You will be sent to ${connector.name} to approve access, then brought back here.`
                  : `The saved credentials are used to connect ${connector.name}.`}
              </p>
              {connector.scopes.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">Permissions requested</p>
                  <ul className="list-disc space-y-1 pl-5 text-sm">
                    {connector.scopes.map((s) => <li key={s}>{scopeLabel(s)}</li>)}
                  </ul>
                </div>
              )}
              <Button disabled={busy} onClick={() => onConnect(connector)}>{connectLabel}</Button>
            </>
          )}
        </section>
      )}

      {step === 3 && (
        <section aria-labelledby="step-title" className="space-y-4">
          <h3 id="step-title" className="text-sm font-semibold">4. Test and done</h3>
          {connections.length === 0 && (
            <p className="text-sm text-muted">No account is connected yet. Finish step 3 to connect one.</p>
          )}
          <ul className="space-y-3">
            {connections.map((c) => (
              <li key={c.id} className="space-y-3 rounded-xl border border-line p-4 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="truncate font-medium">{c.account_label ?? "Account"}</span>
                  {confirming === c.id ? (
                    <span className="flex items-center gap-2">
                      <Button size="sm" variant="danger" disabled={busy} onClick={() => { setConfirming(null); onDisconnect(c); }}>
                        Confirm disconnect
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>Cancel</Button>
                    </span>
                  ) : (
                    <Button size="sm" variant="danger" disabled={busy} onClick={() => setConfirming(c.id)}>Disconnect</Button>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  {onTest && (
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => onTest(c)}
                      aria-label={`Test connection ${c.account_label ?? connector.name}`}>
                      Test connection
                    </Button>
                  )}
                  <span aria-live="polite" className="text-xs text-muted">
                    {c.last_checked_at ? (
                      <>
                        <strong className={c.last_check_ok ? "text-ok" : "text-bad"}>{c.last_check_ok ? "Passed" : "Failed"}</strong>
                        {" "}· checked {timeAgo(c.last_checked_at)}
                      </>
                    ) : "Not tested yet"}
                  </span>
                </div>
                {c.last_checked_at && c.last_check_message && (
                  <p className={`text-xs ${c.last_check_ok ? "text-muted" : "text-bad"}`}>{c.last_check_message}</p>
                )}

                {c.partial && (
                  <p role="alert" className="rounded-lg border border-warn/40 p-2.5 text-xs">
                    {connector.auth_type === "oauth2" ? "The provider" : "This app"} did not grant:{" "}
                    {(c.missing_scopes ?? []).map(scopeLabel).join(", ")}. Reconnect {connector.name} and tick the{" "}
                    {connector.name.replace(/^Google /, "")} permission on the consent screen.
                  </p>
                )}

                {c.scopes.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-xs font-medium">Granted permissions ({c.scopes.length})</p>
                    <ul className="flex flex-wrap gap-1.5">
                      {c.scopes.map((s) => (
                        <li key={s} className="rounded-md border border-line px-2 py-0.5 text-xs text-muted">{scopeLabel(s)}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <label className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={c.auto_approve_writes} disabled={busy}
                    onChange={(e) => onToggleAutoApprove(c, e.target.checked)} className="size-4 accent-[var(--accent)]" />
                  <span>Auto-approve writes</span>
                </label>
              </li>
            ))}
          </ul>

          <div className="flex flex-wrap items-center gap-3">
            {(state === "needs_reconnect" || state === "partial") && (
              <Button disabled={busy} onClick={() => onConnect(connector)}>Reconnect</Button>
            )}
            {configured && connections.length > 0 && (
              <Button variant="secondary" disabled={busy} onClick={() => onConnect(connector)}>Add another account</Button>
            )}
            {connector.setup_url && connections.length > 0 && (
              <a href={connector.setup_url} target="_blank" rel="noreferrer"
                className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium underline underline-offset-4">
                Choose repositories <ExternalIcon width={14} height={14} />
              </a>
            )}
          </div>
        </section>
      )}
    </Modal>
  );
}
