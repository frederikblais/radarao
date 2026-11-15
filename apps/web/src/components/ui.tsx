import clsx from "clsx";
import Link from "next/link";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary: "bg-brand text-on-brand hover:bg-brand-hover",
  secondary: "border border-line bg-surface text-ink hover:bg-surface-2",
  ghost: "text-brand hover:bg-brand-soft",
  danger: "border border-danger/40 text-danger hover:bg-danger-soft",
};

export function Button({ variant = "primary", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={clsx("inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50", variants[variant], className)}
      {...props}
    />
  );
}

export function LinkButton({ href, variant = "primary", className, children, external }: { href: string; variant?: Variant; className?: string; children: ReactNode; external?: boolean }) {
  const cls = clsx("inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium", variants[variant], className);
  if (external)
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>
        {children}
        <span aria-hidden>↗</span>
        <span className="sr-only"> (nouvel onglet)</span>
      </a>
    );
  return (
    <Link href={href} className={cls}>
      {children}
    </Link>
  );
}

export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx("rounded-lg border border-line bg-surface", className)} {...rest}>
      {children}
    </div>
  );
}

type Tone = "neutral" | "ok" | "warn" | "danger" | "brand";
const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted",
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
  brand: "bg-brand-soft text-brand",
};

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={clsx("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Label({ htmlFor, children, hint }: { htmlFor: string; children: ReactNode; hint?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-sm font-medium">
      {children}
      {hint && <span className="mt-0.5 block text-xs font-normal text-muted">{hint}</span>}
    </label>
  );
}

const inputCls = "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={clsx(inputCls, p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={clsx(inputCls, p.className)} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={clsx(inputCls, "pr-8", p.className)} />;

export function Alert({ tone = "warn", children, role = "status" }: { tone?: Tone; children: ReactNode; role?: string }) {
  return (
    <div role={role} className={clsx("rounded-md px-3 py-2 text-sm", tones[tone])}>
      {children}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line p-8 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-2 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Progress({ value, label }: { value: number; label: string }) {
  return (
    <div role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100} aria-label={label} className="h-2 w-full overflow-hidden rounded bg-surface-2">
      <div className="h-full bg-brand transition-[width]" style={{ width: `${value}%` }} />
    </div>
  );
}
