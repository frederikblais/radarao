"use client";

import { Badge } from "@/components/ui";
import { fmtDateTime, t } from "@/lib/i18n";

/** Le temps est l'information la plus importante (section 7.1) : rouge sous 72 heures. */
export function Countdown({ date }: { date?: string | null }) {
  if (!date) return <Badge>{t("countdown.unknown")}</Badge>;
  const ms = new Date(date).getTime() - Date.now();
  const hours = Math.floor(ms / 3_600_000);
  const days = Math.floor(hours / 24);
  let label: string;
  if (ms <= 0) label = t("countdown.past");
  else if (hours < 24) label = t("countdown.hours", { n: Math.max(1, hours) });
  else label = days === 1 ? t("countdown.day") : t("countdown.days", { n: days });
  const tone = ms <= 0 ? "neutral" : hours < 72 ? "danger" : days <= 7 ? "warn" : "neutral";
  return (
    <Badge tone={tone} title={fmtDateTime(date)}>
      <span aria-hidden>⏱</span> {label}
    </Badge>
  );
}
