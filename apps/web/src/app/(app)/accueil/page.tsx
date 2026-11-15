"use client";

import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, Badge, Button, Card, Input, Label, Textarea } from "@/components/ui";
import { api, detail, type Schemas } from "@/lib/api";
import { t } from "@/lib/i18n";

type Profile = Schemas["ProfileIn"];
type Unspsc = Schemas["UnspscOut"];
const CATS = ["works", "services", "goods"] as const;

const empty: Profile = {
  name: "", neq: null, size: null, description: "", categories: [], unspsc: [], regions: [], postal_code: null, radius_km: null,
  value_min: null, value_max: null,
  qualifications: { rbq: { held: false, subcategories: [] }, amp: false, revenu_quebec: false, iso: [], insurance_amount: null, bonding_capacity: null },
  buyer_preferences: { favorites: [], excluded: [] }, onboarding_completed: true,
};

const num = (v: string) => (v === "" ? null : Number(v));

export default function Onboarding() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [p, setP] = useState<Profile>(empty);
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [regions, setRegions] = useState<{ code: string; name: string }[]>([]);
  const [suggestions, setSuggestions] = useState<Unspsc[]>([]);
  const [refused, setRefused] = useState<string[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Unspsc[]>([]);
  const [error, setError] = useState<string>();

  useEffect(() => {
    void fetch("/api/regions").then((r) => r.json()).then(setRegions);
    void api.GET("/me").then(async (r) => {
      const cid = r.data?.company_id;
      if (!cid) return;
      setCompanyId(cid);
      const prof = await api.GET("/companies/{company_id}/profile", { params: { path: { company_id: cid } } });
      if (prof.data) setP({ ...empty, ...prof.data });
    });
  }, []);

  useEffect(() => {
    if (q.length < 2) return setResults([]);
    const h = setTimeout(() => void api.GET("/unspsc", { params: { query: { q } } }).then((r) => setResults(r.data ?? [])), 250);
    return () => clearTimeout(h);
  }, [q]);

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setP((x) => ({ ...x, [k]: v }));
  const setQ2 = (patch: Partial<Profile["qualifications"]>) => setP((x) => ({ ...x, qualifications: { ...x.qualifications, ...patch } }));
  const codes = p.unspsc ?? [];
  const addCode = (u: Unspsc, source: "user" | "suggested") => {
    if (codes.some((c) => c.code === u.code)) return;
    set("unspsc", [...codes, { code: u.code, label: u.label, source, accepted: true }]);
  };

  const suggest = async () => {
    setSuggesting(true);
    setError(undefined);
    let cid = companyId;
    if (!cid) {
      // Un profil minimal est créé pour pouvoir demander des suggestions (non terminé).
      const r = await api.POST("/companies", { body: { ...p, name: p.name || "Mon entreprise", onboarding_completed: false } });
      if (!r.data) {
        setSuggesting(false);
        return setError(detail(r.error));
      }
      cid = r.data.id;
      setCompanyId(cid);
    }
    const r = await api.POST("/companies/{company_id}/unspsc/suggest", { params: { path: { company_id: cid } }, body: { description: p.description ?? "" } });
    setSuggesting(false);
    if (r.data) setSuggestions(r.data);
    else setError(detail(r.error));
  };

  const save = async () => {
    setError(undefined);
    const body = { ...p, onboarding_completed: true };
    const r = companyId
      ? await api.PUT("/companies/{company_id}/profile", { params: { path: { company_id: companyId } }, body })
      : await api.POST("/companies", { body });
    if (r.error) return setError(detail(r.error));
    router.push("/opportunites");
  };

  const canNext = step === 1 ? p.name.trim().length > 0 && (p.categories?.length ?? 0) > 0 : true;
  const rbq = p.qualifications?.rbq ?? { held: false, subcategories: [] };

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-semibold">{t("onboarding.title")}</h1>
      <ol className="mt-4 flex gap-2" aria-label={t("onboarding.step", { n: step })}>
        {[1, 2, 3, 4].map((n) => (
          <li key={n} className={clsx("flex-1 rounded border-t-4 pt-2 text-xs", n <= step ? "border-brand text-brand" : "border-line text-muted")} aria-current={n === step ? "step" : undefined}>
            {t(`onboarding.s${n}`)}
          </li>
        ))}
      </ol>
      <Card className="mt-6 space-y-5 p-6">
        {step === 1 && (
          <>
            <div>
              <Label htmlFor="name">{t("onboarding.name")}</Label>
              <Input id="name" required value={p.name} onChange={(e) => set("name", e.target.value)} />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <Label htmlFor="neq" hint={t("onboarding.neqHelp")}>{t("onboarding.neq")}</Label>
                <Input id="neq" inputMode="numeric" pattern="\d{10}" value={p.neq ?? ""} onChange={(e) => set("neq", e.target.value || null)} />
              </div>
              <div>
                <Label htmlFor="size">{t("onboarding.size")}</Label>
                <Input id="size" type="number" min={1} value={p.size ?? ""} onChange={(e) => set("size", num(e.target.value))} />
              </div>
            </div>
            <fieldset>
              <legend className="mb-2 text-sm font-medium">{t("onboarding.categories")}</legend>
              <div className="flex flex-wrap gap-3">
                {CATS.map((c) => (
                  <label key={c} className="flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm">
                    <input type="checkbox" checked={p.categories?.includes(c)} onChange={(e) => set("categories", e.target.checked ? [...(p.categories ?? []), c] : (p.categories ?? []).filter((x) => x !== c))} />
                    {t(`categories.${c}`)}
                  </label>
                ))}
              </div>
            </fieldset>
          </>
        )}
        {step === 2 && (
          <>
            <div>
              <Label htmlFor="desc">{t("onboarding.description")}</Label>
              <Textarea id="desc" rows={4} placeholder={t("onboarding.descriptionPlaceholder")} value={p.description ?? ""} onChange={(e) => set("description", e.target.value)} />
              <Button variant="secondary" className="mt-2" onClick={suggest} disabled={suggesting || (p.description ?? "").length < 10}>
                {suggesting ? t("onboarding.suggesting") : t("onboarding.suggest")}
              </Button>
            </div>
            {suggestions.length > 0 && (
              <div>
                <p className="text-xs text-muted">{t("onboarding.suggestHelp")}</p>
                <ul className="mt-2 divide-y divide-line rounded-md border border-line">
                  {suggestions.filter((s) => !refused.includes(s.code)).map((s) => {
                    const on = codes.some((c) => c.code === s.code);
                    return (
                      <li key={s.code} className="flex items-center gap-3 px-3 py-2 text-sm">
                        <span className="font-mono text-xs">{s.code}</span>
                        <span className="flex-1">
                          {s.label}
                          {s.reason && <span className="block text-xs text-muted">{s.reason}</span>}
                        </span>
                        {on ? <Badge tone="ok">{t("onboarding.accepted")}</Badge> : (
                          <>
                            <Button variant="secondary" onClick={() => addCode(s, "suggested")}>{t("onboarding.accept")}</Button>
                            <Button variant="ghost" onClick={() => setRefused([...refused, s.code])}>{t("onboarding.refuse")}</Button>
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
            <div>
              <Label htmlFor="q">{t("onboarding.searchUnspsc")}</Label>
              <Input id="q" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
              {results.length > 0 && (
                <ul className="mt-1 max-h-56 overflow-auto rounded-md border border-line bg-surface text-sm" role="listbox">
                  {results.map((r) => (
                    <li key={r.code}>
                      <button className="flex w-full gap-3 px-3 py-1.5 text-left hover:bg-surface-2" onClick={() => { addCode(r, "user"); setQ(""); }}>
                        <span className="font-mono text-xs">{r.code}</span>{r.label}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <p className="mb-1 text-sm font-medium">{t("onboarding.selectedCodes")}</p>
              <div className="flex flex-wrap gap-2">
                {codes.map((c) => (
                  <span key={c.code} className="inline-flex items-center gap-1 rounded bg-brand-soft px-2 py-1 text-xs text-brand">
                    <span className="font-mono">{c.code}</span> {c.label}
                    <button aria-label={`Retirer ${c.code}`} onClick={() => set("unspsc", codes.filter((x) => x.code !== c.code))}>×</button>
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <fieldset>
              <legend className="mb-2 text-sm font-medium">{t("onboarding.regions")}</legend>
              <div className="grid grid-cols-1 gap-1 sm:grid-cols-2 md:grid-cols-3">
                {regions.map((r) => (
                  <label key={r.code} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={p.regions?.includes(r.code)} onChange={(e) => set("regions", e.target.checked ? [...(p.regions ?? []), r.code] : (p.regions ?? []).filter((x) => x !== r.code))} />
                    <span className="font-mono text-xs text-muted">{r.code}</span> {r.name}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-4 md:grid-cols-2">
              <div><Label htmlFor="pc">{t("onboarding.postal")}</Label><Input id="pc" value={p.postal_code ?? ""} onChange={(e) => set("postal_code", e.target.value || null)} /></div>
              <div><Label htmlFor="rad">{t("onboarding.radius")}</Label><Input id="rad" type="number" min={0} value={p.radius_km ?? ""} onChange={(e) => set("radius_km", num(e.target.value))} /></div>
              <div><Label htmlFor="vmin">{t("onboarding.valueMin")}</Label><Input id="vmin" type="number" min={0} value={p.value_min ?? ""} onChange={(e) => set("value_min", num(e.target.value))} /></div>
              <div><Label htmlFor="vmax">{t("onboarding.valueMax")}</Label><Input id="vmax" type="number" min={0} value={p.value_max ?? ""} onChange={(e) => set("value_max", num(e.target.value))} /></div>
            </div>
          </>
        )}
        {step === 4 && (
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rbq.held} onChange={(e) => setQ2({ rbq: { ...rbq, held: e.target.checked } })} />{t("onboarding.rbq")}</label>
            {rbq.held && (
              <div className="ml-6"><Label htmlFor="rbqs">{t("onboarding.rbqSub")}</Label>
                <Input id="rbqs" value={(rbq.subcategories ?? []).join(", ")} onChange={(e) => setQ2({ rbq: { ...rbq, subcategories: e.target.value.split(/[,\s]+/).filter(Boolean) } })} /></div>
            )}
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={p.qualifications?.amp} onChange={(e) => setQ2({ amp: e.target.checked })} />{t("onboarding.amp")}</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={p.qualifications?.revenu_quebec} onChange={(e) => setQ2({ revenu_quebec: e.target.checked })} />{t("onboarding.rq")}</label>
            <div className="grid gap-4 md:grid-cols-3">
              <div><Label htmlFor="iso">{t("onboarding.iso")}</Label><Input id="iso" value={(p.qualifications?.iso ?? []).join(", ")} onChange={(e) => setQ2({ iso: e.target.value.split(/[,\s]+/).filter(Boolean) })} /></div>
              <div><Label htmlFor="ins">{t("onboarding.insurance")}</Label><Input id="ins" type="number" min={0} value={p.qualifications?.insurance_amount ?? ""} onChange={(e) => setQ2({ insurance_amount: num(e.target.value) })} /></div>
              <div><Label htmlFor="bond">{t("onboarding.bonding")}</Label><Input id="bond" type="number" min={0} value={p.qualifications?.bonding_capacity ?? ""} onChange={(e) => setQ2({ bonding_capacity: num(e.target.value) })} /></div>
            </div>
          </div>
        )}
        {error && <Alert tone="danger" role="alert">{error}</Alert>}
        <div className="flex justify-between border-t border-line pt-4">
          <Button variant="secondary" onClick={() => setStep(step - 1)} disabled={step === 1}>{t("onboarding.back")}</Button>
          {step < 4 ? (
            <Button onClick={() => setStep(step + 1)} disabled={!canNext}>{t("onboarding.next")}</Button>
          ) : (
            <Button onClick={save}>{t("onboarding.finish")}</Button>
          )}
        </div>
      </Card>
    </div>
  );
}
