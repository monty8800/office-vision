"use client";

import type { DebugEventItem, DebugPerformance, DebugState, LogItem } from "@/lib/debug-api";
import { eventLabel } from "@/lib/server-api";
import { Badge, Card, EmptyState, PRESENCE_LABELS, presenceTone } from "@/components/ui";

// ---- Behavior 面板：当前状态 + 状态机可视化 ----

const SMOKING_STAGES = ["Idle", "HandNearMouth", "PossibleSmoking", "Smoking", "Finished"];

const STAGE_LABELS: Record<string, string> = {
  Idle: "空闲",
  HandNearMouth: "手近嘴部",
  PossibleSmoking: "疑似抽烟",
  Smoking: "抽烟中",
  Finished: "已结束",
};

const BEHAVIOR_LABELS: Record<string, string> = {
  idle: "空闲",
  smoking: "抽烟中",
};

function currentStage(behavior: DebugState["behavior"]): string {
  // 状态由事件派生：smoking 行为进行中 → Smoking；其余回落到 Idle
  return behavior.current === "smoking" ? "Smoking" : "Idle";
}

export function BehaviorPanel({ state }: { state: DebugState }) {
  const { behavior } = state;
  const stage = currentStage(behavior);
  return (
    <Card title="行为状态" className="h-full">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-zinc-500">当前状态</dt>
          <dd className="mt-0.5">
            <Badge tone={presenceTone(behavior.presence)}>
              {PRESENCE_LABELS[behavior.presence] ?? behavior.presence}
            </Badge>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">当前行为</dt>
          <dd className="mt-0.5 font-medium">
            {behavior.current ? (BEHAVIOR_LABELS[behavior.current] ?? behavior.current) : "-"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">手→嘴距离</dt>
          <dd className="mt-0.5 tabular-nums">
            {behavior.hand_mouth_distance_px != null
              ? `${behavior.hand_mouth_distance_px}px`
              : "-"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">持续时长</dt>
          <dd className="mt-0.5 tabular-nums">
            {behavior.duration_seconds != null
              ? `${behavior.duration_seconds.toFixed(1)}s`
              : "-"}
          </dd>
        </div>
      </dl>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold text-zinc-400">状态机</p>
        <ol className="flex flex-col items-center gap-1">
          {SMOKING_STAGES.map((name, index) => {
            const active = name === stage;
            return (
              <li key={name} className="flex flex-col items-center">
                {index > 0 ? (
                  <span className="text-zinc-700" aria-hidden>
                    ↓
                  </span>
                ) : null}
                <span
                  className={`rounded-md px-3 py-1 text-xs ${
                    active
                      ? "bg-emerald-500/25 font-bold text-emerald-300 ring-1 ring-emerald-400/60"
                      : "bg-zinc-800 text-zinc-500"
                  }`}
                >
                  {STAGE_LABELS[name]}
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    </Card>
  );
}

// ---- Event Timeline 面板（最新在上） ----

export function EventTimelinePanel({ events }: { events: DebugEventItem[] }) {
  return (
    <Card title="事件时间轴" className="h-full">
      {events.length === 0 ? (
        <EmptyState text="等待事件…" />
      ) : (
        <ul
          className="flex max-h-72 flex-col gap-1.5 overflow-y-auto"
          data-testid="event-timeline"
        >
          {[...events].reverse().map((event, index) => (
            <li
              key={`${event.time}-${index}`}
              className="flex items-center gap-3 rounded-md bg-zinc-800/60 px-3 py-1.5 text-xs"
            >
              <span className="shrink-0 tabular-nums text-zinc-500">
                {new Date(event.time).toLocaleTimeString("zh-CN", { hour12: false })}
              </span>
              <Badge tone={event.event_type.startsWith("Smoking") ? "red" : "blue"}>
                {eventLabel(event.event_type)}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---- 实时日志面板（最新在上；Agent 内存环形缓冲，不落盘） ----

const LOG_LEVEL_TONE: Record<string, "red" | "amber" | "blue" | "zinc"> = {
  ERROR: "red",
  WARNING: "amber",
  INFO: "blue",
};

export function LogPanel({ logs }: { logs: LogItem[] }) {
  return (
    <Card title="实时日志（最近 500 条 · 不落盘）" className="xl:col-span-2">
      {logs.length === 0 ? (
        <EmptyState text="等待日志…" />
      ) : (
        <ul className="flex max-h-80 flex-col gap-0.5 overflow-y-auto font-mono text-xs">
          {[...logs].reverse().map((log, index) => (
            <li
              key={`${log.time}-${index}`}
              className="flex items-start gap-2 rounded bg-zinc-800/40 px-2 py-1"
            >
              <span className="shrink-0 tabular-nums text-zinc-500">{log.time}</span>
              <Badge tone={LOG_LEVEL_TONE[log.level] ?? "zinc"}>{log.level}</Badge>
              <span className="break-all text-zinc-300">{log.message}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---- 性能面板 ----

const PERF_ROWS: Array<{ key: keyof DebugPerformance; label: string; unit?: string }> = [
  { key: "cpu_percent", label: "CPU", unit: "%" },
  { key: "memory_mb", label: "内存", unit: "MB" },
  { key: "camera_fps", label: "摄像头帧率" },
  { key: "ai_fps", label: "AI 帧率" },
  { key: "inference_ms", label: "推理耗时", unit: "ms" },
  { key: "queue_length", label: "队列长度" },
  { key: "latency_ms", label: "延迟", unit: "ms" },
];

export function PerformancePanel({ perf }: { perf: Partial<DebugPerformance> }) {
  return (
    <Card title="性能" className="h-full">
      {Object.keys(perf).length === 0 ? (
        <EmptyState text="性能采集已关闭" />
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
          {PERF_ROWS.map(({ key, label, unit }) => (
            <div key={key} className="rounded-lg bg-zinc-800/60 px-3 py-2">
              <dt className="text-[11px] text-zinc-500">{label}</dt>
              <dd className="tabular-nums">
                {perf[key] ?? "-"}
                {unit ? <span className="ml-0.5 text-xs text-zinc-500">{unit}</span> : null}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}

// ---- 插件状态面板 ----

export function PluginPanel({ state }: { state: DebugState }) {
  return (
    <Card title="插件状态" className="h-full">
      {state.plugins.length === 0 ? (
        <EmptyState text="插件目录为空" />
      ) : (
        <ul className="space-y-2">
          {state.plugins.map((plugin) => (
            <li
              key={plugin.name}
              className="flex items-center justify-between rounded-lg bg-zinc-800/60 px-3 py-2 text-sm"
            >
              <span>{plugin.name}</span>
              <Badge tone={plugin.status === "running" ? "green" : "zinc"}>
                {plugin.status === "running" ? "Running" : "Suspended"}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
