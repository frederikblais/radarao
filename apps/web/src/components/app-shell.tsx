"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

const NAV = [
  { href: "/opportunites", key: "nav.opportunities" },
  { href: "/dossiers", key: "nav.dossiers" },
  { href: "/marche", key: "nav.market" },
];

type Theme = "system" | "light" | "dark";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [email, setEmail] = useState<string>();
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    let stored: Theme = "system";
    try {
      stored = (localStorage.getItem("theme") as Theme) || "system";
    } catch {}
    setTheme(stored);
    applyTheme(stored);
    void api.GET("/me").then((r) => {
      if (r.response.status === 401) window.location.href = "/connexion";
      if (r.data) {
        setEmail(r.data.email);
        document.documentElement.setAttribute("data-density", r.data.density);
      }
    });
  }, []);

  const cycleTheme = () => {
    const next: Theme = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
    setTheme(next);
    applyTheme(next);
    try {
      localStorage.setItem("theme", next);
    } catch {}
  };

  const logout = async () => {
    await api.POST("/auth/logout");
    window.location.href = "/";
  };

  return (
    <div className="min-h-screen">
      <a href="#contenu" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        {t("app.skip")}
      </a>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link href="/opportunites" className="flex items-center gap-2 font-semibold text-brand">
            <span aria-hidden className="inline-block h-6 w-6 rounded-full border-4 border-brand" />
            {t("app.name")}
          </Link>
          <nav aria-label="Navigation principale" className="flex gap-1">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={path.startsWith(n.href) ? "page" : undefined}
                className={clsx("rounded-md px-3 py-1.5 text-sm", path.startsWith(n.href) ? "bg-brand-soft font-medium text-brand" : "text-muted hover:text-ink")}
              >
                {t(n.key)}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 text-sm">
            <button onClick={cycleTheme} className="rounded-md px-2 py-1.5 text-muted hover:text-ink" aria-label={`${t("nav.theme")} : ${t(theme === "system" ? "nav.themeSystem" : theme === "light" ? "nav.themeLight" : "nav.themeDark")}`}>
              {t(theme === "system" ? "nav.themeSystem" : theme === "light" ? "nav.themeLight" : "nav.themeDark")}
            </button>
            <Link href="/parametres" className="rounded-md px-2 py-1.5 text-muted hover:text-ink">
              {email ?? t("nav.settings")}
            </Link>
            <button onClick={logout} className="rounded-md px-2 py-1.5 text-muted hover:text-ink">
              {t("nav.logout")}
            </button>
          </div>
        </div>
      </header>
      <main id="contenu" className="mx-auto max-w-7xl px-4 py-6">
        {children}
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-muted">{t("common.attribution")}</footer>
    </div>
  );
}
