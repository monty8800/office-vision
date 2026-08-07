"use client";

import { useEffect, useState } from "react";
import { formatTime, serverApi, type AgentInfo } from "@/lib/server-api";
import { Badge, Card, EmptyState } from "@/components/ui";

export default function StatusPage() {
  const [agents, setAgents] = useState<AgentInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await serverApi.agents();
        if (active) {
          setAgents(result.agents);
          setError(null);
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    const timer = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="p-6">
      <header className="mb-6">
        <h1 className="text-xl font-bold">系统状态</h1>
        <p className="mt-1 text-sm text-zinc-500">Agent 心跳与在线判定（60 秒阈值）</p>
      </header>

      <Card>
        {error ? (
          <p className="text-sm text-red-400">加载失败：{error}</p>
        ) : !agents ? (
          <EmptyState text="加载中…" />
        ) : agents.length === 0 ? (
          <EmptyState text="暂无 Agent 注册（等待首个事件上报）" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-zinc-500">
                <th className="pb-2 font-medium">设备</th>
                <th className="pb-2 font-medium">状态</th>
                <th className="pb-2 font-medium">累计事件</th>
                <th className="pb-2 font-medium">最后心跳</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/80">
              {agents.map((agent) => (
                <tr key={agent.device_id}>
                  <td className="py-2.5">{agent.device_id}</td>
                  <td className="py-2.5">
                    <Badge tone={agent.online ? "green" : "zinc"}>
                      {agent.online ? "在线" : "离线"}
                    </Badge>
                  </td>
                  <td className="py-2.5 tabular-nums">{agent.event_count}</td>
                  <td className="py-2.5 text-xs text-zinc-500">
                    {agent.last_seen_at ? formatTime(agent.last_seen_at) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
