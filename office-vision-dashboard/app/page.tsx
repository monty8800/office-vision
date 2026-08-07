"use client";

import { useEffect, useState } from "react";
import {
  formatDuration,
  serverApi,
  type AgentInfo,
  type PresenceDevice,
  type SmokingSummary,
} from "@/lib/server-api";
import {
  Badge,
  Card,
  EmptyState,
  PRESENCE_LABELS,
  presenceTone,
  Stat,
} from "@/components/ui";

interface OverviewData {
  serverOnline: boolean;
  today: SmokingSummary | null;
  agents: AgentInfo[];
  presence: Record<string, PresenceDevice>;
}

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [health, today, agents, presence] = await Promise.all([
          serverApi.health(),
          serverApi.smokingToday(),
          serverApi.agents(),
          serverApi.presence(),
        ]);
        if (!active) return;
        setError(null);
        setData({
          serverOnline: health.status === "ok",
          today,
          agents: agents.agents,
          presence: presence.devices,
        });
      } catch (e) {
        if (active) {
          setError(e instanceof Error ? e.message : String(e));
          setData((prev) => prev ?? {
            serverOnline: false,
            today: null,
            agents: [],
            presence: {},
          });
        }
      }
    };
    load();
    const timer = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const presenceEntries = Object.entries(data?.presence ?? {});

  return (
    <div className="p-6">
      <header className="mb-6">
        <h1 className="text-xl font-bold">概览</h1>
        <p className="mt-1 text-sm text-zinc-500">
          在岗状态与今日行为统计（每 5 秒刷新）
        </p>
      </header>

      {error ? (
        <Card className="mb-4 border-red-900/60">
          <p className="text-sm text-red-400">
            Server 未连接：{error}
          </p>
          <p className="mt-1 text-xs text-zinc-500">
            请先启动：cd office-vision-server && uv run uvicorn server.main:app
          </p>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Server"
          value={
            data?.serverOnline ? (
              <Badge tone="green">在线</Badge>
            ) : (
              <Badge tone="red">离线</Badge>
            )
          }
        />
        <Stat label="今日抽烟次数" value={data?.today?.count ?? "-"} />
        <Stat
          label="今日总时长"
          value={data?.today ? formatDuration(data.today.total_seconds) : "-"}
          hint={
            data?.today && data.today.count > 0
              ? `平均 ${formatDuration(data.today.avg_seconds)} / 次`
              : undefined
          }
        />
        <Stat label="Agent 数量" value={data?.agents.length ?? "-"} />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="在岗状态">
          {presenceEntries.length === 0 ? (
            <EmptyState text="暂无 Presence 事件" />
          ) : (
            <ul className="space-y-2">
              {presenceEntries.map(([deviceId, info]) => (
                <li
                  key={deviceId}
                  className="flex items-center justify-between rounded-lg bg-zinc-800/60 px-4 py-3"
                >
                  <span className="text-sm">{deviceId}</span>
                  <Badge tone={presenceTone(info.state)}>
                    {PRESENCE_LABELS[info.state] ?? info.state}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Agent 心跳">
          {data?.agents.length === 0 ? (
            <EmptyState text="暂无 Agent 上报事件" />
          ) : (
            <ul className="space-y-2">
              {(data?.agents ?? []).map((agent) => (
                <li
                  key={agent.device_id}
                  className="flex items-center justify-between rounded-lg bg-zinc-800/60 px-4 py-3"
                >
                  <div>
                    <p className="text-sm">{agent.device_id}</p>
                    <p className="text-xs text-zinc-500">
                      累计事件 {agent.event_count}
                    </p>
                  </div>
                  <Badge tone={agent.online ? "green" : "zinc"}>
                    {agent.online ? "在线" : "离线"}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
