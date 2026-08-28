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

export interface PresenceDevice {
  state: string;
  last_event: string | null;
  updated_at: string | null;
}

// ---------- 行为（Behavior）通用类型 ----------

export interface BehaviorInfo {
  key: string;
  label: string;
}

export interface BehaviorSummary {
  count: number;
  total_seconds: number;
  avg_seconds: number;
  last_start_time: string | null;
  last_duration_seconds: number | null;
}

export interface BehaviorSession {
  id: number;
  device_id: string;
  start_time: string;
  end_time: string;
  duration_seconds: number;
}

export interface TrendDay {
  day: string;
  count: number;
  total_seconds: number;
}

export interface HourBucket {
  hour: number;
  count: number;
  total_seconds: number;
}

// ---------- 坐席（在岗/离开）----------

export interface SittingToday {
  day: string;
  total_seconds: number;
  sessions: number;
  leaves: number;
  avg_seconds: number;
  now_sitting: boolean;
  current_session_start: string | null;
  first_sit_time: string | null;
  last_leave_time: string | null;
  last_leave_duration: number | null;
}

export interface SittingDay {
  day: string;
  total_seconds: number;
  sessions: number;
  leaves: number;
  avg_seconds: number;
}

export interface SittingSession {
  start_time: string;
  end_time: string | null; // null = 进行中（仍在座）
  duration_seconds: number;
}

// ---------- 客户端日志 ----------

export interface LogChunkMeta {
  chunk_id: string;
  device_id: string;
  component: string;
  trigger: "periodic" | "error";
  logged_at: string;
  received_at: string;
  size: number;
}

export interface LogChunkDetail extends LogChunkMeta {
  content: string;
}

// 行为注册表（展示层）：新增行为（如喝水 drinking / 看手机 phone_use）
// 只需在此追加一行，并在 Server 的 ENDED_EVENT_BEHAVIORS 注册事件映射。
export interface BehaviorMeta {
  key: string;
  label: string;
  tone: "green" | "amber" | "red" | "zinc" | "blue";
  icon: string;
}

export const BEHAVIORS: BehaviorMeta[] = [
  { key: "smoking", label: "抽烟", tone: "red", icon: "🚬" },
];

// 设备筛选查询串：Server 统计/事件接口均支持 device_id 过滤（不传则全设备聚合）
function deviceParam(deviceId?: string | null, prefix = "&"): string {
  return deviceId ? `${prefix}device_id=${encodeURIComponent(deviceId)}` : "";
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const serverApi = {
  health: () => getJson<{ status: string }>("/api/health"),
  events: (limit = 100, deviceId?: string | null) =>
    getJson<{ events: EventLogItem[] }>(`/api/events?limit=${limit}${deviceParam(deviceId)}`),
  agents: () => getJson<{ agents: AgentInfo[] }>("/api/agents"),
  presence: () => getJson<{ devices: Record<string, PresenceDevice> }>("/api/presence"),
  behaviors: () => getJson<{ behaviors: BehaviorInfo[] }>("/api/behaviors"),
  behaviorToday: (behavior: string, deviceId?: string | null) =>
    getJson<BehaviorSummary>(
      `/api/behaviors/${behavior}/today${deviceParam(deviceId, "?")}`
    ),
  behaviorSessions: (behavior: string, limit = 50, deviceId?: string | null) =>
    getJson<{ items: BehaviorSession[]; limit: number; offset: number }>(
      `/api/behaviors/${behavior}/sessions?limit=${limit}${deviceParam(deviceId)}`
    ),
  behaviorTrend: (behavior: string, days = 7, deviceId?: string | null) =>
    getJson<{ days: TrendDay[] }>(
      `/api/behaviors/${behavior}/trend?days=${days}${deviceParam(deviceId)}`
    ),
  behaviorHourly: (behavior: string, deviceId?: string | null) =>
    getJson<{ date: string; hours: HourBucket[] }>(
      `/api/behaviors/${behavior}/hourly${deviceParam(deviceId, "?")}`
    ),
  sittingToday: (deviceId?: string | null) =>
    getJson<SittingToday>(`/api/sitting/today${deviceParam(deviceId, "?")}`),
  sittingDaily: (days = 7, deviceId?: string | null) =>
    getJson<{ days: SittingDay[] }>(
      `/api/sitting/daily?days=${days}${deviceParam(deviceId)}`
    ),
  sittingSessions: (limit = 50, deviceId?: string | null) =>
    getJson<{ items: SittingSession[]; limit: number; offset: number }>(
      `/api/sitting/sessions?limit=${limit}${deviceParam(deviceId)}`
    ),
  logs: (limit = 50, offset = 0, deviceId?: string | null) =>
    getJson<{ total: number; chunks: LogChunkMeta[] }>(
      `/api/logs?limit=${limit}&offset=${offset}${deviceParam(deviceId)}`
    ),
  logDetail: (chunkId: string) =>
    getJson<LogChunkDetail>(`/api/logs/${encodeURIComponent(chunkId)}`),
};

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

// 相对时间（"距上次"展示用）
export function formatRelative(iso: string): string {
  const diffSec = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diffSec < 60) return "刚刚";
  const minutes = Math.floor(diffSec / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
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
  AgentAlive: "心跳",
};

// 周期性系统事件：时间轴等展示层默认过滤，避免淹没业务事件
export const NOISE_EVENT_TYPES = new Set(["AgentAlive"]);

export function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type;
}
