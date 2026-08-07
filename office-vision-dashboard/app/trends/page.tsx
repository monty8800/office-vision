"use client";

import { useEffect, useState } from "react";
import { serverApi, type TrendDay } from "@/lib/server-api";
import { Card, EmptyState } from "@/components/ui";

export default function TrendsPage() {
  const [days, setDays] = useState<TrendDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const trend = await serverApi.smokingTrend(7);
        if (active) {
          setDays(trend.days);
          setError(null);
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    const timer = setInterval(load, 10000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const max = Math.max(1, ...(days ?? []).map((d) => d.count));

  return (
    <div className="p-6">
      <header className="mb-6">
        <h1 className="text-xl font-bold">趋势</h1>
        <p className="mt-1 text-sm text-zinc-500">近 7 天抽烟次数</p>
      </header>

      {error ? (
        <Card className="border-red-900/60">
          <p className="text-sm text-red-400">数据加载失败：{error}</p>
        </Card>
      ) : !days ? (
        <Card>
          <EmptyState text="加载中…" />
        </Card>
      ) : (
        <Card title="每日次数">
          <div className="flex h-56 items-end gap-3">
            {days.map((day) => (
              <div key={day.day} className="flex flex-1 flex-col items-center gap-2">
                <span className="text-xs tabular-nums text-zinc-400">
                  {day.count > 0 ? day.count : ""}
                </span>
                <div
                  className={`w-full rounded-t-md ${
                    day.count > 0 ? "bg-emerald-500/70" : "bg-zinc-800"
                  }`}
                  style={{ height: `${Math.max((day.count / max) * 100, 2)}%` }}
                />
                <span className="text-[11px] text-zinc-500">
                  {day.day.slice(5)}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
