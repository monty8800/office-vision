"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BEHAVIORS,
  formatDuration,
  formatRelative,
  serverApi,
  type BehaviorSession,
  type BehaviorSummary,
  type HourBucket,
  type TrendDay,
} from "@/lib/server-api";
import { Card, EmptyState, Stat } from "@/components/ui";

interface AnalysisData {
  summary: BehaviorSummary;
  sessions: BehaviorSession[];
  trend: TrendDay[];
  hourly: HourBucket[];
}

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function localDayStr(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// 记录分组标题：今天/昨天/MM-DD + 星期
function dayLabel(day: string): string {
  const wd = WEEKDAYS[new Date(`${day}T00:00:00`).getDay()];
  const todayStr = localDayStr(new Date());
  const yesterdayStr = localDayStr(new Date(Date.now() - 86_400_000));
  if (day === todayStr) return `今天 · ${wd}`;
  if (day === yesterdayStr) return `昨天 · ${wd}`;
  return `${day.slice(5)} · ${wd}`;
}

function isWeekend(day: string): boolean {
  const wd = new Date(`${day}T00:00:00`).getDay();
  return wd === 0 || wd === 6;
}

function formatHm(iso: string): string {
  return new Date(iso).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function AnalysisPage() {
  const [behavior, setBehavior] = useState(BEHAVIORS[0].key);
  const [days, setDays] = useState<7 | 30>(7);
  const [data, setData] = useState<AnalysisData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const meta = BEHAVIORS.find((b) => b.key === behavior) ?? BEHAVIORS[0];

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [summary, sessions, trend, hourly] = await Promise.all([
          serverApi.behaviorToday(behavior),
          serverApi.behaviorSessions(behavior, 50),
          serverApi.behaviorTrend(behavior, days),
          serverApi.behaviorHourly(behavior),
        ]);
        if (active) {
          setData({ summary, sessions: sessions.items, trend: trend.days, hourly: hourly.hours });
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
  }, [behavior, days]);

  // 节奏派生指标：平均间隔（相邻两次开始时间差的均值）
  const avgInterval = useMemo(() => {
    const sessions = data?.sessions ?? [];
    if (sessions.length < 2) return null;
    let total = 0;
    for (let i = 0; i < sessions.length - 1; i++) {
      total += new Date(sessions[i].start_time).getTime() - new Date(sessions[i + 1].start_time).getTime();
    }
    return total / (sessions.length - 1) / 1000;
  }, [data]);

  const maxCount = Math.max(1, ...(data?.trend ?? []).map((d) => d.count));
  const maxSeconds = Math.max(1, ...(data?.trend ?? []).map((d) => d.total_seconds));
  const maxHourly = Math.max(1, ...(data?.hourly ?? []).map((h) => h.count));

  // 记录按本地日期分组（sessions 已按时间倒序）
  const grouped = useMemo(() => {
    const map = new Map<string, BehaviorSession[]>();
    for (const s of data?.sessions ?? []) {
      const day = localDayStr(new Date(s.start_time));
      if (!map.has(day)) map.set(day, []);
      map.get(day)!.push(s);
    }
    return [...map.entries()];
  }, [data]);

  return (
    <div className="p-6">
      <header className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold">行为分析</h1>
          <p className="mt-1 text-sm text-zinc-500">
            频率、时段分布与记录明细（全天 24 小时，含周末与加班时段）
          </p>
        </div>
        {/* 行为切换 Tab：注册表新增行为后自动出现 */}
        <div className="flex gap-1 rounded-lg bg-zinc-800/60 p-1">
          {BEHAVIORS.map((b) => (
            <button
              key={b.key}
              onClick={() => setBehavior(b.key)}
              className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                b.key === behavior
                  ? "bg-zinc-700 text-zinc-100"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {b.icon} {b.label}
            </button>
          ))}
        </div>
      </header>

      {error ? (
        <Card className="border-red-900/60">
          <p className="text-sm text-red-400">数据加载失败：{error}</p>
        </Card>
      ) : !data ? (
        <Card>
          <EmptyState text="加载中…" />
        </Card>
      ) : (
        <div className="space-y-4">
          {/* 指标行 */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label={`今日${meta.label}次数`} value={data.summary.count} />
            <Stat
              label="今日总时长"
              value={formatDuration(data.summary.total_seconds)}
              hint={
                data.summary.count > 0
                  ? `平均 ${formatDuration(data.summary.avg_seconds)} / 次`
                  : undefined
              }
            />
            <Stat
              label="平均间隔"
              value={avgInterval != null ? formatDuration(avgInterval) : "-"}
              hint="按最近 50 次记录计算"
            />
            <Stat
              label="距上次"
              value={data.summary.last_start_time ? formatRelative(data.summary.last_start_time) : "-"}
              hint={
                data.summary.last_duration_seconds != null
                  ? `上次时长 ${formatDuration(data.summary.last_duration_seconds)}`
                  : undefined
              }
            />
          </div>

          {/* 今日时段分布：全天 0-23 时 */}
          <Card title="今日时段分布（0:00 – 23:00）">
            <div className="flex h-36 items-end gap-1">
              {data.hourly.map((bucket) => (
                <div
                  key={bucket.hour}
                  className="flex h-full flex-1 flex-col items-center justify-end gap-1"
                  title={`${bucket.hour}:00 ${bucket.count} 次 / ${formatDuration(bucket.total_seconds)}`}
                >
                  {bucket.count > 0 ? (
                    <span className="text-[10px] tabular-nums text-zinc-400">{bucket.count}</span>
                  ) : null}
                  <div
                    className={`w-full rounded-t-sm ${
                      bucket.count > 0 ? "bg-red-500/70" : "bg-zinc-800"
                    }`}
                    style={{ height: `${Math.max((bucket.count / maxHourly) * 100, 2)}%` }}
                  />
                  <span className="text-[9px] tabular-nums text-zinc-600">{bucket.hour}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* 每日趋势：次数 + 时长双指标 */}
          <Card
            title={`每日趋势（近 ${days} 天）`}
            className="relative"
          >
            <div className="absolute right-4 top-4 flex items-center gap-3 text-[11px] text-zinc-500">
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-emerald-500/70" /> 次数
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-amber-500/70" /> 时长
              </span>
              <div className="ml-2 flex gap-1 rounded-md bg-zinc-800 p-0.5">
                {([7, 30] as const).map((d) => (
                  <button
                    key={d}
                    onClick={() => setDays(d)}
                    className={`rounded px-2 py-0.5 transition-colors ${
                      days === d ? "bg-zinc-700 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
                    }`}
                  >
                    {d} 天
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-6 flex h-56 items-end gap-[3px]">
              {data.trend.map((day, i) => (
                <div
                  key={day.day}
                  className="flex h-full flex-1 flex-col items-center justify-end gap-1.5"
                  title={`${day.day} ${day.count} 次 / ${formatDuration(day.total_seconds)}`}
                >
                  <div className="flex w-full flex-1 items-end justify-center gap-[2px]">
                    <div
                      className={`w-1/2 max-w-4 rounded-t-sm ${
                        day.count > 0 ? "bg-emerald-500/70" : "bg-zinc-800"
                      }`}
                      style={{ height: `${Math.max((day.count / maxCount) * 100, 2)}%` }}
                    />
                    <div
                      className={`w-1/2 max-w-4 rounded-t-sm ${
                        day.total_seconds > 0 ? "bg-amber-500/70" : "bg-zinc-800"
                      }`}
                      style={{ height: `${Math.max((day.total_seconds / maxSeconds) * 100, 2)}%` }}
                    />
                  </div>
                  {/* 30 天模式下只标部分日期，避免拥挤 */}
                  {days === 7 || i === data.trend.length - 1 || i % 5 === 0 ? (
                    <span
                      className={`text-[10px] tabular-nums ${
                        isWeekend(day.day) ? "text-amber-400/80" : "text-zinc-500"
                      }`}
                    >
                      {day.day.slice(5)}
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
          </Card>

          {/* 记录明细 */}
          <Card title={`${meta.label}记录明细（最近 ${data.sessions.length} 条）`}>
            {grouped.length === 0 ? (
              <EmptyState text="暂无记录" />
            ) : (
              <div className="space-y-4">
                {grouped.map(([day, sessions]) => (
                  <div key={day}>
                    <p className="mb-1.5 text-xs font-semibold text-zinc-400">
                      {dayLabel(day)}
                      <span className="ml-2 font-normal text-zinc-600">
                        {sessions.length} 次 · 共{" "}
                        {formatDuration(sessions.reduce((sum, s) => sum + s.duration_seconds, 0))}
                      </span>
                    </p>
                    <ul className="divide-y divide-zinc-800/60">
                      {sessions.map((s) => {
                        // 与时间上更早一条的间隔（sessions 倒序，下一条即更早）
                        const all = data.sessions;
                        const prev = all[all.indexOf(s) + 1];
                        const gap = prev
                          ? (new Date(s.start_time).getTime() -
                              new Date(prev.start_time).getTime()) /
                            1000
                          : null;
                        return (
                          <li key={s.id} className="flex items-center gap-4 py-2 text-sm">
                            <span className="w-28 shrink-0 tabular-nums text-zinc-300">
                              {formatHm(s.start_time)} – {formatHm(s.end_time)}
                            </span>
                            <span className="w-20 shrink-0 tabular-nums text-zinc-400">
                              {formatDuration(s.duration_seconds)}
                            </span>
                            <span className="text-xs text-zinc-600">
                              {gap != null ? `距上次 ${formatDuration(gap)}` : ""}
                            </span>
                            <span className="ml-auto text-xs text-zinc-600">{s.device_id}</span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
