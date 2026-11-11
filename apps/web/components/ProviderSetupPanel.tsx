"use client";

import { useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api";
import { providerAppsApi, type Connector, type TestResult } from "@/lib/connections";

type Props = {
  connector: Connector;
  onSaved: () => void;
  onRemoved: () => void;
  onClose: () => void;
};

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable: the value is selectable */
    }
  }
  return (
    <div className="flex items-center gap-2">
      <code className="min-w-0 flex-1 select-all break-all rounded bg-neutral-100 px-2 py-1 text-xs dark:bg-neutral-800">{value}</code>
      <button type="button" onClick={copy} className="shrink-0 text-xs underline">{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}

export function ProviderSetupPanel({ connector, onSaved, onRemoved, onClose }: Props) {
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
    <div className="space-y-4 rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-800">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-medium">
          Set up {connector.app_provider === connector.id
            ? connector.name
            : `your ${connector.app_provider.charAt(0).toUpperCase()}${connector.app_provider.slice(1)} app`}
        </h3>
        <button type="button" onClick={onClose} className="text-xs underline">Close</button>
      </div>

      {setup.source === "platform" && (
        <p className="text-neutral-600 dark:text-neutral-400">
          This server provides a default app. Enter your own below to use it instead.
        </p>
      )}

      {connector.setup_guide.length > 0 && (
        <ol className="list-decimal space-y-1 pl-5 text-neutral-700 dark:text-neutral-300">
          {connector.setup_guide.map((step, i) => <li key={i}>{step}</li>)}
        </ol>
      )}
      {connector.console_url && (
        <a href={connector.console_url} target="_blank" rel="noreferrer" className="inline-block underline">
          Open the developer console ↗
        </a>
      )}

      {connector.redirect_uris.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium">Redirect URI{connector.redirect_uris.length > 1 ? "s (add all)" : ""}</p>
          {connector.redirect_uris.map((u) => <CopyField key={u} value={u} />)}
        </div>
      )}
      {connector.scopes.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium">Scopes</p>
          <ul className="flex flex-wrap gap-1">
            {connector.scopes.map((s) => (
              <li key={s}><code className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">{s}</code></li>
            ))}
          </ul>
        </div>
      )}

      <form id={formId} onSubmit={save} className="space-y-3" noValidate>
        {connector.credential_fields.map((f) => {
          const id = `${formId}-${f.key}`;
          const saved = f.secret && setup.secrets_set.includes(f.key);
          const isClientId = f.key === "client_id" && setup.client_id_masked;
          return (
            <div key={f.key}>
              <label htmlFor={id} className="font-medium">
                {f.label}{!f.required && <span className="font-normal text-neutral-500"> (optional)</span>}
              </label>
              <input
                id={id}
                type={f.secret ? "password" : "text"}
                autoComplete="off"
                spellCheck={false}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                placeholder={saved ? "Saved. Leave blank to keep" : isClientId ? `Saved: ${setup.client_id_masked}` : ""}
                aria-invalid={Boolean(errors[f.key])}
                aria-describedby={`${id}-help`}
                className="mt-1 w-full rounded-md border border-neutral-300 bg-transparent px-2 py-1.5 font-mono text-xs aria-[invalid=true]:border-red-500 dark:border-neutral-700"
              />
              <p id={`${id}-help`} className="mt-1 text-xs text-neutral-500">
                {errors[f.key] ? <span className="text-red-700 dark:text-red-400">{errors[f.key]}. </span> : null}
                {f.help_text}
              </p>
            </div>
          );
        })}
      </form>

      {message && (
        <p role="status" className={message.ok ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400"}>
          {message.text}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" form={formId} disabled={busy}
          className="rounded-md bg-neutral-900 px-3 py-1.5 font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900">
          Save
        </button>
        <button type="button" onClick={test} disabled={busy || setup.source === "none"}
          className="rounded-md border border-neutral-400 px-3 py-1.5 font-medium disabled:opacity-50">
          Test
        </button>
        {hasUserApp && removeStep === null && (
          <button type="button" onClick={() => setRemoveStep("confirm")} disabled={busy}
            className="ml-auto text-xs text-red-700 underline dark:text-red-400">
            Remove credentials
          </button>
        )}
      </div>

      {removeStep === "confirm" && (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md bg-red-50 p-2 dark:bg-red-950/40">
          <span>Remove the saved credentials?</span>
          <button type="button" onClick={() => remove(false)} disabled={busy} className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white">Remove</button>
          <button type="button" onClick={() => setRemoveStep(null)} className="text-xs underline">Cancel</button>
        </div>
      )}
      {removeStep !== null && removeStep !== "confirm" && (
        <div role="alert" className="space-y-2 rounded-md bg-red-50 p-2 dark:bg-red-950/40">
          <p>
            Removing these credentials will disconnect {removeStep.count} connection{removeStep.count === 1 ? "" : "s"}:{" "}
            {removeStep.names.join(", ")}.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={() => remove(true)} disabled={busy} className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white">
              Remove and disconnect
            </button>
            <button type="button" onClick={() => setRemoveStep(null)} className="text-xs underline">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
