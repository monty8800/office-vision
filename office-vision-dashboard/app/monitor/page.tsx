"use client";

import { useEffect, useState } from "react";
import {
  debugApi,
  type DebugEventItem,
  type DebugState,
  type LogItem,
  type OverlayState,
  type ReplayMeta,
} from "@/lib/debug-api";
import { Badge, Card } from "@/components/ui";
import {
  BehaviorPanel,
  EventTimelinePanel,
  LogPanel,
  PerformancePanel,
  PluginPanel,
} from "@/components/debug/panels";
import {
  OverlayControls,
  ReplayPanel,
  SnapshotPanel,
} from "@/components/debug/settings";

export default function MonitorPage() {
  const [state, setState] = useState<DebugState | null>(null);
  const [events, setEvents] = useState<DebugEventItem[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [replays, setReplays] = useState<ReplayMeta[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const loadState = async () => {
      try {
        const next = await debugApi.state();
        if (!active) return;
        setState(next);
        setError(null);
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      }
    };
    const loadEvents = async () => {
      try {
        const next = await debugApi.events(200);
        if (active) setEvents(next.events);
      } catch {
        // 事件轮询失败不单独报错（state 轮询已覆盖连通性）
      }
    };
    const loadReplays = async () => {
      try {
        const next = await debugApi.replays();
        if (active) setReplays(next.replays);
      } catch {
        // 同上
      }
    };
    const loadLogs = async () => {
      try {
        const next = await debugApi.logs(200);
        if (active) setLogs(next.logs);
      } catch {
        // 同上
      }
    };
    loadState();
    loadEvents();
    loadLogs();
    loadReplays();
    const stateTimer = setInterval(loadState, 1000);
    const eventTimer = setInterval(loadEvents, 2000);
    const logTimer = setInterval(loadLogs, 2000);
    const replayTimer = setInterval(loadReplays, 10000);
    return () => {
      active = false;
      clearInterval(stateTimer);
      clearInterval(eventTimer);
      clearInterval(logTimer);
      clearInterval(replayTimer);
    };
  }, []);

  const latestEvent = events.length > 0 ? events[events.length - 1] : null;

  return (
    <div className="p-6">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">实时监控</h1>
          <p className="mt-1 text-sm text-zinc-500">
            实时观察画面、AI 行为识别状态与事件流
          </p>
        </div>
        <Badge tone={state ? "green" : "red"}>
          {state ? `Agent ${state.device_id} 已连接` : "Agent 未连接"}
        </Badge>
      </header>

      {error ? (
        <Card className="mb-4 border-red-900/60">
          <p className="text-sm text-red-400">实时监控服务未连接：{error}</p>
          <p className="mt-1 text-xs text-zinc-500">
            请确认 Agent 已启动（监控端口默认 8100）
          </p>
        </Card>
      ) : null}

      {/* 四栏布局：实时画面 | 行为状态 / 事件时间轴 | 性能 / 插件状态 | 画面标注 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* 实时画面 */}
        <Card title="实时画面（标注：面部 / 手部 / 嘴部 / 检测框 / 距离 / 帧率）">
          <img
            src={debugApi.streamUrl}
            alt="实时画面（MJPEG 实时流）"
            className="w-full rounded-lg border border-zinc-800 bg-black"
          />
        </Card>

        {/* 行为状态（含状态机） */}
        {state ? <BehaviorPanel state={state} /> : <PlaceholderCard title="行为状态" />}

        {/* 事件时间轴 */}
        <EventTimelinePanel events={events} />

        {/* 性能 */}
        {state ? (
          <PerformancePanel perf={state.performance} />
        ) : (
          <PlaceholderCard title="性能" />
        )}

        {/* 插件状态 */}
        {state ? <PluginPanel state={state} /> : <PlaceholderCard title="插件状态" />}

        {/* 画面标注开关 */}
        <Card title="画面标注">
          {state ? (
            <OverlayControls
              overlays={state.overlays}
              onChanged={(next: OverlayState) =>
                setState((prev) => (prev ? { ...prev, overlays: next } : prev))
              }
            />
          ) : (
            <p className="text-sm text-zinc-600">等待连接…</p>
          )}
        </Card>

        {/* 事件回放 + 快照与标注 */}
        <ReplayPanel replays={replays} />
        <SnapshotPanel latestEvent={latestEvent} />

        {/* 实时日志（整行宽，不落盘） */}
        <LogPanel logs={logs} />
      </div>
    </div>
  );
}

function PlaceholderCard({ title }: { title: string }) {
  return (
    <Card title={title} className="h-full">
      <p className="flex min-h-24 items-center justify-center text-sm text-zinc-600">
        等待 Agent 连接…
      </p>
    </Card>
  );
}
