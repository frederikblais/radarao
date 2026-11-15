"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Countdown } from "@/components/countdown";
import { Score } from "@/components/score";
import { Alert, Badge, Button, Card, EmptyState, Input, Label, LinkButton, Select } from "@/components/ui";
import { api, detail, type Schemas, unwrap } from "@/lib/api";
import { fmtDate, t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

type Card = Schemas["TenderCard"];
type Filters = { category: string; region: string; buyer: string; deadline_before: string; min_score: number; follow: string };
const DEFAULTS: Filters = { category: "", region: "", buyer: "", deadline_before: "", min_score: 0, follow: "" };

function query(f: Filters, cursor?: string | null) {
  const q: Record<string, string | number> = { min_score: f.min_score };
  for (const k of ["category", "region", "buyer", "follow"] as const) if (f[k]) q[k] = f[k];
  if (f.deadline_before) q.deadline_before = new Date(`${f.deadline_before}T23:59:59`).toISOString();
  if (cursor) q.cursor = cursor;
  return q;
}

export default function Feed() {
  const [f, setF] = useState<Filters>(DEFAULTS);
  const [items, setItems] = useState<Card[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [fresh, setFresh] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [manual, setManual] = useState(false);
  const [buyerQ, setBuyerQ] = useState("");
  const [buyers, setBuyers] = useState<{ id: string; name: string }[]>([]);
  const regions = useQuery(() => fetch("/api/regions").then((r) => r.json() as Promise<{ code: string; name: string }[]>));
  const renewals = useQuery(async () => unwrap(await api.GET("/market/renewals", { params: { query: { limit: 5 } } })) as { items: Record<string, string | number>[] });

  const load = async (append = false) => {
    setLoading(true);
    const r = await api.GET("/tenders", { params: { query: query(f, append ? cursor : null) as never } });
    const d = unwrap(r);
    setItems(append ? [...items, ...d.items] : d.items);
    setCursor(d.next_cursor ?? null);
    setTotal(d.total);
    setFresh(d.freshness ?? null);
    setLoading(false);
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void load(), [f]);
  useEffect(() => {
    if (buyerQ.length < 2) return setBuyers([]);
    const h = setTimeout(() => void api.GET("/buyers", { params: { query: { q: buyerQ } } }).then((r) => setBuyers((r.data ?? []) as { id: string; name: string }[])), 250);
    return () => clearTimeout(h);
  }, [buyerQ]);

  const patch = (ocid: string, c: Card) => setItems((xs) => xs.map((x) => (x.ocid === ocid ? { ...x, ...c, score: x.score, reasons: x.reasons } : x)));
  const feedback = async (c: Card, fb: "relevant" | "not_relevant" | null) => {
    const r = await api.POST("/tenders/{ocid}/feedback", { params: { path: { ocid: c.ocid } }, body: { feedback: fb } });
    if (!r.data) return;
    if (fb === "not_relevant" && !f.follow) setItems((xs) => xs.filter((x) => x.ocid !== c.ocid));
    else patch(c.ocid, r.data);
  };
  const track = async (c: Card) => {
    const r = await api.POST("/tenders/{ocid}/track", { params: { path: { ocid: c.ocid } }, body: { tracked: !c.tracked } });
    if (r.data) patch(c.ocid, r.data);
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h1 className="text-2xl font-semibold">{t("feed.title")}</h1>
          <span className="text-sm text-muted">{t("feed.results", { n: total })}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <Badge tone={fresh ? "brand" : "warn"} title={t("feed.freshnessNote")}>{fresh ? t("feed.freshness", { date: fmtDate(fresh) }) : t("feed.freshnessNote")}</Badge>
          <Button variant="ghost" onClick={() => setManual(true)}>{t("feed.addManual")}</Button>
        </div>
        {manual && <ManualForm onClose={() => setManual(false)} onAdded={() => { setManual(false); void load(); }} />}

        <section aria-label={t("feed.filters")} className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-6">
          <div><Label htmlFor="fc">{t("feed.category")}</Label>
            <Select id="fc" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
              <option value="">{t("feed.all")}</option>
              {["works", "services", "goods"].map((c) => <option key={c} value={c}>{t(`categories.${c}`)}</option>)}
            </Select></div>
          <div><Label htmlFor="fr">{t("feed.region")}</Label>
            <Select id="fr" value={f.region} onChange={(e) => setF({ ...f, region: e.target.value })}>
              <option value="">{t("feed.all")}</option>
              {(regions.data ?? []).map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
            </Select></div>
          <div className="relative"><Label htmlFor="fb">{t("feed.buyer")}</Label>
            <Input id="fb" value={buyerQ} onChange={(e) => { setBuyerQ(e.target.value); if (!e.target.value) setF({ ...f, buyer: "" }); }} autoComplete="off" />
            {buyers.length > 0 && (
              <ul className="absolute z-10 mt-1 max-h-48 w-72 overflow-auto rounded-md border border-line bg-surface text-sm shadow">
                {buyers.map((b) => <li key={b.id}><button className="w-full px-3 py-1.5 text-left hover:bg-surface-2" onClick={() => { setF({ ...f, buyer: b.id }); setBuyerQ(b.name); setBuyers([]); }}>{b.name}</button></li>)}
              </ul>
            )}</div>
          <div><Label htmlFor="fd">{t("feed.deadline")}</Label><Input id="fd" type="date" value={f.deadline_before} onChange={(e) => setF({ ...f, deadline_before: e.target.value })} /></div>
          <div><Label htmlFor="fs">{t("feed.minScore")}</Label>
            <Select id="fs" value={f.min_score} onChange={(e) => setF({ ...f, min_score: Number(e.target.value) })}>
              {[0, 40, 60, 70, 80, 90].map((s) => <option key={s} value={s}>≥ {s}</option>)}
            </Select></div>
          <div><Label htmlFor="ff">{t("feed.follow")}</Label>
            <Select id="ff" value={f.follow} onChange={(e) => setF({ ...f, follow: e.target.value })}>
              <option value="">{t("feed.followAll")}</option><option value="tracked">{t("feed.followTracked")}</option>
              <option value="relevant">{t("feed.followRelevant")}</option><option value="new">{t("feed.followNew")}</option>
              <option value="not_relevant">{t("feed.followNotRelevant")}</option>
            </Select></div>
        </section>

        <ul className="mt-5 space-y-3" aria-busy={loading}>
          {items.map((c) => (
            <li key={c.ocid}>
              <Card className="density-pad flex gap-4 p-4">
                <Score value={c.score} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <Link href={`/avis/${encodeURIComponent(c.ocid)}`} className="font-medium hover:underline">{c.title}</Link>
                    <Countdown date={c.end_date} />
                  </div>
                  <p className="mt-0.5 text-sm text-muted">
                    {[c.buyer_name, c.main_category && t(`categories.${c.main_category}`), c.region_name].filter(Boolean).join(" · ")}
                    {c.tender_id && <span className="ml-2 font-mono text-xs">{c.tender_id}</span>}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {c.reasons?.map((r) => <Badge key={r} tone="ok"><span aria-hidden>✓</span>{r}</Badge>)}
                    {c.blockers?.map((b) => <Badge key={b} tone="warn"><span aria-hidden>⚠</span>{b}</Badge>)}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button variant={c.tracked ? "primary" : "secondary"} onClick={() => track(c)} aria-pressed={!!c.tracked}>{c.tracked ? t("feed.tracked") : t("feed.track")}</Button>
                    <Button variant="secondary" onClick={() => feedback(c, c.feedback === "relevant" ? null : "relevant")} aria-pressed={c.feedback === "relevant"}>{t("feed.relevant")}</Button>
                    <Button variant="ghost" onClick={() => feedback(c, c.feedback === "not_relevant" ? null : "not_relevant")} aria-pressed={c.feedback === "not_relevant"}>{t("feed.notForUs")}</Button>
                    {c.seao_url && <LinkButton href={c.seao_url} external variant="ghost">{t("feed.viewSeao")}</LinkButton>}
                  </div>
                </div>
              </Card>
            </li>
          ))}
        </ul>
        {!loading && items.length === 0 && (
          <div className="mt-6"><EmptyState title={t("feed.empty")}><p>{t("feed.emptyHelp")}</p><div className="mt-3"><LinkButton href="/accueil" variant="secondary">{t("feed.editProfile")}</LinkButton></div></EmptyState></div>
        )}
        {cursor && <div className="mt-4 text-center"><Button variant="secondary" onClick={() => load(true)} disabled={loading}>{t("feed.loadMore")}</Button></div>}
      </div>

      <aside aria-labelledby="renew" className="space-y-3">
        <h2 id="renew" className="font-semibold">{t("feed.renewalsTitle")}</h2>
        <p className="text-xs text-muted">{t("feed.renewalsLead")}</p>
        {(renewals.data?.items ?? []).map((r) => (
          <Card key={`${r.buyer_party_id}-${r.unspsc_prefix}`} className="p-3 text-sm">
            <p className="font-medium">{r.buyer_name}</p>
            <p className="text-xs text-muted">{r.unspsc_label ?? r.unspsc_prefix}</p>
            <p className="mt-1 text-xs">{t("market.predicted", { d: fmtDate(String(r.predicted_date)), w: r.window_days })}</p>
            <Badge tone={r.confidence === "high" ? "ok" : r.confidence === "medium" ? "brand" : "neutral"} className="mt-1">{t(`market.confidence.${r.confidence}`)}</Badge>
          </Card>
        ))}
        {renewals.data && renewals.data.items.length === 0 && <p className="text-xs text-muted">{String((renewals.data as { note?: string }).note ?? "")}</p>}
        <Link href="/marche" className="text-sm text-brand hover:underline">{t("nav.market")} →</Link>
      </aside>
    </div>
  );
}

function ManualForm({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [v, setV] = useState({ tender_id: "", title: "", buyer_name: "", end_date: "", seao_url: "" });
  const [error, setError] = useState<string>();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const r = await api.POST("/tenders/manual", { body: { tender_id: v.tender_id, title: v.title, buyer_name: v.buyer_name || null, end_date: v.end_date ? new Date(v.end_date).toISOString() : null, seao_url: v.seao_url || null } });
    if (r.error) setError(detail(r.error));
    else onAdded();
  };
  return (
    <Card className="mt-3 p-4">
      <form onSubmit={submit} className="space-y-3" aria-labelledby="mt">
        <h2 id="mt" className="font-semibold">{t("manual.title")}</h2>
        <p className="text-xs text-muted">{t("manual.help")}</p>
        <div className="grid gap-3 md:grid-cols-2">
          <div><Label htmlFor="mn">{t("manual.number")}</Label><Input id="mn" required value={v.tender_id} onChange={(e) => setV({ ...v, tender_id: e.target.value })} /></div>
          <div><Label htmlFor="mtt">{t("manual.titleField")}</Label><Input id="mtt" required minLength={3} value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} /></div>
          <div><Label htmlFor="mb">{t("manual.buyer")}</Label><Input id="mb" value={v.buyer_name} onChange={(e) => setV({ ...v, buyer_name: e.target.value })} /></div>
          <div><Label htmlFor="md">{t("manual.deadline")}</Label><Input id="md" type="datetime-local" value={v.end_date} onChange={(e) => setV({ ...v, end_date: e.target.value })} /></div>
          <div className="md:col-span-2"><Label htmlFor="mu">{t("manual.url")}</Label><Input id="mu" type="url" pattern="https://.*" value={v.seao_url} onChange={(e) => setV({ ...v, seao_url: e.target.value })} /></div>
        </div>
        {error && <Alert tone="danger" role="alert">{error}</Alert>}
        <div className="flex gap-2"><Button type="submit">{t("manual.submit")}</Button><Button type="button" variant="secondary" onClick={onClose}>{t("manual.cancel")}</Button></div>
      </form>
    </Card>
  );
}
