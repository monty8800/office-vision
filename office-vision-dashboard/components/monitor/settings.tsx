"use client";

import { useEffect, useRef, useState } from "react";
import {
  type AnnotateBox,
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

// ---- 数据集标注：冻结当前帧 → 拖框 → 保存为 labelme JSON （供 labelme2yolo → 训练） ----

type DragBox = { x1: number; y1: number; x2: number; y2: number };

export function AnnotationPanel({ api }: { api: MonitorApi }) {
  const [active, setActive] = useState(false);
  const [imgSrc, setImgSrc] = useState<string | null>(null);
  const [natW, setNatW] = useState(0);
  const [natH, setNatH] = useState(0);
  const [boxes, setBoxes] = useState<AnnotateBox[]>([]);
  const [drag, setDrag] = useState<DragBox | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const loadFrame = async () => {
    const res = await fetch(api.rawFrameUrl, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const dataUrl = await new Promise<string>((resolve) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result as string);
      r.readAsDataURL(blob);
    });
    setImgSrc(dataUrl);
    setBoxes([]);
  };

  const fetchFrame = async () => {
    setMsg("加载当前帧…");
    try {
      await loadFrame();
      setMsg(null);
    } catch (e) {
      setMsg(`加载帧失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // 进入标注模式即自动获取当前帧
  useEffect(() => {
    if (active) void fetchFrame();
  }, [active]);

  const onImgLoad = () => {
    if (imgRef.current) {
      setNatW(imgRef.current.naturalWidth);
      setNatH(imgRef.current.naturalHeight);
    }
  };

  useEffect(() => {
    const c = canvasRef.current;
    if (!c || !imgSrc) return;
    c.width = natW;
    c.height = natH;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, natW, natH);
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = Math.max(2, natW / 300);
    ctx.font = `bold ${Math.max(14, natW / 40)}px sans-serif`;
    ctx.strokeRect(0, 0, natW, natH);
    for (const b of boxes) {
      ctx.strokeRect(b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1);
    }
    if (drag) {
      ctx.strokeRect(drag.x1, drag.y1, drag.x2 - drag.x1, drag.y2 - drag.y1);
    }
  }, [natW, natH, boxes, drag, imgSrc]);

  const toImageCoords = (e: React.PointerEvent) => {
    const c = canvasRef.current;
    if (!c) return null;
    const rect = c.getBoundingClientRect();
    const sx = c.width / Math.max(1, rect.width);
    const sy = c.height / Math.max(1, rect.height);
    const x = (e.clientX - rect.left) * sx;
    const y = (e.clientY - rect.top) * sy;
    return { x: Math.max(0, Math.min(c.width, x)), y: Math.max(0, Math.min(c.height, y)) };
  };

  const onDown = (e: React.PointerEvent) => {
    const p = toImageCoords(e);
    if (p) {
      setDrag({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    }
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const p = toImageCoords(e);
    if (p) setDrag((d) => (d ? { ...d, x2: p.x, y2: p.y } : d));
  };
  const onUp = () => {
    if (drag) {
      const b: AnnotateBox = {
        x1: Math.min(drag.x1, drag.x2),
        y1: Math.min(drag.y1, drag.y2),
        x2: Math.max(drag.x1, drag.x2),
        y2: Math.max(drag.y1, drag.y2),
      };
      if (b.x2 - b.x1 > 4 && b.y2 - b.y1 > 4) setBoxes((bs) => [...bs, b]);
      setDrag(null);
    }
  };

  const save = async (negative: boolean) => {
    if (!imgSrc) return;
    if (!negative && boxes.length === 0) {
      setMsg("请先拖框标注香烟，或改用「保存为负样本」");
      return;
    }
    setMsg("保存…");
    try {
      const r = await api.annotate({
        image: imgSrc,
        boxes: negative ? [] : boxes,
        label: "cigarette",
        negative,
        device_id: "",
      });
      // 保存后自动获取下一帧继续标注（不退出标注模式）
      const savedMsg = `已保存：${r.saved_image}（${negative ? "负样本" : `${r.boxes} 框`}）`;
      try {
        await loadFrame();
      } catch {
        setBoxes([]);
        setImgSrc(null);
      }
      setMsg(savedMsg);
    } catch (e) {
      setMsg(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <Card title="数据集标注（冻结当前帧 → 拖框 → 保存）">
      {!active ? (
        <button
          type="button"
          onClick={() => setActive(true)}
          className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium hover:bg-emerald-500"
        >
          进入标注模式
        </button>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={fetchFrame}
              className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs hover:bg-zinc-700"
            >
              获取当前帧
            </button>
            <button
              type="button"
              onClick={() => setBoxes([])}
              className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs hover:bg-zinc-700"
            >
              清空框
            </button>
            <button
              type="button"
              onClick={() => save(true)}
              className="rounded-md bg-amber-600 px-3 py-1.5 text-xs hover:bg-amber-500"
            >
              保存为负样本
            </button>
            <button
              type="button"
              onClick={() => save(false)}
              className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium hover:bg-emerald-500"
            >
              保存标注（{boxes.length} 框）
            </button>
            <button
              type="button"
              onClick={() => setActive(false)}
              className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs hover:bg-zinc-700"
            >
              退出
            </button>
          </div>
          {msg ? <p className="text-xs text-zinc-400">{msg}</p> : null}
          {imgSrc ? (
            <div className="relative overflow-hidden rounded border border-zinc-800">
              <img
                ref={imgRef}
                src={imgSrc}
                onLoad={onImgLoad}
                alt="待标注帧"
                className="w-full select-none"
                draggable={false}
              />
              <canvas
                ref={canvasRef}
                className="absolute inset-0 h-full w-full cursor-crosshair"
                onPointerDown={onDown}
                onPointerMove={onMove}
                onPointerUp={onUp}
              />
            </div>
          ) : (
            <p className="text-xs text-zinc-600">
              点击「获取当前帧」冻结画面，然后在图上拖框标注香烟。
            </p>
          )}
          <p className="text-[11px] text-zinc-600">
            规则：烟在手上或嘴里才算抽烟；放桌上请点「保存为负样本」。
          </p>
        </div>
      )}
    </Card>
  );
}
