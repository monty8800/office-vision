// Agent 监控中心 API 客户端（http://localhost:8100 经 Next 代理）
// 仅开发模式可用：agent.yaml monitor.enabled=false 时服务不存在。
// 多 Agent：createMonitorApi(`/agent-monitor/${device}`) 经 proxy.ts 转发至对应 Agent；
// 默认实例 monitorApi 走 /agent-monitor rewrite（单设备回退）。

export interface MonitorBehavior {
  presence: string;
  current: string;
  since: string | null;
  duration_seconds: number | null;
  hand_mouth_distance_px: number | null;
}

export interface MonitorPlugin {
  name: string;
  status: string;
}

export interface MonitorPerformance {
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

export interface MonitorState {
  device_id: string;
  behavior: MonitorBehavior;
  plugins: MonitorPlugin[];
  performance: Partial<MonitorPerformance>;
  overlays: OverlayState;
  frame_buffer_frames: number;
}

export interface MonitorEventItem {
  time: string;
  event_type: string;
  device_id: string;
  payload: Record<string, unknown>;
}

export interface AnnotateBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface AnnotatePayload {
  image: string; // dataURL 或 base64 JPEG
  boxes: AnnotateBox[];
  label: string;
  negative: boolean;
  device_id: string;
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
  /** 截图模式产物；旧版 mp4 回放无此字段 */
  snapshots?: string[];
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

export function createMonitorApi(basePath = "/agent-monitor") {
  return {
    state: () => getJson<MonitorState>(`${basePath}/state`),
    events: (limit = 100) =>
      getJson<{ events: MonitorEventItem[] }>(`${basePath}/events?limit=${limit}`),
    logs: (limit = 200) => getJson<{ logs: LogItem[] }>(`${basePath}/logs?limit=${limit}`),
    replays: () => getJson<{ replays: ReplayMeta[] }>(`${basePath}/replays`),
    setOverlays: (changes: Partial<OverlayState>) =>
      postJson<OverlayState>(`${basePath}/overlays`, changes),
    saveSnapshot: () =>
      postJson<{ image: string; meta: string }>(`${basePath}/snapshot`, {}),
    label: (eventId: string, verdict: "correct" | "wrong", note = "") =>
      postJson<Record<string, unknown>>(`${basePath}/labels`, {
        event_id: eventId,
        verdict,
        note,
      }),
    annotate: (payload: AnnotatePayload) =>
      postJson<{ saved_image: string; saved_json: string; boxes: number; negative: boolean }>(
        `${basePath}/annotate`,
        payload
      ),
    streamUrl: `${basePath}/stream`,
    rawFrameUrl: `${basePath}/raw.png`,
    replaySnapshotUrl: (eventId: string, name: string) =>
      `${basePath}/replays/${eventId}/frames/${name}`,
  };
}

export type MonitorApi = ReturnType<typeof createMonitorApi>;

export const monitorApi = createMonitorApi();

// 多 Agent 模式下已配置映射的设备列表（未配置返回空数组）；
// 响应结构非法时（如旧进程无此端点，请求落到 rewrite 透传给 Agent 监控服务）
// 同样视为单设备模式，避免调用方拿到 undefined
export async function monitorDevices(): Promise<{ devices: string[] }> {
  try {
    const r = await getJson<{ devices?: string[] }>("/agent-monitor/devices");
    return { devices: Array.isArray(r.devices) ? r.devices : [] };
  } catch {
    return { devices: [] };
  }
}
