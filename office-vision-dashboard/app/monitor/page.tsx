"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createMonitorApi,
  monitorApi,
  monitorDevices,
  type MonitorEventItem,
  type MonitorState,
  type LogItem,
  type OverlayState,
  type ReplayMeta,
} from "@/lib/monitor-api";
import { Badge, Card } from "@/components/ui";
import {
  BehaviorPanel,
  EventTimelinePanel,
  LogPanel,
  PerformancePanel,
  PluginPanel,
} from "@/components/monitor/panels";
import {
  OverlayControls,
  ReplayPanel,
  SnapshotPanel,
} from "@/components/monitor/settings";

export default function MonitorPage() {
  const [devices, setDevices] = useState<string[]>([]);
  const [device, setDevice] = useState<string | null>(null);
  const [state, setState] = useState<MonitorState | null>(null);
  const [events, setEvents] = useState<MonitorEventItem[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [replays, setReplays] = useState<ReplayMeta[]>([]);
  const [error, setError] = useState<string | null>(null);

  // 多 Agent 模式：加载 OVA_AGENT_MONITOR_URLS 映射的设备列表；
  // 未配置映射时保持单设备模式（monitorApi 走 /agent-monitor rewrite）
  useEffect(() => {
    monitorDevices().then(({ devices: list }) => {
      setDevices(list);
      if (list.length > 0) setDevice(list[0]);
    });
  }, []);

  const api = useMemo(
    () => (device ? createMonitorApi(`/agent-monitor/${device}`) : monitorApi),
    [device]
  );

  // 切换设备：清空上一路数据，避免新旧设备数据混淆
  const switchDevice = (next: string) => {
    setDevice(next);
    setState(null);
    setEvents([]);
    setLogs([]);
    setReplays([]);
    setError(null);
  };

  useEffect(() => {
    let active = true;
    const loadState = async () => {
      try {
        const next = await api.state();
        if (!active) return;
        // 防御非法响应（如上游返回非 MonitorState 结构），避免渲染崩溃
        if (!next || typeof next.behavior !== "object" || next.behavior === null) {
          setError("Agent 返回了无效的监控状态（检查 Agent 版本）");
          return;
        }
        setState(next);
        setError(null);
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      }
    };
    const loadEvents = async () => {
      try {
        const next = await api.events(200);
        if (active) setEvents(next.events);
      } catch {
        // 事件轮询失败不单独报错（state 轮询已覆盖连通性）
      }
    };
    const loadReplays = async () => {
      try {
        const next = await api.replays();
        if (active) setReplays(next.replays);
      } catch {
        // 同上
      }
    };
    const loadLogs = async () => {
      try {
        const next = await api.logs(200);
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
  }, [api]);

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
        <div className="flex items-center gap-3">
          {devices.length > 0 ? (
            <select
              value={device ?? ""}
              onChange={(e) => switchDevice(e.target.value)}
              className="rounded-md border border-zinc-800 bg-zinc-800/60 px-3 py-1.5 text-sm text-zinc-300"
              aria-label="切换 Agent"
            >
              {devices.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          ) : null}
          <Badge tone={state ? "green" : "red"}>
            {state ? `Agent ${state.device_id} 已连接` : "Agent 未连接"}
          </Badge>
        </div>
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
            key={api.streamUrl}
            src={api.streamUrl}
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
              api={api}
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
        <ReplayPanel api={api} replays={replays} />
        <SnapshotPanel api={api} latestEvent={latestEvent} />

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
