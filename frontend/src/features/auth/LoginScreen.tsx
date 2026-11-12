import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useId, useState, type SyntheticEvent } from "react";

import { login, type LoginResult } from "@/api/auth";
import { Monogram } from "@/components/Monogram";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const MESSAGES: Record<Exclude<LoginResult, "ok" | "second_factor_required">, string> = {
  invalid: "Adresse ou mot de passe incorrect.",
  too_many_attempts: "Trop de tentatives. Patientez quelques minutes avant de réessayer.",
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
          setError("Code incorrect. Saisissez le code affiché dans votre application, ou un code de secours.");
        }
        setNeedsCode(true);
      } else {
        setError(MESSAGES[result]);
      }
    } catch {
      setError("Le serveur ne répond pas. Vérifiez votre connexion, puis réessayez.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center px-6 py-12">
      <form
        onSubmit={(event) => void submit(event)}
        className="w-full max-w-sm space-y-6"
        aria-describedby={error ? ids.error : undefined}
      >
        <div className="flex items-center gap-3">
          <Monogram className="size-10" />
          <h1 className="text-2xl font-bold">Lorakus</h1>
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
                Le code à 6 chiffres de votre application d'authentification, ou un code de secours.
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
