"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { ApiError } from "@/lib/api";
import { providerAppsApi, type Connector, type TestResult } from "@/lib/connections";

type Props = {
  connector: Connector;
  onSaved: () => void;
  onRemoved: () => void;
};

/** Step 2: the user's own developer credentials. Saved encrypted on the server; secrets are never shown again. */
export function CredentialsForm({ connector, onSaved, onRemoved }: Props) {
  const { setup } = connector;
  const hasUserApp = setup.source === "user";
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(connector.credential_fields.map((f) => [f.key, f.secret ? "" : setup.fields[f.key] ?? ""])),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [removeStep, setRemoveStep] = useState<null | "confirm" | { count: number; names: string[] }>(null);
  const formId = `setup-${connector.id}`;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setMessage(null);
    try {
      await providerAppsApi.save(connector.app_provider, values);
      setValues((v) => Object.fromEntries(Object.entries(v).map(([k, val]) =>
        [k, connector.credential_fields.find((f) => f.key === k)?.secret ? "" : val])));
      setMessage({ ok: true, text: "Saved. Use Test to check the credentials, then Connect." });
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.detail.errors) setErrors(err.detail.errors);
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setMessage(null);
    try {
      const r: TestResult = await providerAppsApi.test(connector.app_provider);
      setErrors(r.errors ?? {});
      setMessage({ ok: r.ok, text: r.message });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function remove(confirm: boolean) {
    setBusy(true);
    setMessage(null);
    try {
      await providerAppsApi.remove(connector.app_provider, confirm);
      setRemoveStep(null);
      onRemoved();
    } catch (err) {
      if (err instanceof ApiError && err.detail.code === "has_connections") {
        const conns = (err.detail.connections as { provider: string; account_label: string | null }[]) ?? [];
        setRemoveStep({ count: conns.length, names: conns.map((c) => c.account_label ?? c.provider) });
      } else {
        setMessage({ ok: false, text: (err as Error).message });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      {setup.source === "platform" && (
        <p className="text-sm text-muted">This server provides a default app. Enter your own below to use it instead.</p>
      )}

      <form id={formId} onSubmit={save} className="space-y-4" noValidate>
        {connector.credential_fields.map((f) => {
          const id = `${formId}-${f.key}`;
          const saved = f.secret && setup.secrets_set.includes(f.key);
          const isClientId = f.key === "client_id" && setup.client_id_masked;
          return (
            <div key={f.key}>
              <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
                {f.label}{!f.required && <span className="font-normal text-muted"> (optional)</span>}
              </label>
              <Input id={id} type={f.secret ? "password" : "text"} autoComplete="off" spellCheck={false}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                placeholder={saved ? "Saved. Leave blank to keep" : isClientId ? `Saved: ${setup.client_id_masked}` : ""}
                aria-invalid={Boolean(errors[f.key])} aria-describedby={`${id}-help`} className="font-mono text-xs" />
              <p id={`${id}-help`} className="mt-1.5 text-xs text-muted">
                {errors[f.key] ? <span className="text-bad">{errors[f.key]}. </span> : null}
                {f.help_text}
              </p>
            </div>
          );
        })}
        {hasUserApp && setup.client_id_masked && (
          <p className="text-xs text-muted">Your app: <code>{setup.client_id_masked}</code></p>
        )}
      </form>

      {message && (
        <p role="status" className={`text-sm ${message.ok ? "text-ok" : "text-bad"}`}>{message.text}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" form={formId} disabled={busy}>Save</Button>
        <Button variant="secondary" onClick={test} disabled={busy || setup.source === "none"}>Test</Button>
        {hasUserApp && removeStep === null && (
          <Button variant="danger" size="sm" className="ml-auto" onClick={() => setRemoveStep("confirm")} disabled={busy}>
            Remove credentials
          </Button>
        )}
      </div>

      {removeStep === "confirm" && (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-xl border border-bad/40 p-3 text-sm">
          <span>Remove the saved credentials?</span>
          <Button size="sm" variant="danger" onClick={() => remove(false)} disabled={busy}>Remove</Button>
          <Button size="sm" variant="ghost" onClick={() => setRemoveStep(null)}>Cancel</Button>
        </div>
      )}
      {removeStep !== null && removeStep !== "confirm" && (
        <div role="alert" className="space-y-2 rounded-xl border border-bad/40 p-3 text-sm">
          <p>
            Removing these credentials will disconnect {removeStep.count} connection{removeStep.count === 1 ? "" : "s"}:{" "}
            {removeStep.names.join(", ")}.
          </p>
          <div className="flex gap-2">
            <Button size="sm" variant="danger" onClick={() => remove(true)} disabled={busy}>Remove and disconnect</Button>
            <Button size="sm" variant="ghost" onClick={() => setRemoveStep(null)}>Cancel</Button>
          </div>
        </div>
      )}
    </div>
  );
}
