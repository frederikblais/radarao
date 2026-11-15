"use client";

import { Alert, Card } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

type Metrics = {
  cost_per_dossier: { dossiers: number; avg_usd: number | null; max_usd: number | null }; quote_not_found_rate: number;
  steps: { step: string; model: string; calls: number; avg_latency_ms: number; cost_usd: number; cache_hit_ratio: number | null; errors: number }[];
  fields: { key: string; count: number; quote_not_found: number; user_corrected: number; correction_rate: number }[];
};

/** Tableau de bord interne (section 11.4) — réservé au rôle admin. */
export default function Admin() {
  const m = useQuery(async () => unwrap(await api.GET("/admin/metrics", { params: { query: { days: 30 } } })) as Metrics);
  if (m.error) return <Alert tone="danger">{m.error}</Alert>;
  if (!m.data) return <p>{t("common.loading")}</p>;
  const d = m.data;
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold">Observabilité (30 jours)</h1>
      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="p-4"><p className="text-xs text-muted">Coût moyen par dossier</p><p className="font-mono text-xl">{d.cost_per_dossier.avg_usd ?? "—"} $ US</p></Card>
        <Card className="p-4"><p className="text-xs text-muted">Dossiers analysés</p><p className="font-mono text-xl">{d.cost_per_dossier.dossiers}</p></Card>
        <Card className="p-4"><p className="text-xs text-muted">Taux de citations introuvables</p><p className="font-mono text-xl">{(d.quote_not_found_rate * 100).toFixed(1)} %</p></Card>
      </div>
      <Card className="overflow-x-auto p-4">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted">{["Étape", "Modèle", "Appels", "Latence moy.", "Coût", "Cache", "Erreurs"].map((h) => <th key={h} className="pb-2 font-normal">{h}</th>)}</tr></thead>
          <tbody>{d.steps.map((s) => (
            <tr key={s.step + s.model} className="border-t border-line font-mono text-xs"><td className="py-1">{s.step}</td><td>{s.model}</td><td>{s.calls}</td><td>{s.avg_latency_ms} ms</td><td>{s.cost_usd} $</td><td>{s.cache_hit_ratio !== null ? `${(s.cache_hit_ratio * 100).toFixed(0)} %` : "—"}</td><td>{s.errors}</td></tr>
          ))}</tbody>
        </table>
      </Card>
      <Card className="overflow-x-auto p-4">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted">{["Champ", "Extraits", "Citation introuvable", "Corrigés", "Taux de correction"].map((h) => <th key={h} className="pb-2 font-normal">{h}</th>)}</tr></thead>
          <tbody>{d.fields.map((f) => (
            <tr key={f.key} className="border-t border-line text-xs"><td className="py-1 font-mono">{f.key}</td><td>{f.count}</td><td>{f.quote_not_found}</td><td>{f.user_corrected}</td><td>{(f.correction_rate * 100).toFixed(0)} %</td></tr>
          ))}</tbody>
        </table>
      </Card>
    </div>
  );
}
