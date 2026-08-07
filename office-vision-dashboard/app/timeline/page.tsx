"use client";

import { useEffect, useState } from "react";
import {
  eventLabel,
  formatTime,
  NOISE_EVENT_TYPES,
  serverApi,
  type EventLogItem,
} from "@/lib/server-api";
import { Badge, Card, EmptyState } from "@/components/ui";

function eventTone(type: string): "green" | "amber" | "red" | "zinc" | "blue" {
  if (type.startsWith("Smoking")) return "red";
  if (type.startsWith("Seat")) return "green";
  if (type.startsWith("Presence")) return "blue";
  return "zinc";
}

export default function TimelinePage() {
  const [events, setEvents] = useState<EventLogItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await serverApi.events(200);
        if (active) {
          // 心跳等周期性事件不进时间轴（避免淹没业务事件）
          setEvents(result.events.filter((e) => !NOISE_EVENT_TYPES.has(e.event_type)));
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
        <h1 className="text-xl font-bold">事件时间轴</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Server 收到的全部 Agent 事件（倒序，每 5 秒刷新）
        </p>
      </header>

      <Card>
        {error ? (
          <p className="text-sm text-red-400">加载失败：{error}</p>
        ) : events.length === 0 ? (
          <EmptyState text="暂无事件" />
        ) : (
          <ul className="divide-y divide-zinc-800/80">
            {events.map((event) => (
              <li key={event.event_id} className="flex items-center gap-4 py-2.5">
                <span className="w-20 shrink-0 text-xs tabular-nums text-zinc-500">
                  {formatTime(event.occurred_at)}
                </span>
                <Badge tone={eventTone(event.event_type)}>
                  {eventLabel(event.event_type)}
                </Badge>
                <span className="text-xs text-zinc-500">{event.device_id}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
