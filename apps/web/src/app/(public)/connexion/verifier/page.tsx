"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

function Verify() {
  const params = useSearchParams();
  const router = useRouter();
  const [failed, setFailed] = useState(false);
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const token = params.get("token");
    if (!token) return setFailed(true);
    void api.POST("/auth/verify", { body: { token } }).then((r) => {
      if (!r.data) return setFailed(true);
      router.replace(r.data.has_company ? "/opportunites" : "/accueil");
    });
  }, [params, router]);

  return (
    <main id="contenu" className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      {failed ? (
        <div className="space-y-3">
          <Alert tone="danger" role="alert">{t("login.invalid")}</Alert>
          <Link href="/connexion" className="text-sm text-brand underline">{t("login.retry")}</Link>
        </div>
      ) : (
        <p aria-live="polite">{t("login.verifying")}</p>
      )}
    </main>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}
