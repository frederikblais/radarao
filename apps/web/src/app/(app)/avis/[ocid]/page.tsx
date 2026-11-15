"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { Countdown } from "@/components/countdown";
import { Score } from "@/components/score";
import { Alert, Badge, Button, Card, LinkButton } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtMoney, t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

export default function TenderPage() {
  const { ocid } = useParams<{ ocid: string }>();
  const id = decodeURIComponent(ocid);
  const router = useRouter();
  const { data: d, error } = useQuery(async () => unwrap(await api.GET("/tenders/{ocid}", { params: { path: { ocid: id } } })), [id]);

  const openDossier = async () => {
    if (d?.dossier_id) return router.push(`/dossiers/${d.dossier_id}`);
    const r = unwrap(await api.POST("/dossiers", { body: { ocid: id } }));
    router.push(`/dossiers/${r.id}`);
  };

  if (error) return <Alert tone="danger" role="alert">{error}</Alert>;
  if (!d) return <p>{t("common.loading")}</p>;
  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <Link href="/opportunites" className="text-sm text-brand hover:underline">← {t("tender.back")}</Link>
      <div className="flex items-start gap-4">
        <Score value={d.score} />
        <div className="flex-1">
          <h1 className="text-2xl font-semibold">{d.title}</h1>
          <p className="mt-1 text-muted">{d.buyer_name} {d.tender_id && <span className="ml-2 font-mono text-sm">{d.tender_id}</span>}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2"><Countdown date={d.end_date} />{d.source === "manual" && <Badge tone="brand">{t("tender.manual")}</Badge>}</div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-[1fr_320px]">
        <Card className="p-5">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <div><dt className="text-muted">{t("tender.deadline")}</dt><dd className="font-medium">{fmtDateTime(d.end_date)}</dd></div>
            <div><dt className="text-muted">{t("tender.published")}</dt><dd>{fmtDate(d.start_date)}</dd></div>
            <div><dt className="text-muted">{t("tender.category")}</dt><dd>{d.main_category ? t(`categories.${d.main_category}`) : "—"}</dd></div>
            <div><dt className="text-muted">{t("tender.method")}</dt><dd>{d.procurement_method_details ?? d.procurement_method ?? "—"}</dd></div>
            <div><dt className="text-muted">{t("tender.region")}</dt><dd title={t("tender.regionApprox")}>{d.region_name ?? "—"}</dd></div>
            <div><dt className="text-muted">{t("tender.value")}</dt><dd className="font-mono">{fmtMoney(d.value_amount)}</dd></div>
          </dl>
          {d.summary_fr && <p className="mt-4 text-sm">{d.summary_fr}</p>}
          <h2 className="mt-5 text-sm font-semibold">{t("tender.unspsc")}</h2>
          <ul className="mt-1 space-y-1 text-sm">
            {d.items_unspsc.map((i) => <li key={String(i.code)}><span className="font-mono text-xs">{String(i.code)}</span> {String(i.label ?? "")}</li>)}
          </ul>
          <h2 className="mt-5 text-sm font-semibold">{t("tender.history")}</h2>
          <ol className="mt-1 space-y-0.5 text-xs text-muted">
            {d.history.map((h) => <li key={String(h.release_id)}>{(h.tags as string[]).join(", ")} · <span className="font-mono">{String(h.release_id)}</span></li>)}
          </ol>
        </Card>
        <div className="space-y-4">
          <Card className="p-4">
            <h2 className="text-sm font-semibold">{t("tender.reasons")}</h2>
            <ul className="mt-2 space-y-1 text-sm">{d.reasons?.map((r) => <li key={r} className="flex gap-2"><span aria-hidden className="text-ok">✓</span>{r}</li>)}</ul>
            {(d.blockers?.length ?? 0) > 0 && (<>
              <h2 className="mt-3 text-sm font-semibold">{t("tender.blockers")}</h2>
              <ul className="mt-2 space-y-1 text-sm">{d.blockers?.map((b) => <li key={b} className="flex gap-2 text-warn"><span aria-hidden>⚠</span>{b}</li>)}</ul>
            </>)}
          </Card>
          <Card className="space-y-3 p-4">
            <Button className="w-full" onClick={openDossier}>{d.dossier_id ? t("tender.openDossier") : t("tender.upload")}</Button>
            <p className="text-xs text-muted">{t("tender.uploadHelp")}</p>
            {d.seao_url && <LinkButton href={d.seao_url} external variant="secondary" className="w-full">{t("feed.viewSeao")}</LinkButton>}
          </Card>
        </div>
      </div>
    </div>
  );
}
