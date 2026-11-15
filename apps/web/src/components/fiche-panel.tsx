"use client";

import clsx from "clsx";
import { useState } from "react";

import { Badge, Button, Input } from "@/components/ui";
import { api, type Schemas, unwrap } from "@/lib/api";
import { fmtDateTime, t } from "@/lib/i18n";

type Field = Schemas["FieldOut"];
type Fiche = Schemas["FicheOut"];

function display(f: Field): string {
  const v = f.value;
  if (v === null || v === undefined) return t("fiche.notFound");
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return /^\d{4}-\d{2}-\d{2}T/.test(s) ? fmtDateTime(s) : s;
}

function StatusBadge({ f }: { f: Field }) {
  if (f.verified_status === "user_verified") return <Badge tone="ok">✓ {t("fiche.verified")}</Badge>;
  if (f.verified_status === "user_corrected") return <Badge tone="ok">✎ {t("fiche.corrected")}</Badge>;
  if (f.to_verify) return <Badge tone={f.critical ? "danger" : "warn"} title={f.verified_status === "quote_not_found" ? t("fiche.quoteNotFound") : t(`fiche.confidence.${f.confidence}`)}>⚠ {t("fiche.toVerify")}</Badge>;
  if (f.verified_status === "auto_ok") return <Badge tone="ok" title={t(`fiche.confidence.${f.confidence}`)}>✓ <span className="sr-only">{t("fiche.auto")}</span></Badge>;
  return null;
}

export function FichePanel({ fiche, dossierId, selected, onSelect, onChanged }: {
  fiche: Fiche; dossierId: string; selected?: string; onSelect: (f: Field) => void; onChanged: () => void;
}) {
  const [editing, setEditing] = useState<string>();
  const [value, setValue] = useState("");
  const byId = new Map(fiche.sections.flatMap((s) => s.fields).map((f) => [f.id, f]));

  const patch = async (f: Field, action: "verify" | "correct") => {
    unwrap(await api.PATCH("/dossiers/{dossier_id}/fiche/fields/{field_id}", {
      params: { path: { dossier_id: dossierId, field_id: f.id } }, body: { action, value: action === "correct" ? value : null },
    }));
    setEditing(undefined);
    onChanged();
  };

  return (
    <div className="space-y-6">
      {fiche.sections.map((s) => {
        const current = s.fields.filter((f) => !f.superseded_by_field_id);
        if (!current.length) return null;
        return (
          <section key={s.key} aria-labelledby={`sec-${s.key}`}>
            <h3 id={`sec-${s.key}`} className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{s.label}</h3>
            <ul className="divide-y divide-line rounded-md border border-line bg-surface">
              {current.map((f) => {
                const olds = s.fields.filter((o) => o.superseded_by_field_id === f.id);
                const isSel = selected === f.id;
                return (
                  <li key={f.id} className={clsx("density-pad px-3 py-2.5", isSel && "bg-brand-soft", f.to_verify && f.critical && "border-l-4 border-l-danger")}>
                    <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                      <span className="w-full text-xs text-muted sm:w-48 sm:shrink-0">{f.label}{f.critical && <span className="sr-only"> ({t("fiche.critical")})</span>}{f.critical && <span aria-hidden className="ml-1 text-danger">*</span>}</span>
                      <div className="min-w-0 flex-1">
                        {editing === f.id ? (
                          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void patch(f, "correct"); }}>
                            <label className="sr-only" htmlFor={`v-${f.id}`}>{f.label}</label>
                            <Input id={`v-${f.id}`} value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
                            <Button type="submit">{t("fiche.save")}</Button>
                            <Button type="button" variant="secondary" onClick={() => setEditing(undefined)}>{t("fiche.cancel")}</Button>
                          </form>
                        ) : (
                          <button className={clsx("text-left text-sm", f.value === null ? "italic text-muted" : "font-medium")} onClick={() => onSelect(f)} disabled={!f.page}
                            aria-label={f.page ? `${f.label} : ${display(f)}. ${t("fiche.source", { doc: f.document_name ?? "", page: f.page })}` : undefined}>
                            {display(f)}
                          </button>
                        )}
                        {olds.map((o) => (
                          <p key={o.id} className="mt-0.5 text-xs text-muted">
                            {t("fiche.previous")} : <del>{display(o)}</del>{" "}
                            {o.page && <button className="underline" onClick={() => onSelect(o)}>({t("fiche.source", { doc: o.document_name ?? "", page: o.page })})</button>}
                          </p>
                        ))}
                        {f.note && <p className="mt-0.5 text-xs text-muted">{f.note}</p>}
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <StatusBadge f={f} />
                        {f.page ? (
                          <button className="text-xs text-brand hover:underline" onClick={() => onSelect(f)}>{t("fiche.source", { doc: f.document_name ?? "", page: f.page })}</button>
                        ) : <span className="text-xs text-muted">{t("fiche.noSource")}</span>}
                      </div>
                    </div>
                    {f.to_verify && editing !== f.id && (
                      <div className="mt-1.5 flex gap-2">
                        {f.value !== null && <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => patch(f, "verify")}>{t("fiche.markVerified")}</Button>}
                        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => { setEditing(f.id); setValue(typeof f.value === "string" ? f.value : ""); }}>{t("fiche.correct")}</Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      <section aria-labelledby="sec-addenda">
        <h3 id="sec-addenda" className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t("fiche.addenda")}</h3>
        {fiche.addenda.length === 0 ? <p className="text-sm text-muted">{t("fiche.noAddenda")}</p> : fiche.addenda.map((a) => (
          <div key={a.document_id} className="mb-2 rounded-md border border-line bg-surface p-3 text-sm">
            <p className="font-medium">{t("fiche.addendumChanges", { n: a.addendum_number ?? "?" })} — {a.document_name}</p>
            <ul className="mt-1 space-y-1">
              {a.changes.map((c) => {
                const f = byId.get(String(c.field_id));
                const olds = (c.old as { value: unknown }[]) ?? [];
                return (
                  <li key={String(c.field_id)}>
                    {String(c.label)} : {olds.map((o, i) => <del key={i} className="mr-1 text-muted">{String(o.value)}</del>)}→ <strong>{String(c.new_value)}</strong>{" "}
                    {f && <button className="text-xs text-brand underline" onClick={() => onSelect(f)}>({a.document_name} p. {String(c.page)})</button>}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
