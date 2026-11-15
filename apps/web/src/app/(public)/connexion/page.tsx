"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert, Button, Card, Input, Label } from "@/components/ui";
import { api, detail } from "@/lib/api";
import { t } from "@/lib/i18n";

export default function Login() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const r = await api.POST("/auth/magic-link", { body: { email } });
    setBusy(false);
    if (r.error) setError(detail(r.error));
    else setSent(true);
  };

  return (
    <main id="contenu" className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <Link href="/" className="mb-6 font-semibold text-brand">
        {t("app.name")}
      </Link>
      <Card className="p-6">
        <h1 className="text-xl font-semibold">{t("login.title")}</h1>
        {sent ? (
          <div className="mt-4">
            <Alert tone="ok">{t("login.sent")}</Alert>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-4 space-y-4">
            <div>
              <Label htmlFor="email">{t("login.email")}</Label>
              <Input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            {error && <Alert tone="danger" role="alert">{error}</Alert>}
            <Button type="submit" disabled={busy} className="w-full">
              {t("login.submit")}
            </Button>
            <a href="/api/auth/google/start" className="block text-center text-sm text-brand hover:underline">
              {t("login.google")}
            </a>
          </form>
        )}
      </Card>
    </main>
  );
}
