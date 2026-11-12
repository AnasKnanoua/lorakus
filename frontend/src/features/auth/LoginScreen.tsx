import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useId, useState, type SyntheticEvent } from "react";

import { login, type LoginResult } from "@/api/auth";
import { Orb } from "@/components/Orb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const MESSAGES: Record<Exclude<LoginResult, "ok" | "second_factor_required">, string> = {
  invalid: "Adresse ou mot de passe incorrect.",
  too_many_attempts: "Trop de tentatives. Patiente quelques minutes avant de réessayer.",
  second_factor_setup_required:
    "La double authentification est obligatoire. Active-la d'abord sur le serveur " +
    "(commande enable-second-factor), puis reviens te connecter.",
};

export function LoginScreen() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ids = { email: useId(), password: useId(), code: useId(), error: useId() };

  async function submit(event: SyntheticEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await login(email.trim(), password, needsCode ? code.trim() : undefined);
      if (result === "ok") {
        // Oublier le « pas de session » mis en cache avant la connexion.
        queryClient.removeQueries({ queryKey: ["me"] });
        await navigate({ to: "/" });
      } else if (result === "second_factor_required") {
        if (needsCode) {
          setError("Code incorrect. Saisis le code affiché dans ton application, ou un code de secours.");
        }
        setNeedsCode(true);
      } else {
        setError(MESSAGES[result]);
      }
    } catch {
      setError("Le serveur ne répond pas. Vérifie ta connexion, puis réessaie.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-full items-center justify-center overflow-hidden px-5 py-12">
      <div className="aurora" aria-hidden="true" />
      <form
        onSubmit={(event) => void submit(event)}
        className="relative w-full max-w-[380px] animate-fade-up space-y-6"
        aria-describedby={error ? ids.error : undefined}
      >
        <div className="flex flex-col items-center gap-4 pb-2 text-center">
          <Orb thinking={busy} className="size-12" />
          <div>
            <h1 className="text-[1.625rem] font-semibold tracking-[-0.02em]">Lorakus</h1>
            <p className="mt-1 text-[0.9375rem] text-ink-muted">Ton assistant personnel.</p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor={ids.email} className="text-sm font-medium">
              Adresse e-mail
            </label>
            <Input
              id={ids.email}
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor={ids.password} className="text-sm font-medium">
              Mot de passe
            </label>
            <Input
              id={ids.password}
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
              }}
            />
          </div>
          {needsCode && (
            <div className="space-y-1.5">
              <label htmlFor={ids.code} className="text-sm font-medium">
                Code de double authentification
              </label>
              <Input
                id={ids.code}
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                autoFocus
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                }}
              />
              <p className="text-sm text-ink-muted">
                Le code à 6 chiffres de ton application d'authentification, ou un code de secours.
              </p>
            </div>
          )}
        </div>

        {error && (
          <p id={ids.error} role="alert" className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Connexion…" : "Se connecter"}
        </Button>
      </form>
    </main>
  );
}
