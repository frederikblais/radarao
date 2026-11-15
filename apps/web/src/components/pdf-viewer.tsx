"use client";

import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

import { Button, Select } from "@/components/ui";
import { t } from "@/lib/i18n";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export type ViewerDoc = { id: string; filename: string };
type TextItem = { str: string };

const norm = (s: string) =>
  s.normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[’‘`´]/g, "'").replace(/[«»“”]/g, '"').replace(/\s+/g, " ").toLowerCase().trim();

/** Indices des éléments de texte de la page qui couvrent la citation (exacte, sinon par les premiers mots). */
function itemsToHighlight(items: TextItem[], quote: string): Set<number> {
  const out = new Set<number>();
  if (!quote) return out;
  let joined = "";
  const starts: number[] = [];
  items.forEach((it) => {
    starts.push(joined.length);
    joined += norm(it.str) + " ";
  });
  const q = norm(quote);
  let at = joined.indexOf(q);
  let len = q.length;
  if (at < 0) {
    const head = q.split(" ").slice(0, 6).join(" ");
    at = head.length > 8 ? joined.indexOf(head) : -1;
    len = q.length;
  }
  if (at < 0) return out;
  const end = at + len;
  starts.forEach((s, i) => {
    const e = s + norm(items[i].str).length;
    if (e > at && s < end) out.add(i);
  });
  return out;
}

export function PdfViewer({ docs, docId, page, quote, fileUrl, onChange }: {
  docs: ViewerDoc[]; docId: string | null; page: number; quote?: string | null;
  fileUrl: (docId: string) => string; onChange: (docId: string, page: number) => void;
}) {
  const [numPages, setNumPages] = useState(0);
  const [marks, setMarks] = useState<Set<number>>(new Set());
  const [width, setWidth] = useState(600);
  const [failed, setFailed] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.max(280, el.clientWidth - 2)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => setFailed(false), [docId]);
  const file = useMemo(() => (docId ? fileUrl(docId) : null), [docId, fileUrl]);
  const onText = useCallback(
    async (p: { getTextContent: () => Promise<{ items: unknown[] }> }) => {
      const content = await p.getTextContent();
      setMarks(itemsToHighlight(content.items.filter((x): x is TextItem => typeof (x as TextItem).str === "string"), quote ?? ""));
    },
    [quote],
  );
  const renderer = useCallback(
    ({ str, itemIndex }: { str: string; itemIndex: number }) => (marks.has(itemIndex) ? `<mark>${str.replace(/</g, "&lt;")}</mark>` : str.replace(/</g, "&lt;")),
    [marks],
  );

  if (!docId) return <p className="p-4 text-sm text-muted">{t("pdf.document")} —</p>;
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-2">
        <label className="sr-only" htmlFor="pdf-doc">{t("pdf.document")}</label>
        <Select id="pdf-doc" className="w-auto max-w-[16rem]" value={docId} onChange={(e) => onChange(e.target.value, 1)}>
          {docs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
        </Select>
        <div className="ml-auto flex items-center gap-1 text-sm">
          <Button variant="ghost" aria-label={t("pdf.prev")} disabled={page <= 1} onClick={() => onChange(docId, page - 1)}>‹</Button>
          <span aria-live="polite">{t("pdf.page", { page, total: numPages || "…" })}</span>
          <Button variant="ghost" aria-label={t("pdf.next")} disabled={!!numPages && page >= numPages} onClick={() => onChange(docId, page + 1)}>›</Button>
        </div>
      </div>
      <div ref={box} className="flex-1 overflow-auto bg-surface-2 p-2">
        {failed ? (
          <p className="p-4 text-sm text-danger">{t("pdf.error")}</p>
        ) : (
          <Document file={file} loading={<p className="p-4 text-sm">{t("pdf.loading")}</p>} onLoadSuccess={({ numPages: n }) => setNumPages(n)} onLoadError={() => setFailed(true)}>
            <Page pageNumber={Math.min(page, numPages || page)} width={width} onLoadSuccess={onText} customTextRenderer={renderer} />
          </Document>
        )}
        {quote && marks.size > 0 && <p className="sr-only" aria-live="polite">{t("pdf.highlight")} : {quote}</p>}
      </div>
    </div>
  );
}
