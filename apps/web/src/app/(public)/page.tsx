import Link from "next/link";

import { LinkButton } from "@/components/ui";
import { t } from "@/lib/i18n";

const PILLARS = ["p1", "p2", "p3", "p4"];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5">
        <span className="flex items-center gap-2 text-lg font-semibold text-brand">
          <span aria-hidden className="inline-block h-6 w-6 rounded-full border-4 border-brand" />
          {t("app.name")}
        </span>
        <Link href="/connexion" className="text-sm font-medium text-brand hover:underline">
          {t("landing.login")}
        </Link>
      </header>
      <main id="contenu" className="mx-auto max-w-6xl px-4">
        <section className="py-14 md:py-20">
          <p className="text-sm font-medium uppercase tracking-wide text-muted">{t("app.tagline")}</p>
          <h1 className="mt-3 max-w-3xl text-3xl font-semibold leading-tight md:text-5xl">{t("landing.title")}</h1>
          <p className="mt-5 max-w-2xl text-lg text-muted">{t("landing.lead")}</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <LinkButton href="/connexion" className="px-5 py-3 text-base">
              {t("landing.cta")}
            </LinkButton>
          </div>
        </section>
        <section aria-label="Fonctionnalités" className="grid gap-4 md:grid-cols-4">
          {PILLARS.map((p) => (
            <div key={p} className="rounded-lg border border-line bg-surface p-5">
              <h2 className="font-semibold text-brand">{t(`landing.${p}t`)}</h2>
              <p className="mt-2 text-sm text-muted">{t(`landing.${p}`)}</p>
            </div>
          ))}
        </section>
        <section className="mt-12 rounded-lg border border-line bg-surface-2 p-6">
          <h2 className="font-semibold">{t("landing.trustTitle")}</h2>
          <ul className="mt-3 space-y-2 text-sm">
            {["trust1", "trust2", "trust3"].map((k) => (
              <li key={k} className="flex gap-2">
                <span aria-hidden className="text-ok">✓</span>
                {t(`landing.${k}`)}
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-muted">{t("landing.disclaimer")}</p>
        </section>
      </main>
      <footer className="mx-auto max-w-6xl px-4 py-10 text-xs text-muted">
        {t("common.attribution")} · <Link href="/confidentialite" className="underline">{t("settings.policy")}</Link>
      </footer>
    </div>
  );
}
