"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import {
  BEHAVIORS,
  formatDuration,
  formatRelative,
  serverApi,
  type BehaviorSession,
  type BehaviorSummary,
  type HourBucket,
  type SittingDay,
  type SittingSession,
  type SittingToday,
  type TrendDay,
} from "@/lib/server-api";
import { Card, EmptyState, Stat } from "@/components/ui";
import { DeviceFilter, useDeviceFilter } from "@/components/device-filter";

type TabKey = "sitting" | "smoking";

interface SmokingData {
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

// ============ 坐席时长 Tab（2 栏） ============
function SittingTab({ device }: { device?: string | null }) {
  const [today, setToday] = useState<SittingToday | null>(null);
  const [daily, setDaily] = useState<SittingDay[]>([]);
  const [sessions, setSessions] = useState<SittingSession[]>([]);
  const [days, setDays] = useState<7 | 30>(7);
  const [error, setError] = useState<string | null>(null);

  const grouped = useMemo(() => {
    const map = new Map<string, SittingSession[]>();
    for (const s of sessions) {
      const day = localDayStr(new Date(s.start_time));
      if (!map.has(day)) map.set(day, []);
      map.get(day)!.push(s);
    }
    return [...map.entries()];
  }, [sessions]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [t, d, s] = await Promise.all([
          serverApi.sittingToday(device),
          serverApi.sittingDaily(days, device),
          serverApi.sittingSessions(50, device),
        ]);
        if (active) {
          setToday(t);
          setDaily(d.days);
          setSessions(s.items);
          setError(null);
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    const timer = setInterval(load, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [days, device]);

  if (error) {
    return (
      <div className="rounded-xl border border-red-900/60 bg-zinc-900/40 p-5">
        <p className="text-sm text-red-400">坐席数据加载失败：{error}</p>
      </div>
    );
  }
  if (!today) return <Card><EmptyState text="加载中…" /></Card>;

  const maxSec = Math.max(1, ...daily.map((d) => d.total_seconds));

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
      {/* 左列：今日指标 + 每日趋势 */}
      <div className="space-y-4 xl:col-span-3">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat
            label="今日坐席时长"
            value={formatDuration(today.total_seconds)}
            hint={`平均 ${formatDuration(today.avg_seconds)} / 次`}
          />
          <Stat label="在座次数" value={today.sessions} hint={`进入画面 ${today.sessions} 次`} />
          <Stat label="离开次数" value={today.leaves} hint={`离开画面 ${today.leaves} 次`} />
          <Stat
            label="当前状态"
            value={today.now_sitting ? "在座中" : "已离开"}
            hint={
              today.now_sitting && today.current_session_start
                ? `本次自 ${formatHm(today.current_session_start)}`
                : undefined
            }
          />
        </div>

        <Card title={`每日在岗时长（近 ${days} 天）`} className="relative">
          <div className="absolute right-4 top-4 flex gap-1 rounded-md bg-zinc-800 p-0.5">
            {([7, 30] as const).map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                  days === d ? "bg-zinc-700 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {d} 天
              </button>
            ))}
          </div>
          <div className="mt-6 flex h-40 items-end gap-[3px]">
            {daily.map((d) => (
              <div
                key={d.day}
                className="flex h-full flex-1 flex-col items-center justify-end gap-1"
                title={`${d.day} 坐席 ${formatDuration(d.total_seconds)} · 进入 ${d.sessions} · 离开 ${d.leaves}`}
              >
                <div
                  className={`w-full rounded-t-sm ${
                    d.total_seconds > 0 ? "bg-sky-500/70" : "bg-zinc-800"
                  }`}
                  style={{ height: `${Math.max((d.total_seconds / maxSec) * 100, 2)}%` }}
                />
                {days === 7 || new Date(`${d.day}T00:00:00`).getDate() % 5 === 0 ? (
                  <span className="text-[9px] tabular-nums text-zinc-600">{d.day.slice(5)}</span>
                ) : null}
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* 右列：进出记录（紧凑，小高度滚动） */}
      <div className="xl:col-span-2">
        <Card title={`进出记录（最近 ${sessions.length} 条）`}>
          <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
            {grouped.length === 0 ? (
              <EmptyState text="暂无记录" />
            ) : (
              grouped.map(([day, list]) => (
                <div key={day}>
                  <p className="mb-1 text-[11px] font-semibold text-zinc-400">
                    {dayLabel(day)}
                    <span className="ml-1.5 font-normal text-zinc-600">· {list.length} 段</span>
                  </p>
                  <ul className="divide-y divide-zinc-800/60">
                    {list.map((s, i) => (
                      <li key={i} className="flex items-center gap-2 py-1 text-xs">
                        <span className="shrink-0 tabular-nums text-zinc-300">
                          {formatHm(s.start_time)} – {s.end_time ? formatHm(s.end_time) : "…"}
                        </span>
                        <span className="ml-auto shrink-0 tabular-nums text-zinc-500">
                          {formatDuration(s.duration_seconds)}
                        </span>
                        {!s.end_time && (
                          <span className="shrink-0 rounded bg-emerald-500/20 px-1 py-0.5 text-[10px] text-emerald-300">
                            在座中
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ============ 抽烟统计 Tab（2 栏） ============
function SmokingTab({ device }: { device?: string | null }) {
  const behavior = "smoking";
  const meta = BEHAVIORS.find((b) => b.key === behavior) ?? BEHAVIORS[0];
  const [days, setDays] = useState<7 | 30>(7);
  const [data, setData] = useState<SmokingData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [summary, sessions, trend, hourly] = await Promise.all([
          serverApi.behaviorToday(behavior, device),
          serverApi.behaviorSessions(behavior, 50, device),
          serverApi.behaviorTrend(behavior, days, device),
          serverApi.behaviorHourly(behavior, device),
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
  }, [days, device]);

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

  if (error) {
    return (
      <div className="rounded-xl border border-red-900/60 bg-zinc-900/40 p-5">
        <p className="text-sm text-red-400">抽烟数据加载失败：{error}</p>
      </div>
    );
  }
  if (!data) return <Card><EmptyState text="加载中…" /></Card>;

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
      {/* 左列：指标 + 时段分布 + 每日趋势 */}
      <div className="space-y-4 xl:col-span-3">
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

        <Card title="今日时段分布（0:00 – 23:00）">
          <div className="flex h-32 items-end gap-1">
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

        <Card title={`每日趋势（近 ${days} 天）`} className="relative">
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
                  className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                    days === d ? "bg-zinc-700 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {d} 天
                </button>
              ))}
            </div>
          </div>
          <div className="mt-6 flex h-40 items-end gap-[3px]">
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
      </div>

      {/* 右列：抽烟记录明细（紧凑，小高度滚动） */}
      <div className="xl:col-span-2">
        <Card title={`${meta.label}记录明细（最近 ${data.sessions.length} 条）`}>
          <div className="max-h-[520px] space-y-3 overflow-y-auto pr-1">
            {grouped.length === 0 ? (
              <EmptyState text="暂无记录" />
            ) : (
              grouped.map(([day, sessions]) => (
                <div key={day}>
                  <p className="mb-1 text-[11px] font-semibold text-zinc-400">
                    {dayLabel(day)}
                    <span className="ml-1.5 font-normal text-zinc-600">
                      · {sessions.length} 次 · 共{" "}
                      {formatDuration(sessions.reduce((sum, s) => sum + s.duration_seconds, 0))}
                    </span>
                  </p>
                  <ul className="divide-y divide-zinc-800/60">
                    {sessions.map((s) => {
                      const all = data.sessions;
                      const prev = all[all.indexOf(s) + 1];
                      const gap = prev
                        ? (new Date(s.start_time).getTime() - new Date(prev.start_time).getTime()) /
                          1000
                        : null;
                      return (
                        <li key={s.id} className="flex items-center gap-3 py-1.5 text-xs">
                          <span className="shrink-0 tabular-nums text-zinc-300">
                            {formatHm(s.start_time)} – {formatHm(s.end_time)}
                          </span>
                          <span className="shrink-0 tabular-nums text-zinc-500">
                            {formatDuration(s.duration_seconds)}
                          </span>
                          {gap != null ? (
                            <span className="ml-auto shrink-0 text-[11px] text-zinc-600">
                              距上次 {formatDuration(gap)}
                            </span>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

// useSearchParams 需要 Suspense 边界（仅多设备时筛选器可见）
export default function AnalysisPage() {
  return (
    <Suspense fallback={null}>
      <AnalysisContent />
    </Suspense>
  );
}

function AnalysisContent() {
  const { device } = useDeviceFilter();
  const [tab, setTab] = useState<TabKey>("sitting");

  const tabClass = (key: TabKey) =>
    `rounded-md px-4 py-1.5 text-sm transition-colors ${
      tab === key ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"
    }`;

  return (
    <div className="p-6">
      <header className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold">行为分析</h1>
          <p className="mt-1 text-sm text-zinc-500">
            坐席时长、进出记录与行为统计（全天 24 小时，含周末与加班时段）
          </p>
        </div>
        <DeviceFilter />
      </header>

      {/* 顶部 Tabs：坐席时长 / 抽烟统计 */}
      <div className="mb-5 flex gap-1 rounded-lg bg-zinc-800/60 p-1">
        <button type="button" onClick={() => setTab("sitting")} className={tabClass("sitting")}>
          🪑 坐席时长
        </button>
        <button type="button" onClick={() => setTab("smoking")} className={tabClass("smoking")}>
          🚬 抽烟统计
        </button>
      </div>

      {tab === "sitting" ? (
        <SittingTab device={device} />
      ) : (
        <SmokingTab device={device} />
      )}
    </div>
  );
}
