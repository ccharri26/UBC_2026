// Small shared building blocks. Text from the API is rendered as React children
// (escaped); nothing here uses dangerouslySetInnerHTML.

import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export { cx };

export function Card({
  title,
  subtitle,
  action,
  children,
  className,
  flush,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean; // no inner padding (for tables that run edge to edge)
}) {
  return (
    <section className={cx("rounded-2xl border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 px-5 pt-5 pb-3">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-ink-3">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={flush ? "" : cx("px-5 pb-5", !(title || action) && "pt-5")}>{children}</div>
    </section>
  );
}

export type Tone = "neutral" | "gain" | "loss" | "caution" | "accent";

const toneClass: Record<Tone, string> = {
  neutral: "bg-subtle text-ink-2",
  gain: "bg-gain-soft text-gain",
  loss: "bg-loss-soft text-loss",
  caution: "bg-caution-soft text-caution",
  accent: "bg-accent-soft text-accent",
};

export function Badge({ tone = "neutral", children, dot }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
        toneClass[tone],
      )}
    >
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  hint,
  valueClass,
  children,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  valueClass?: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="text-sm text-ink-3">{label}</div>
      <div className={cx("tabular mt-2 text-3xl font-semibold tracking-tight", valueClass)}>{value}</div>
      {hint && <div className="mt-1 text-sm text-ink-3">{hint}</div>}
      {children}
    </div>
  );
}

export function Meter({ value, warnAt = 0.8 }: { value: number; warnAt?: number }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-subtle">
      <div
        className={cx("h-full rounded-full transition-[width] duration-500", v >= warnAt ? "bg-loss" : "bg-accent")}
        style={{ width: `${v * 100}%` }}
      />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3">{children}</div>;
}

export function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5 text-sm">
      <span className="text-ink-2">{label}</span>
      <span className="tabular text-right">{children}</span>
    </div>
  );
}

// --- tables ------------------------------------------------------------------

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  );
}

export function Th({ children, num, className }: { children?: ReactNode; num?: boolean; className?: string }) {
  return (
    <th
      className={cx(
        "border-y border-line bg-subtle/60 px-4 py-2 text-xs font-medium whitespace-nowrap text-ink-3 first:pl-5 last:pr-5",
        num ? "text-right" : "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  num,
  className,
  colSpan,
}: {
  children?: ReactNode;
  num?: boolean;
  className?: string;
  colSpan?: number;
}) {
  return (
    <td
      colSpan={colSpan}
      className={cx(
        "border-b border-line px-4 py-3 whitespace-nowrap first:pl-5 last:pr-5",
        num && "tabular text-right",
        className,
      )}
    >
      {children}
    </td>
  );
}

// --- modal -------------------------------------------------------------------

export function Modal({
  open,
  onClose,
  children,
  locked,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  locked?: boolean; // Escape and backdrop clicks don't close it: the user must press a button
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => locked && e.preventDefault()}
      onClick={(e) => !locked && e.target === ref.current && onClose()}
      className="m-auto w-[min(440px,calc(100vw-32px))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-2xl backdrop:bg-black/40 backdrop:backdrop-blur-sm"
    >
      <div className="p-6">{children}</div>
    </dialog>
  );
}

export function Button({
  variant = "secondary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const styles = {
    primary: "bg-ink text-canvas hover:opacity-90",
    secondary: "border border-line bg-surface text-ink hover:bg-subtle",
    danger: "bg-loss text-white hover:opacity-90",
  }[variant];
  return (
    <button
      {...props}
      className={cx(
        "inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        styles,
        className,
      )}
    />
  );
}
