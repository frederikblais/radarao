"use client";

import { useState } from "react";

import { Badge, Button, Card, EmptyState, Input, Label, Select } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { fmtDate, fmtMoney, t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

type Entity = { name: string; contracts: number; amount?: number | null };
type Bucket = { min: number; max: number | null; count: number };
type Insights = Record<string, unknown> & {
  contracts: number; avg_tenderers?: number | null; amount_p25?: number | null; amount_median?: number | null; amount_p75?: number | null;
  period_start?: string | null; period_end?: string | null; top_buyers: Entity[]; top_suppliers: Entity[]; amount_histogram: Bucket[]; source: string; backend: string; summary?: string | null;
};

const bucketLabel = (b: Bucket) => (b.max ? `${fmtMoney(b.min)} – ${fmtMoney(b.max)}` : `≥ ${fmtMoney(b.min)}`);

/** Histogramme à une seule série : une teinte, barres fines, survol, et tableau équivalent. */
function Histogram({ buckets }: { buckets: Bucket[] }) {
  const [showTable, setShowTable] = useState(false);
  const max = Math.max(1, ...buckets.map((b) => b.count));
  return (
    <figure>
      <figcaption className="flex items-center justify-between text-sm font-semibold">
        {t("market.distribution")}
        <button className="text-xs font-normal text-brand hover:underline" onClick={() => setShowTable(!showTable)} aria-expanded={showTable}>
          {showTable ? "Graphique" : "Tableau"}
        </button>
      </figcaption>
      {showTable ? (
        <table className="mt-3 w-full text-sm">
          <thead><tr className="text-left text-muted"><th className="font-normal">Montant</th><th className="text-right font-normal">{t("market.contracts")}</th></tr></thead>
          <tbody>{buckets.map((b) => <tr key={b.min} className="border-t border-line"><td className="py-1">{bucketLabel(b)}</td><td className="text-right font-mono">{b.count}</td></tr>)}</tbody>
        </table>
      ) : (
        <div className="mt-3 flex h-40 items-end gap-0.5 border-b border-line" role="img" aria-label={buckets.map((b) => `${bucketLabel(b)} : ${b.count}`).join("; ")}>
          {buckets.map((b) => (
            <div key={b.min} className="group relative flex h-full flex-1 flex-col justify-end px-2">
              <div className="rounded-t bg-brand group-hover:bg-brand-hover" style={{ height: `${(b.count / max) * 100}%`, minHeight: b.count ? 2 : 0 }} />
              <span className="pointer-events-none absolute -top-1 left-1/2 hidden -translate-x-1/2 -translate-y-full whitespace-nowrap rounded border border-line bg-surface px-2 py-1 text-xs text-ink shadow group-hover:block">
                {bucketLabel(b)} · {b.count}
              </span>
            </div>
          ))}
        </div>
      )}
      {!showTable && (
        <div className="mt-1 flex gap-0.5 text-[10px] text-muted">{buckets.map((b) => <span key={b.min} className="flex-1 text-center">{b.max ? `< ${Intl.NumberFormat("fr-CA", { notation: "compact" }).format(b.max)}` : "+"}</span>)}</div>
      )}
    </figure>
  );
}

function Ranking({ title, rows }: { title: string; rows: Entity[] }) {
  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      <ol className="mt-2 space-y-1 text-sm">
        {rows.map((r, i) => (
          <li key={r.name} className="flex gap-2"><span className="w-4 text-muted">{i + 1}.</span><span className="flex-1">{r.name}</span><span className="font-mono text-xs text-muted">{r.contracts}</span></li>
        ))}
      </ol>
    </Card>
  );
}

export default function Market() {
  const [unspsc, setUnspsc] = useState("");
  const [region, setRegion] = useState("");
  const [args, setArgs] = useState<{ unspsc?: string; region?: string; summarize?: boolean }>({});
  const regions = useQuery(() => fetch("/api/regions").then((r) => r.json() as Promise<{ code: string; name: string }[]>));
  const ins = useQuery(async () => unwrap(await api.GET("/market/insights", { params: { query: args } })) as Insights, [JSON.stringify(args)]);
  const renewals = useQuery(async () => unwrap(await api.GET("/market/renewals", { params: { query: { limit: 30 } } })) as { items: Record<string, string | number>[]; note: string });
  const d = ins.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("market.title")}</h1>
        <p className="text-sm text-muted">{t("market.lead")}</p>
      </div>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); setArgs({ unspsc: unspsc || undefined, region: region || undefined }); }}>
        <div><Label htmlFor="mu">{t("market.unspsc")}</Label><Input id="mu" inputMode="numeric" pattern="\d{2,8}" value={unspsc} onChange={(e) => setUnspsc(e.target.value)} /></div>
        <div><Label htmlFor="mr">{t("market.region")}</Label>
          <Select id="mr" value={region} onChange={(e) => setRegion(e.target.value)}><option value="">{t("feed.all")}</option>{(regions.data ?? []).map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}</Select></div>
        <Button type="submit">{t("market.show")}</Button>
      </form>

      {d && (d.contracts === 0 ? <EmptyState title={t("market.noData")} /> : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              [t("market.contracts"), String(d.contracts)],
              [t("market.avgTenderers"), d.avg_tenderers?.toFixed(1) ?? "—"],
              [t("market.median"), fmtMoney(d.amount_median)],
              [t("market.range"), `${fmtMoney(d.amount_p25)} – ${fmtMoney(d.amount_p75)}`],
            ].map(([k, v]) => <Card key={k} className="p-4"><p className="text-xs text-muted">{k}</p><p className="mt-1 font-mono text-xl font-semibold">{v}</p></Card>)}
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="p-4 lg:col-span-1">{d.amount_histogram?.length ? <Histogram buckets={d.amount_histogram} /> : <p className="text-sm text-muted">—</p>}</Card>
            <Ranking title={t("market.buyers")} rows={d.top_buyers ?? []} />
            <Ranking title={t("market.suppliers")} rows={d.top_suppliers ?? []} />
          </div>
          <p className="text-xs text-muted">
            <Badge tone="brand" className="mr-2">{t(`market.backend.${d.backend}`)}</Badge>
            {t("market.source", { s: d.source })} · {t("market.period", { a: fmtDate(d.period_start), b: fmtDate(d.period_end) })}
          </p>
          <div>
            {d.summary ? <Card className="p-4 text-sm"><h2 className="font-semibold">{t("market.summary")}</h2><p className="mt-1">{d.summary}</p></Card> :
              <Button variant="secondary" onClick={() => setArgs({ ...args, summarize: true })}>{t("market.summarize")}</Button>}
          </div>
        </div>
      ))}

      <section aria-labelledby="ren">
        <h2 id="ren" className="text-lg font-semibold">{t("market.renewals")}</h2>
        <p className="text-xs text-muted">{renewals.data?.note ?? t("market.renewalsNote")}</p>
        <ul className="mt-3 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {(renewals.data?.items ?? []).map((r) => (
            <li key={`${r.buyer_party_id}-${r.unspsc_prefix}`}>
              <Card className="space-y-1 p-4 text-sm">
                <p className="font-medium">{r.buyer_name}</p>
                <p className="text-xs text-muted"><span className="font-mono">{r.unspsc_prefix}</span> {r.unspsc_label} {r.region_name ? `· ${r.region_name}` : ""}</p>
                <p>{t("market.predicted", { d: fmtDate(String(r.predicted_date)), w: r.window_days })}</p>
                <p className="text-xs text-muted">{t("market.cycle", { n: Math.round(Number(r.median_interval_days) / 30), k: r.occurrences })}</p>
                {r.last_supplier && <p className="text-xs text-muted">{t("market.lastSupplier", { s: String(r.last_supplier) })} · {fmtMoney(Number(r.last_amount))}</p>}
                <Badge tone={r.confidence === "high" ? "ok" : r.confidence === "medium" ? "brand" : "neutral"}>{t(`market.confidence.${r.confidence}`)}</Badge>
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
