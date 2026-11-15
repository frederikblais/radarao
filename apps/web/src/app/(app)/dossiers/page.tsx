"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Countdown } from "@/components/countdown";
import { Badge, Button, Card, EmptyState, Input, Label } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { fmtDate, t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

export default function Dossiers() {
  const router = useRouter();
  const { data, loading } = useQuery(async () => unwrap(await api.GET("/dossiers")));
  const [title, setTitle] = useState("");
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const d = unwrap(await api.POST("/dossiers", { body: { title } }));
    router.push(`/dossiers/${d.id}`);
  };
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold">{t("dossiers.title")}</h1>
      <form onSubmit={create} className="flex flex-wrap items-end gap-2">
        <div className="min-w-64 flex-1"><Label htmlFor="nt">{t("dossiers.newTitle")}</Label><Input id="nt" required value={title} onChange={(e) => setTitle(e.target.value)} /></div>
        <Button type="submit">{t("dossiers.new")}</Button>
      </form>
      {!loading && !data?.length && <EmptyState title={t("dossiers.empty")}><p>{t("dossiers.emptyHelp")}</p></EmptyState>}
      <ul className="grid gap-3 md:grid-cols-2">
        {data?.map((d) => (
          <li key={d.id}>
            <Card className="p-4">
              <div className="flex items-start justify-between gap-2">
                <Link href={`/dossiers/${d.id}`} className="font-medium hover:underline">{d.title}</Link>
                <Countdown date={d.end_date} />
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                <Badge tone={d.status === "ready" ? "ok" : d.status === "failed" ? "danger" : d.status === "partial" ? "warn" : "brand"}>{t(`dossiers.status.${d.status}`)}</Badge>
                <Badge>{t("dossiers.documents", { n: d.documents.length })}</Badge>
                {d.fields_to_verify > 0 && <Badge tone="warn">{t("dossiers.toVerify", { n: d.fields_to_verify })}</Badge>}
              </div>
              {d.delete_after && <p className="mt-2 text-xs text-muted">{t("dossiers.deleteAfter", { date: fmtDate(d.delete_after) })}</p>}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
