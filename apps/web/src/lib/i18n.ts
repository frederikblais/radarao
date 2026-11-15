import fr from "@/messages/fr.json";

type Dict = { [k: string]: string | Dict };
const messages: Dict = fr as Dict;

/** t("feed.freshness", { date }) — les textes vivent dans src/messages/fr.json, jamais dans le code. */
export function t(key: string, vars?: Record<string, string | number>): string {
  let node: string | Dict | undefined = messages;
  for (const part of key.split(".")) node = typeof node === "object" ? node[part] : undefined;
  let out = typeof node === "string" ? node : key;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, String(v));
  return out;
}

const dateFmt = new Intl.DateTimeFormat("fr-CA", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("fr-CA", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "America/Toronto" });
const moneyFmt = new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });

export const fmtDate = (d?: string | null) => (d ? dateFmt.format(new Date(d.length === 10 ? `${d}T12:00:00` : d)) : "—");
export const fmtDateTime = (d?: string | null) => (d ? dateTimeFmt.format(new Date(d)) : "—");
export const fmtMoney = (n?: number | null) => (n === null || n === undefined ? "—" : moneyFmt.format(n));
