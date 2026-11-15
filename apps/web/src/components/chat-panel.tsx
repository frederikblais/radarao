"use client";

import { useEffect, useRef, useState } from "react";

import { Alert, Button, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type Citation = { document_id: string; alias?: string; page: number; cited_text: string; title?: string };
type Msg = { role: string; text: string; citations: Citation[] };

/** E8 — assistant (réponse en flux SSE, citations cliquables vers le PDF). */
export function ChatPanel({ dossierId, onCite, onClose, docName }: {
  dossierId: string; onCite: (docId: string, page: number, quote: string) => void; onClose: () => void; docName: (id: string) => string;
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [tool, setTool] = useState<string>();
  const [error, setError] = useState<string>();
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api.GET("/dossiers/{dossier_id}/chat", { params: { path: { dossier_id: dossierId } } }).then((r) => setMsgs((r.data ?? []) as unknown as Msg[]));
  }, [dossierId]);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [msgs, tool]);

  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    const question = q.trim();
    if (!question || busy) return;
    setQ("");
    setBusy(true);
    setError(undefined);
    setMsgs((m) => [...m, { role: "user", text: question, citations: [] }, { role: "assistant", text: "", citations: [] }]);
    const res = await fetch(`/api/dossiers/${dossierId}/chat`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json", Accept: "text/event-stream" }, body: JSON.stringify({ question }),
    });
    if (!res.ok || !res.body) {
      setBusy(false);
      setError(res.status === 429 ? "Limite atteinte pour cette heure." : t("common.error"));
      return;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split(/\r?\n\r?\n/);
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const data = part.split(/\r?\n/).filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("\n");
        if (!data) continue;
        const ev = JSON.parse(data) as { type: string; text?: string; name?: string; citations?: Citation[] };
        if (ev.type === "tool") setTool(ev.name);
        if (ev.type === "text" || ev.type === "error")
          setMsgs((m) => m.map((x, i) => (i === m.length - 1 ? { ...x, text: x.text + (ev.text ?? "") } : x)));
        if (ev.type === "done") setMsgs((m) => m.map((x, i) => (i === m.length - 1 ? { ...x, text: ev.text ?? x.text, citations: ev.citations ?? [] } : x)));
      }
    }
    setTool(undefined);
    setBusy(false);
  };

  return (
    <aside aria-labelledby="chat-title" className="flex h-full flex-col border-l border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line p-3">
        <h2 id="chat-title" className="font-semibold">{t("chat.title")}</h2>
        <Button variant="ghost" onClick={onClose} aria-label={t("chat.close")}>×</Button>
      </div>
      <div className="flex-1 space-y-3 overflow-auto p-3 text-sm" aria-live="polite">
        {msgs.length === 0 && <p className="text-muted">{t("chat.empty")}</p>}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "ml-8 rounded-lg bg-brand-soft p-2" : "mr-4"}>
            <p className="whitespace-pre-wrap">{m.text || (busy && i === msgs.length - 1 ? "…" : "")}</p>
            {m.citations.length > 0 && (
              <div className="mt-2">
                <p className="text-xs font-medium text-muted">{t("chat.sources")}</p>
                <ul className="mt-1 space-y-1">
                  {m.citations.map((c, j) => (
                    <li key={j}>
                      <button className="text-left text-xs text-brand hover:underline" onClick={() => onCite(c.document_id, c.page, c.cited_text)}>
                        [{j + 1}] {docName(c.document_id)}, p. {c.page} — « {c.cited_text.slice(0, 90)}{c.cited_text.length > 90 ? "…" : ""} »
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
        {tool && <p className="text-xs text-muted">{t(`chat.tool.${tool}`)}…</p>}
        {error && <Alert tone="danger" role="alert">{error}</Alert>}
        <div ref={end} />
      </div>
      <form onSubmit={ask} className="space-y-2 border-t border-line p-3">
        <label htmlFor="chat-q" className="sr-only">{t("chat.placeholder")}</label>
        <Textarea id="chat-q" rows={2} value={q} placeholder={t("chat.placeholder")} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(e); } }} />
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted">{t("chat.limits")}</p>
          <Button type="submit" disabled={busy || q.trim().length < 2}>{busy ? t("chat.thinking") : t("chat.send")}</Button>
        </div>
      </form>
    </aside>
  );
}
