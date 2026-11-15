"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Alert, Badge, Card, EmptyState } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { fmtDate, fmtMoney, t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

type Point = { texte: string; field_id: string; document_name?: string | null; page?: number | null };

function Points({ title, items, tone }: { title: string; items: Point[]; tone: "ok" | "warn" | "danger" }) {
  return (
    <Card className="p-4">
      <h2 className="font-semibold">{title}</h2>
      {items.length === 0 ? <p className="mt-2 text-sm text-muted">—</p> : (
        <ul className="mt-2 space-y-2 text-sm">
          {items.map((p, i) => (
            <li key={i} className="flex gap-2">
              <Badge tone={tone} className="h-fit">{tone === "ok" ? "+" : tone === "warn" ? "!" : "⛔"}</Badge>
              <span>{p.texte}{p.page && <span className="ml-1 text-xs text-muted">({p.document_name} p. {p.page})</span>}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function GoNoGo() {
  const { id } = useParams<{ id: string }>();
  const g = useQuery(async () => {
    try { return unwrap(await api.GET("/dossiers/{dossier_id}/go-no-go", { params: { path: { dossier_id: id } } })); } catch { return null; }
  }, [id]);
  if (g.loading) return <p>{t("common.loading")}</p>;
  if (!g.data) return <EmptyState title={t("gonogo.none")} />;
  const d = g.data;
  const b = d.benchmarks as Record<string, number | string | null> | null | undefined;
  const tone = d.recommendation === "go" ? "ok" : d.recommendation === "no_go" ? "danger" : "warn";
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <Link href={`/dossiers/${id}`} className="text-sm text-brand hover:underline">← {t("fiche.title")}</Link>
      <h1 className="text-2xl font-semibold">{t("gonogo.title")}</h1>
      <Card className="flex flex-wrap items-center gap-4 p-5">
        <Badge tone={tone} className="px-3 py-1.5 text-lg">{t(`gonogo.rec.${d.recommendation}`)}</Badge>
        <span className="text-sm">{t("gonogo.effort")} : <strong>{t(`gonogo.efforts.${d.effort}`)}</strong></span>
      </Card>
      {d.warning && <Alert tone="danger" role="alert">{d.warning}</Alert>}
      <p className="whitespace-pre-line text-sm">{d.summary}</p>
      <div className="grid gap-4 md:grid-cols-3">
        <Points title={t("gonogo.strengths")} items={d.strengths as Point[]} tone="ok" />
        <Points title={t("gonogo.risks")} items={d.risks as Point[]} tone="warn" />
        <Points title={t("gonogo.blockers")} items={d.blockers as Point[]} tone="danger" />
      </div>
      {b && (
        <Card className="p-4 text-sm">
          <h2 className="font-semibold">{t("gonogo.benchmarks")}</h2>
          <dl className="mt-2 grid grid-cols-3 gap-2">
            <div><dt className="text-muted">{t("gonogo.p25")}</dt><dd className="font-mono">{fmtMoney(b.amount_p25 as number)}</dd></div>
            <div><dt className="text-muted">{t("gonogo.median")}</dt><dd className="font-mono font-semibold">{fmtMoney(b.amount_median as number)}</dd></div>
            <div><dt className="text-muted">{t("gonogo.p75")}</dt><dd className="font-mono">{fmtMoney(b.amount_p75 as number)}</dd></div>
          </dl>
          <p className="mt-2 text-xs text-muted">
            {t("gonogo.contracts", { n: String(b.contracts) })}{b.avg_tenderers ? ` · ${t("gonogo.avgTenderers", { n: String(b.avg_tenderers) })}` : ""} ·{" "}
            {t("market.period", { a: fmtDate(b.period_start as string), b: fmtDate(b.period_end as string) })} · {String(b.source)}
          </p>
        </Card>
      )}
      <p className="text-xs text-muted">{t("gonogo.reminder")}</p>
    </div>
  );
}
