"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import { ChatPanel } from "@/components/chat-panel";
import { Countdown } from "@/components/countdown";
import { FichePanel } from "@/components/fiche-panel";
import { Alert, Badge, Button, Card, LinkButton, Progress, Select } from "@/components/ui";
import { api, ApiError, detail, type Schemas, unwrap } from "@/lib/api";
import { fmtDate, t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

const PdfViewer = dynamic(() => import("@/components/pdf-viewer").then((m) => m.PdfViewer), { ssr: false });
type Field = Schemas["FieldOut"];
type Job = Schemas["JobOut"];
const STEPS = ["E0", "E1", "E2", "E3", "E4", "E5", "E6"];

export default function DossierPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const dossier = useQuery(async () => unwrap(await api.GET("/dossiers/{dossier_id}", { params: { path: { dossier_id: id } } })), [id],
    (d) => (d?.last_job && ["queued", "running"].includes(String((d.last_job as Job).status)) ? 2000 : null));
  const fiche = useQuery(async () => {
    try { return unwrap(await api.GET("/dossiers/{dossier_id}/fiche", { params: { path: { dossier_id: id } } })); } catch { return undefined; }
  }, [id, dossier.data?.status]);
  const [view, setView] = useState<{ docId: string | null; page: number; quote?: string | null; fieldId?: string }>({ docId: null, page: 1 });
  const [chat, setChat] = useState(false);
  const [consent, setConsent] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string>();
  const input = useRef<HTMLInputElement>(null);

  const d = dossier.data;
  const job = d?.last_job as Job | undefined;
  const docs = d?.documents ?? [];
  const activeDoc = view.docId ?? docs.find((x) => x.status !== "duplicate")?.id ?? null;
  const fileUrl = useCallback((docId: string) => `/api/dossiers/${id}/documents/${docId}/file`, [id]);
  const docName = (docId: string) => docs.find((x) => x.id === docId)?.filename ?? "document";

  const upload = async (files: FileList | File[]) => {
    if (!consent && !d?.documents.length) return setError(t("upload.consentRequired"));
    setUploading(true);
    setError(undefined);
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    form.append("consent", String(consent));
    const res = await fetch(`/api/dossiers/${id}/documents`, { method: "POST", body: form, credentials: "include" });
    setUploading(false);
    if (!res.ok) setError(detail(await res.json().catch(() => ({}))));
    void dossier.reload();
  };

  const analyze = async (retry = false) => {
    setError(undefined);
    try {
      unwrap(await api.POST("/dossiers/{dossier_id}/analyze", { params: { path: { dossier_id: id }, query: { retry_failed: retry } } }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("common.error"));
    }
    void dossier.reload();
  };

  const setKind = async (docId: string, kind: string, n?: number) => {
    await api.PATCH("/dossiers/{dossier_id}/documents/{document_id}", { params: { path: { dossier_id: id, document_id: docId } }, body: { kind: kind as never, addendum_number: n ?? null } });
    void dossier.reload();
  };

  const remove = async () => {
    if (!confirm(t("common.confirmDelete"))) return;
    await api.DELETE("/dossiers/{dossier_id}", { params: { path: { dossier_id: id } } });
    router.push("/dossiers");
  };

  if (dossier.error) return <Alert tone="danger" role="alert">{dossier.error}</Alert>;
  if (!d) return <p>{t("common.loading")}</p>;
  const running = job && ["queued", "running"].includes(job.status);
  const select = (f: Field) => f.document_id && f.page && setView({ docId: f.document_id, page: f.page, quote: f.citation, fieldId: f.id });

  return (
    <div className="-mx-4 -my-6 flex min-h-[calc(100vh-4rem)] flex-col lg:h-[calc(100vh-4rem)]">
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">{d.title}</h1>
          <p className="text-xs text-muted">
            {t(`dossiers.status.${d.status}`)}{d.fields_to_verify > 0 && ` · ${t("analysis.toVerify", { n: d.fields_to_verify })}`}
            {d.delete_after && ` · ${t("dossiers.deleteAfter", { date: fmtDate(d.delete_after) })}`}
          </p>
        </div>
        <Countdown date={d.end_date} />
        <Button variant="danger" onClick={remove}>{t("common.delete")}</Button>
      </div>
      <div className="grid flex-1 lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" style={chat ? { gridTemplateColumns: undefined } : undefined}>
        <div className="space-y-5 overflow-auto p-4">
          <Card className="space-y-3 p-4">
            <h2 className="font-semibold">{t("upload.title")}</h2>
            <ul className="space-y-1 text-sm">
              {docs.map((doc) => (
                <li key={doc.id} className="flex flex-wrap items-center gap-2">
                  <button className="text-left text-brand hover:underline" onClick={() => setView({ docId: doc.id, page: 1 })}>{doc.filename}</button>
                  <span className="text-xs text-muted">{doc.pages ? t("upload.pages", { n: doc.pages }) : ""}</span>
                  {doc.scanned_pages.length > 0 && <Badge>{t("upload.scanned", { n: doc.scanned_pages.length })}</Badge>}
                  {["encrypted", "unreadable", "duplicate"].includes(doc.status) && <Badge tone="danger">{t(`upload.${doc.status}`)}</Badge>}
                  <label className="sr-only" htmlFor={`k-${doc.id}`}>{t("upload.kind")}</label>
                  <Select id={`k-${doc.id}`} className="ml-auto w-auto py-1 text-xs" value={doc.kind} onChange={(e) => setKind(doc.id, e.target.value, e.target.value === "addendum" ? doc.addendum_number ?? 1 : undefined)}>
                    {["auto", "main", "devis", "form", "addendum", "other"].map((k) => <option key={k} value={k}>{t(`upload.kinds.${k}`)}</option>)}
                  </Select>
                  {doc.kind === "addendum" && (
                    <input aria-label={t("upload.addendumNo")} type="number" min={1} className="w-14 rounded border border-line bg-surface px-1 py-0.5 text-xs"
                      defaultValue={doc.addendum_number ?? 1} onBlur={(e) => setKind(doc.id, "addendum", Number(e.target.value))} />
                  )}
                </li>
              ))}
            </ul>
            <div onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); void upload(e.dataTransfer.files); }}
              className="rounded-md border-2 border-dashed border-line p-4 text-center text-sm text-muted">
              <p>{t("upload.drop")}</p>
              <Button variant="ghost" onClick={() => input.current?.click()} disabled={uploading}>{uploading ? t("upload.uploading") : t("upload.browse")}</Button>
              <input ref={input} type="file" accept="application/pdf" multiple className="sr-only" aria-label={t("upload.browse")} onChange={(e) => e.target.files && upload(e.target.files)} />
            </div>
            {!docs.length && (
              <label className="flex items-start gap-2 text-xs">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" />
                {t("upload.consent")}
              </label>
            )}
            {error && <Alert tone="danger" role="alert">{error}</Alert>}
            {docs.length > 0 && !running && (
              <Button onClick={() => analyze(false)}>{job ? t("upload.reanalyze") : t("upload.analyze")}</Button>
            )}
          </Card>

          {running && job && (
            <Card className="space-y-2 p-4" aria-live="polite">
              <p className="font-medium">{t("analysis.running")} · {job.step_label ?? t("analysis.steps.E0")}</p>
              <Progress value={job.progress} label={t("analysis.running")} />
              <ol className="flex flex-wrap gap-1.5 text-xs">
                {STEPS.map((s) => <li key={s}><Badge tone={job.completed_steps.includes(s) ? "ok" : job.step === s ? "brand" : "neutral"}>{t(`analysis.steps.${s}`)}</Badge></li>)}
              </ol>
            </Card>
          )}
          {job?.status === "partial" && (
            <Alert>{t("analysis.partial")} {job.failed_sections.length > 0 && t("analysis.missing", { s: job.failed_sections.join(", ") })}{" "}
              <Button variant="ghost" onClick={() => analyze(true)}>{t("analysis.retry")}</Button></Alert>
          )}
          {job?.status === "failed" && (
            <Alert tone="danger" role="alert">{job.failure_kind === "budget" ? t("analysis.budget") : `${t("analysis.failed")} ${job.error ?? ""}`}{" "}
              {job.failure_kind !== "budget" && <Button variant="ghost" onClick={() => analyze(false)}>{t("analysis.resume")}</Button>}</Alert>
          )}
          {job?.problems?.map((p) => <Alert key={p}>{p}</Alert>)}

          {fiche.data && fiche.data.sections.some((s) => s.fields.length) ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-semibold">{t("fiche.title")}</h2>
                {fiche.data.to_verify > 0 && <Badge tone="warn">{t("analysis.toVerify", { n: fiche.data.to_verify })}</Badge>}
              </div>
              <p className="text-xs text-muted">{t("fiche.disclaimer")}</p>
              <FichePanel fiche={fiche.data} dossierId={id} selected={view.fieldId} onSelect={select} onChanged={() => { void fiche.reload(); void dossier.reload(); }} />
            </>
          ) : (!running && <p className="text-sm text-muted">{t("analysis.notStarted")}</p>)}
        </div>

        <div className={chat ? "grid min-h-[60vh] grid-cols-1 border-t border-line lg:min-h-0 lg:grid-cols-[1fr_360px] lg:border-l lg:border-t-0" : "min-h-[60vh] border-t border-line lg:min-h-0 lg:border-l lg:border-t-0"}>
          <PdfViewer docs={docs.filter((x) => x.status === "ready" || x.status === "uploaded")} docId={activeDoc} page={view.page} quote={view.quote}
            fileUrl={fileUrl} onChange={(docId, page) => setView({ docId, page, quote: docId === view.docId ? view.quote : null, fieldId: view.fieldId })} />
          {chat && <ChatPanel dossierId={id} docName={docName} onClose={() => setChat(false)} onCite={(docId, page, quote) => setView({ docId, page, quote })} />}
        </div>
      </div>
      <nav aria-label="Actions du dossier" className="no-print flex flex-wrap gap-2 border-t border-line bg-surface px-4 py-3">
        <LinkButton href={`/dossiers/${id}/liste`} variant="secondary">{t("fiche.checklist")}</LinkButton>
        <LinkButton href={`/dossiers/${id}/go-no-go`} variant="secondary">{t("fiche.goNoGo")}</LinkButton>
        <Button variant={chat ? "primary" : "secondary"} onClick={() => setChat(!chat)} aria-expanded={chat}>💬 {t("fiche.ask")}</Button>
        {d.ocid && <Link href={`/avis/${encodeURIComponent(d.ocid)}`} className="ml-auto self-center text-sm text-brand hover:underline">{t("fiche.viewTender")}</Link>}
      </nav>
    </div>
  );
}
