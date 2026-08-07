"use client";

import { useState } from "react";
import {
  type MonitorApi,
  type MonitorEventItem,
  type OverlayKey,
  type OverlayState,
  type ReplayMeta,
} from "@/lib/monitor-api";
import { Card, EmptyState } from "@/components/ui";
import { eventLabel } from "@/lib/server-api";

const OVERLAY_LABELS: Record<OverlayKey, string> = {
  face: "面部",
  hand: "手部",
  mouth: "嘴部",
  bbox: "检测框",
  state: "状态",
  fps: "帧率",
  event: "事件",
  distance: "距离",
};

// ---- Overlay 开关 ----

export function OverlayControls({
  api,
  overlays,
  onChanged,
}: {
  api: MonitorApi;
  overlays: OverlayState;
  onChanged: (next: OverlayState) => void;
}) {
  const toggle = async (key: OverlayKey) => {
    const value = !overlays[key];
    onChanged({ ...overlays, [key]: value }); // 乐观更新
    try {
      const next = await api.setOverlays({ [key]: value });
      onChanged(next);
    } catch {
      onChanged({ ...overlays, [key]: !value }); // 回滚
    }
  };
  return (
    <div className="grid grid-cols-2 gap-2">
      {(Object.keys(OVERLAY_LABELS) as OverlayKey[]).map((key) => (
        <label
          key={key}
          className="flex cursor-pointer items-center gap-2 rounded-md bg-zinc-800/60 px-3 py-1.5 text-xs hover:bg-zinc-800"
        >
          <input
            type="checkbox"
            checked={overlays[key] ?? false}
            onChange={() => toggle(key)}
            className="accent-emerald-500"
          />
          {OVERLAY_LABELS[key]}
        </label>
      ))}
    </div>
  );
}

// ---- Event Replay 列表 + 截图浏览（不录视频，节省磁盘） ----

export function ReplayPanel({ api, replays }: { api: MonitorApi; replays: ReplayMeta[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const selectedReplay = replays.find((r) => r.event_id === selected) ?? null;
  return (
    <Card title="事件回放（事件前 10s + 过程 + 后 10s · 截图模式）">
      {replays.length === 0 ? (
        <EmptyState text="暂无回放（触发开始抽烟/抽烟结束事件后自动生成）" />
      ) : (
        <div className="space-y-2">
          {selectedReplay ? (
            selectedReplay.snapshots && selectedReplay.snapshots.length > 0 ? (
              <div className="grid max-h-64 grid-cols-4 gap-1.5 overflow-y-auto rounded-lg border border-zinc-800 p-1.5">
                {selectedReplay.snapshots.map((name) => (
                  <img
                    key={name}
                    src={api.replaySnapshotUrl(selectedReplay.event_id, name)}
                    alt={`${selectedReplay.event_type} ${name}`}
                    className="w-full rounded border border-zinc-800/60"
                  />
                ))}
              </div>
            ) : (
              <EmptyState text="该回放无截图（旧版视频回放不再支持播放）" />
            )
          ) : null}
          <ul className="max-h-40 space-y-1.5 overflow-y-auto">
            {replays.map((replay) => (
              <li key={replay.event_id}>
                <button
                  type="button"
                  onClick={() => setSelected(replay.event_id)}
                  className={`flex w-full items-center justify-between rounded-md px-3 py-1.5 text-left text-xs ${
                    selected === replay.event_id
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "bg-zinc-800/60 hover:bg-zinc-800"
                  }`}
                >
                  <span>
                    {eventLabel(replay.event_type)}
                    <span className="ml-2 text-zinc-500">
                      {replay.snapshots ? `${replay.snapshots.length} 张截图` : `${replay.frame_count} 帧`}
                    </span>
                  </span>
                  <span className="tabular-nums text-zinc-500">
                    {new Date(replay.occurred_at).toLocaleTimeString("zh-CN", {
                      hour12: false,
                    })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

// ---- Snapshot + Label Mode（预留） ----

export function SnapshotPanel({
  api,
  latestEvent,
}: {
  api: MonitorApi;
  latestEvent: MonitorEventItem | null;
}) {
  const [message, setMessage] = useState<string | null>(null);
  const save = async () => {
    try {
      const result = await api.saveSnapshot();
      setMessage(`已保存：${result.image.split("/").pop()}`);
    } catch (e) {
      setMessage(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };
  const label = async (verdict: "correct" | "wrong") => {
    if (!latestEvent) return;
    try {
      await api.label(latestEvent.event_type, verdict);
      setMessage(`已标注 ${verdict === "correct" ? "✔ 正确" : "✖ 错误"}`);
    } catch (e) {
      setMessage(`标注失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };
  return (
    <Card title="快照与标注">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={save}
          className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium hover:bg-emerald-500"
        >
          一键截图
        </button>
        <button
          type="button"
          onClick={() => label("correct")}
          className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs hover:bg-zinc-700"
        >
          ✔ 正确
        </button>
        <button
          type="button"
          onClick={() => label("wrong")}
          className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs hover:bg-zinc-700"
        >
          ✖ 错误
        </button>
      </div>
      {message ? <p className="mt-2 text-xs text-zinc-400">{message}</p> : null}
      <p className="mt-2 text-[11px] text-zinc-600">
        Label Mode 接口已预留：人工确认识别结果，未来自动生成训练数据集。
      </p>
    </Card>
  );
}
