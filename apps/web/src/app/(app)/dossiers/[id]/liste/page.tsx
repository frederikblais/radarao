"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Badge, Button, Card, EmptyState, Input, Label, LinkButton } from "@/components/ui";
import { api, type Schemas, unwrap } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

type Item = Schemas["ChecklistItemOut"];

export default function Checklist() {
  const { id } = useParams<{ id: string }>();
  const p = { params: { path: { dossier_id: id } } };
  const { data, setData } = useQuery(async () => unwrap(await api.GET("/dossiers/{dossier_id}/checklist", p)), [id]);
  const dossier = useQuery(async () => unwrap(await api.GET("/dossiers/{dossier_id}", p)), [id]);
  const [label, setLabel] = useState("");
  const [editing, setEditing] = useState<string>();
  const items = data ?? [];
  const names = new Map((dossier.data?.documents ?? []).map((d) => [d.id, d.filename]));

  const update = async (i: Item, body: Partial<Item>) => {
    const r = unwrap(await api.PATCH("/dossiers/{dossier_id}/checklist/{item_id}", { params: { path: { dossier_id: id, item_id: i.id } }, body }));
    setData(items.map((x) => (x.id === i.id ? r : x)));
  };
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const r = unwrap(await api.POST("/dossiers/{dossier_id}/checklist", { ...p, body: { label, blocking: false } }));
    setData([...items, r]);
    setLabel("");
  };
  const remove = async (i: Item) => {
    await api.DELETE("/dossiers/{dossier_id}/checklist/{item_id}", { params: { path: { dossier_id: id, item_id: i.id } } });
    setData(items.filter((x) => x.id !== i.id));
  };
  const done = items.filter((i) => i.done).length;

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <Link href={`/dossiers/${id}`} className="no-print text-sm text-brand hover:underline">← {dossier.data?.title}</Link>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">{t("checklist.title")}</h1>
          <p className="text-sm text-muted">{dossier.data?.title} · {t("checklist.progress", { done, total: items.length })}</p>
        </div>
        <div className="no-print flex gap-2">
          <LinkButton href={`/api/dossiers/${id}/checklist.pdf`} variant="secondary" external>{t("checklist.export")}</LinkButton>
          <Button variant="secondary" onClick={() => window.print()}>{t("checklist.print")}</Button>
        </div>
      </div>
      {!items.length && <EmptyState title={t("checklist.empty")} />}
      <ul className="space-y-2">
        {items.map((i) => (
          <li key={i.id}>
            <Card className={`density-pad flex flex-wrap items-start gap-3 p-3 ${i.blocking ? "border-danger/50" : ""}`}>
              <input type="checkbox" className="mt-1 h-4 w-4" checked={i.done} onChange={(e) => update(i, { done: e.target.checked })} aria-label={i.label} />
              <div className="min-w-0 flex-1">
                {editing === i.id ? (
                  <form onSubmit={(e) => { e.preventDefault(); const v = new FormData(e.currentTarget); void update(i, { label: String(v.get("label")) }); setEditing(undefined); }} className="flex gap-2">
                    <Input name="label" defaultValue={i.label} aria-label={t("checklist.edit")} autoFocus />
                    <Button type="submit">{t("common.save")}</Button>
                  </form>
                ) : (
                  <p className={i.done ? "text-muted line-through" : "font-medium"}>{i.label}</p>
                )}
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                  {i.blocking && <Badge tone="danger">⛔ {t("checklist.blocking")}</Badge>}
                  {i.blocking_reason && <span className="text-danger">{i.blocking_reason}</span>}
                  {i.source_page && i.source_document_id && (
                    <Link className="text-brand hover:underline" href={`/dossiers/${id}`}>{t("checklist.source")} : {names.get(i.source_document_id)} p. {i.source_page}</Link>
                  )}
                </div>
                <div className="no-print mt-2 flex flex-wrap gap-2 text-xs">
                  <label className="flex items-center gap-1">{t("checklist.assignee")}
                    <input className="w-36 rounded border border-line bg-surface px-1 py-0.5" defaultValue={i.assignee ?? ""} onBlur={(e) => e.target.value !== (i.assignee ?? "") && update(i, { assignee: e.target.value || null })} /></label>
                  <label className="flex items-center gap-1">{t("checklist.due")}
                    <input type="date" className="rounded border border-line bg-surface px-1 py-0.5" defaultValue={i.due_date ?? ""} onChange={(e) => update(i, { due_date: e.target.value || null })} /></label>
                  <button className="text-brand hover:underline" onClick={() => setEditing(i.id)}>{t("checklist.edit")}</button>
                  <button className="text-danger hover:underline" onClick={() => remove(i)}>{t("checklist.delete")}</button>
                </div>
                <p className="hidden text-xs print:block">{[i.assignee && `${t("checklist.assignee")} : ${i.assignee}`, i.due_date && `${t("checklist.due")} : ${i.due_date}`].filter(Boolean).join(" · ")}</p>
              </div>
            </Card>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="no-print flex items-end gap-2">
        <div className="flex-1"><Label htmlFor="nl">{t("checklist.newLabel")}</Label><Input id="nl" required value={label} onChange={(e) => setLabel(e.target.value)} /></div>
        <Button type="submit">{t("checklist.add")}</Button>
      </form>
    </div>
  );
}
