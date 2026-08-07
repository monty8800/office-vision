// Agent Debug Center API 客户端（http://localhost:8100 经 Next 代理）
// 仅开发模式可用：agent.yaml debug.enabled=false 时服务不存在。

export interface DebugBehavior {
  presence: string;
  current: string;
  since: string | null;
  duration_seconds: number | null;
  hand_mouth_distance_px: number | null;
}

export interface DebugPlugin {
  name: string;
  status: string;
}

export interface DebugPerformance {
  cpu_percent: number;
  memory_mb: number;
  camera_fps: number;
  ai_fps: number;
  inference_ms: number;
  queue_length: number;
  latency_ms: number;
}

export type OverlayKey =
  | "face"
  | "hand"
  | "mouth"
  | "bbox"
  | "state"
  | "fps"
  | "event"
  | "distance";

export type OverlayState = Record<OverlayKey, boolean>;

export interface DebugState {
  device_id: string;
  behavior: DebugBehavior;
  plugins: DebugPlugin[];
  performance: Partial<DebugPerformance>;
  overlays: OverlayState;
  frame_buffer_frames: number;
}

export interface DebugEventItem {
  time: string;
  event_type: string;
  device_id: string;
  payload: Record<string, unknown>;
}

export interface LogItem {
  time: string;
  level: string;
  message: string;
}

export interface ReplayMeta {
  event_id: string;
  event_type: string;
  device_id: string;
  occurred_at: string;
  frame_count: number;
  payload: Record<string, unknown>;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const debugApi = {
  state: () => getJson<DebugState>("/agent-debug/state"),
  events: (limit = 100) =>
    getJson<{ events: DebugEventItem[] }>(`/agent-debug/events?limit=${limit}`),
  logs: (limit = 200) => getJson<{ logs: LogItem[] }>(`/agent-debug/logs?limit=${limit}`),
  replays: () => getJson<{ replays: ReplayMeta[] }>("/agent-debug/replays"),
  setOverlays: (changes: Partial<OverlayState>) =>
    postJson<OverlayState>("/agent-debug/overlays", changes),
  saveSnapshot: () =>
    postJson<{ image: string; meta: string }>("/agent-debug/snapshot", {}),
  label: (eventId: string, verdict: "correct" | "wrong", note = "") =>
    postJson<Record<string, unknown>>("/agent-debug/labels", {
      event_id: eventId,
      verdict,
      note,
    }),
  streamUrl: "/agent-debug/stream",
  replayUrl: (eventId: string) => `/agent-debug/replays/${eventId}.mp4`,
};
