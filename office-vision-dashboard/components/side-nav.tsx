"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "概览", icon: "◉" },
  { href: "/trends", label: "行为分析", icon: "▤" },
  { href: "/timeline", label: "事件时间轴", icon: "≣" },
  { href: "/status", label: "系统状态", icon: "⚙" },
  { href: "/logs", label: "客户端日志", icon: "≡" },
  { href: "/monitor", label: "实时监控", icon: "⌖" },
];

export function SideNav() {
  const pathname = usePathname();
  return (
    <nav className="w-52 shrink-0 border-r border-zinc-800 bg-zinc-900/60 p-4 flex flex-col gap-1">
      <div className="mb-4">
        <h1 className="text-sm font-bold tracking-wide text-zinc-100">Office Vision</h1>
        <p className="text-xs text-zinc-500">AI 行为分析平台</p>
      </div>
      {NAV_ITEMS.map((item) => {
        const active =
          item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-lg px-3 py-2 text-sm transition-colors ${
              active
                ? "bg-emerald-500/15 text-emerald-300"
                : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            }`}
          >
            <span className="mr-2">{item.icon}</span>
            {item.label}
          </Link>
        );
      })}
      <div className="mt-auto text-[11px] text-zinc-600">
        Agent → Server → Dashboard
      </div>
    </nav>
  );
}
