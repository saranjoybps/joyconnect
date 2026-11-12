"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { safeNextPath } from "@/lib/routes";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { LogoMark } from "@/components/ui/icons";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(
    params.get("error") ? "Sign-in failed. Please try again." : null,
  );

  const callbackUrl = () =>
    `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    const supabase = getSupabaseBrowserClient();
    const { data, error } =
      mode === "signin"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password, options: { emailRedirectTo: callbackUrl() } });
    setBusy(false);
    if (error) return setMessage(error.message);
    if (mode === "signup" && !data.session) {
      return setMessage("Check your email to confirm your account, then sign in.");
    }
    router.replace(next);
    router.refresh();
  }

  async function onGoogle() {
    setBusy(true);
    const { error } = await getSupabaseBrowserClient().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: callbackUrl() },
    });
    if (error) {
      setBusy(false);
      setMessage(error.message);
    }
  }

  return (
    <div className="anim-fade-up glass-strong w-full max-w-sm space-y-8 rounded-3xl p-8">
      <div className="space-y-2 text-center">
        <span className="btn-gradient mx-auto flex size-12 items-center justify-center rounded-2xl"><LogoMark width={26} height={26} /></span>
        <h1 className="text-2xl font-semibold tracking-tight">{mode === "signin" ? "Sign in" : "Create account"}</h1>
        <p className="text-sm text-muted">Connect your apps, then chat to get things done.</p>
      </div>
      <form onSubmit={onSubmit} className="space-y-4" aria-describedby={message ? "login-msg" : undefined}>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Email</span>
          <Input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Password</span>
          <Input type="password" required minLength={8} value={password}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            onChange={(e) => setPassword(e.target.value)} />
        </label>
        <Button type="submit" size="lg" disabled={busy} className="w-full">
          {mode === "signin" ? "Sign in" : "Sign up"}
        </Button>
      </form>
      <Button variant="secondary" size="lg" onClick={onGoogle} disabled={busy} className="w-full">
        Continue with Google
      </Button>
      {message && <p id="login-msg" role="status" className="text-sm text-bad">{message}</p>}
      <p className="text-center text-sm text-muted">
        {mode === "signin" ? "No account?" : "Have an account?"}{" "}
        <button type="button" className="font-medium text-foreground underline underline-offset-4" onClick={() => setMode(mode === "signin" ? "signup" : "signin")}>
          {mode === "signin" ? "Sign up" : "Sign in"}
        </button>
      </p>
    </div>
  );
}
