"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert, Button, Card, Input, Label, LinkButton, Select } from "@/components/ui";
import { api, type Schemas, unwrap } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useQuery } from "@/lib/use-query";

export default function Settings() {
  const me = useQuery(async () => unwrap(await api.GET("/me")));
  const [saved, setSaved] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const update = async (body: Schemas["MeUpdate"]) => {
    const r = unwrap(await api.PATCH("/me", { body }));
    me.setData(r);
    if (body.density) document.documentElement.setAttribute("data-density", body.density);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };
  const deleteAccount = async () => {
    await api.DELETE("/me");
    window.location.href = "/";
  };
  const u = me.data;
  if (!u) return <p>{t("common.loading")}</p>;
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <h1 className="text-2xl font-semibold">{t("settings.title")}</h1>
      {saved && <Alert tone="ok">{t("settings.saved")}</Alert>}
      <Card className="space-y-3 p-5">
        <h2 className="font-semibold">{t("settings.profile")}</h2>
        <LinkButton href="/accueil" variant="secondary">{t("settings.editProfile")}</LinkButton>
      </Card>
      <Card className="space-y-3 p-5">
        <h2 className="font-semibold">{t("settings.alerts")}</h2>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={u.instant_alerts} onChange={(e) => update({ instant_alerts: e.target.checked })} />{t("settings.instant")}</label>
        <div><Label htmlFor="th">{t("settings.threshold")}</Label><Input id="th" type="number" min={0} max={100} className="w-28" defaultValue={u.alert_threshold} onBlur={(e) => update({ alert_threshold: Number(e.target.value) })} /></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={u.weekly_digest} onChange={(e) => update({ weekly_digest: e.target.checked })} />{t("settings.digest")}</label>
      </Card>
      <Card className="space-y-3 p-5">
        <h2 className="font-semibold">{t("settings.display")}</h2>
        <div><Label htmlFor="den">{t("settings.density")}</Label>
          <Select id="den" className="w-48" value={u.density} onChange={(e) => update({ density: e.target.value as "comfortable" | "compact" })}>
            <option value="comfortable">{t("settings.comfortable")}</option><option value="compact">{t("settings.compact")}</option>
          </Select></div>
      </Card>
      <Card className="space-y-3 p-5">
        <h2 className="font-semibold">{t("settings.privacy")}</h2>
        <p className="text-sm text-muted">{t("settings.privacyText")}</p>
        <Link href="/confidentialite" className="text-sm text-brand hover:underline">{t("settings.policy")}</Link>
        <div className="border-t border-line pt-3">
          <Label htmlFor="del">{t("settings.deleteConfirm")}</Label>
          <div className="flex gap-2"><Input id="del" className="w-48" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
            <Button variant="danger" disabled={confirmText !== "SUPPRIMER"} onClick={deleteAccount}>{t("settings.deleteAccount")}</Button></div>
        </div>
      </Card>
    </div>
  );
}
