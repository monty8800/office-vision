// Server API 客户端（http://localhost:8000 经 Next 代理）

export interface EventLogItem {
  event_id: string;
  device_id: string;
  event_type: string;
  occurred_at: string;
  received_at: string;
}

export interface AgentInfo {
  device_id: string;
  last_seen_at: string;
  event_count: number;
  online: boolean;
}

export interface SmokingSummary {
  count: number;
  total_seconds: number;
  avg_seconds: number;
}

export interface TrendDay {
  day: string;
  count: number;
}

export interface PresenceDevice {
  state: string;
  last_event: string | null;
  updated_at: string | null;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const serverApi = {
  health: () => getJson<{ status: string }>("/api/health"),
  events: (limit = 100) =>
    getJson<{ events: EventLogItem[] }>(`/api/events?limit=${limit}`),
  agents: () => getJson<{ agents: AgentInfo[] }>("/api/agents"),
  smokingToday: () => getJson<SmokingSummary>("/api/smoking/today"),
  smokingTrend: (days = 7) =>
    getJson<{ days: TrendDay[] }>(`/api/smoking/trend?days=${days}`),
  presence: () => getJson<{ devices: Record<string, PresenceDevice> }>("/api/presence"),
};

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}

// 事件类型中文名（标识符保持英文，展示层翻译；未知类型原样显示）
const EVENT_LABELS: Record<string, string> = {
  SeatOccupied: "在岗",
  SeatEmpty: "离开",
  SmokingStarted: "开始抽烟",
  SmokingEnded: "抽烟结束",
  PresenceSleeping: "休眠",
  PresenceResumed: "恢复运行",
};

export function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type;
}
