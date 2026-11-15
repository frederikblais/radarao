import clsx from "clsx";

import { t } from "@/lib/i18n";

export function Score({ value }: { value?: number | null }) {
  if (value === null || value === undefined) return null;
  const tone = value >= 80 ? "bg-ok-soft text-ok" : value >= 60 ? "bg-brand-soft text-brand" : "bg-surface-2 text-muted";
  return (
    <span className={clsx("inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full font-mono text-sm font-semibold", tone)} aria-label={`${t("tender.score")} : ${value} sur 100`}>
      {value}
    </span>
  );
}
