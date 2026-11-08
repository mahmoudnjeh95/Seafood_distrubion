import { ApiError } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Brand, Button, Card, Field, Input, ThemeToggle } from "@frutti/ui";
import { type FormEvent, useState } from "react";
import { Navigate, useLocation } from "react-router";

import { useInstance } from "./instance";
import { LanguageSwitch } from "./LanguageSwitch";
import { useLogin, useSession } from "./session";

/**
 * Login screen shared by both apps. `title` names the app ("Administration", "Chauffeur"); `withLanguage` offers
 * French or Arabic; `logoUrl` is the company logo to show in place of the default mark (before login, only a copy kept
 * on the phone can be shown: D-154). `app` picks the training copy this login screen links to (D-290).
 */
export function LoginPage({
  title,
  withLanguage = false,
  logoUrl,
  app,
}: {
  title: string;
  withLanguage?: boolean;
  logoUrl?: string | null;
  app: "admin" | "driver";
}) {
  const { t } = useTranslation();
  const session = useSession();
  const login = useLogin();
  const location = useLocation();
  const instance = useInstance();
  const trainingUrl = app === "admin" ? instance?.training_admin_url : instance?.training_driver_url;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  if (session.data) {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from ?? "/"} replace />;
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate({ username: username.trim(), password });
  }

  function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      if (error.status === 429) return t("auth.tooManyAttempts");
      // The server explains a refused login in the user's language.
      if (error.status === 401 || error.status === 403) return error.message;
    }
    return t("auth.networkError");
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-radial-[60%_70%_at_70%_40%] from-sea-soft to-transparent p-4">
      <Card className="flex w-full max-w-[380px] flex-col gap-5 p-6">
        <div className="flex items-center justify-between gap-3">
          <Brand logoUrl={logoUrl} />
          <ThemeToggle />
        </div>
        {withLanguage && <LanguageSwitch className="self-start" />}
        <div>
          <span className="eyebrow">{title}</span>
          <h1 className="text-[1.4rem]">{t("auth.title")}</h1>
        </div>
        <form onSubmit={submit} aria-label={t("auth.title")} className="flex flex-col gap-4">
          <Field label={t("auth.username")} htmlFor="login-username">
            <Input
              id="login-username"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </Field>
          <Field label={t("auth.password")} htmlFor="login-password">
            <div className="relative">
              <Input
                id="login-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                autoCapitalize="none"
                spellCheck={false}
                required
                value={password}
                className="pe-20"
                onChange={(event) => setPassword(event.target.value)}
              />
              <Button
                variant="ghost"
                aria-pressed={showPassword}
                aria-controls="login-password"
                onClick={() => setShowPassword((shown) => !shown)}
                className="absolute end-1.5 top-1/2 -translate-y-1/2 px-2.5 py-1 text-[0.8rem]"
              >
                {showPassword ? t("auth.hidePassword") : t("auth.showPassword")}
              </Button>
            </div>
          </Field>
          {login.isError && (
            <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
              {errorMessage(login.error)}
            </p>
          )}
          <Button type="submit" variant="primary" size="lg" disabled={login.isPending}>
            {login.isPending ? t("auth.submitting") : t("auth.submit")}
          </Button>
        </form>
        {trainingUrl && (
          <a href={trainingUrl} className="self-center text-[0.88rem] font-semibold text-sea underline">
            {t("auth.trainingLink")}
          </a>
        )}
      </Card>
    </main>
  );
}
