import type { ReactNode } from "react";

export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 ${className}`}
    >
      {title ? (
        <h2 className="mb-3 text-sm font-semibold text-zinc-300">{title}</h2>
      ) : null}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-lg bg-zinc-800/60 px-4 py-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-zinc-600">{hint}</p> : null}
    </div>
  );
}

export function Badge({
  tone = "zinc",
  children,
}: {
  tone?: "green" | "amber" | "red" | "zinc" | "blue";
  children: ReactNode;
}) {
  const tones: Record<string, string> = {
    green: "bg-emerald-500/15 text-emerald-300",
    amber: "bg-amber-500/15 text-amber-300",
    red: "bg-red-500/15 text-red-300",
    zinc: "bg-zinc-700/40 text-zinc-300",
    blue: "bg-sky-500/15 text-sky-300",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-full min-h-24 items-center justify-center text-sm text-zinc-600">
      {text}
    </div>
  );
}

export function presenceTone(state: string): "green" | "amber" | "red" | "zinc" | "blue" {
  switch (state) {
    case "working":
      return "green";
    case "away":
      return "amber";
    case "sleeping":
      return "blue";
    default:
      return "zinc";
  }
}

export const PRESENCE_LABELS: Record<string, string> = {
  working: "在岗",
  away: "离开",
  sleeping: "休眠",
  waiting: "等待",
};
