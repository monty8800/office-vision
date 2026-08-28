"use client";

import { useEffect, useRef, useState } from "react";
import {
  type AnnotateBox,
  type MonitorApi,
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

export function ReplayPanel({
  api,
  replays,
  onFrameVerdict,
}: {
  api: MonitorApi;
  replays: ReplayMeta[];
  onFrameVerdict?: (eventId: string, frame: string, verdict: "correct" | "wrong") => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  // 灯箱：当前查看的截图下标（null=关闭）
  const [viewIdx, setViewIdx] = useState<number | null>(null);
  const selectedReplay = replays.find((r) => r.event_id === selected) ?? null;
  const snaps = selectedReplay?.snapshots ?? [];
  const fv = selectedReplay?.frame_verdicts ?? {};
  const n = snaps.length;
  const currFrame = viewIdx != null ? snaps[viewIdx] : null;
  const currVerdict = currFrame ? fv[currFrame] : undefined;

  const mark = async (frame: string, verdict: "correct" | "wrong") => {
    if (!selectedReplay || !frame) return;
    setBusy(frame);
    setMsg(null);
    try {
      const res = await api.markFrame(selectedReplay.event_id, frame, verdict);
      onFrameVerdict?.(selectedReplay.event_id, frame, verdict);
      const exported = Number(res.exported_negatives ?? 0);
      setMsg(
        verdict === "wrong"
          ? `已标记为误判${exported > 0 ? "，导出该帧到训练负样本" : ""}`
          : "已标记为有烟（正常）"
      );
    } catch (e) {
      setMsg(`标记失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const go = (dir: number) =>
    setViewIdx((i) => (i == null ? null : (i + dir + n) % n));

  // 键盘：←/→ 切换，Esc 关闭
  useEffect(() => {
    if (viewIdx == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setViewIdx(null);
      else if (e.key === "ArrowLeft") {
        e.preventDefault();
        go(-1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        go(1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewIdx, n]);

  // 缩略图角标：误判红 / 有烟绿
  const frameBadge = (verdict?: string) => {
    if (verdict === "wrong")
      return (
        <span className="absolute right-1 top-1 rounded bg-red-500/85 px-1 py-0.5 text-[9px] font-medium text-white">
          误判
        </span>
      );
    if (verdict === "correct")
      return (
        <span className="absolute right-1 top-1 rounded bg-emerald-500/85 px-1 py-0.5 text-[9px] font-medium text-white">
          有烟
        </span>
      );
    return null;
  };

  // 已标记帧数汇总（列表行展示）
  const markedCount = (replay: ReplayMeta) =>
    Object.values(replay.frame_verdicts ?? {}).length;

  return (
    <>
      <Card title="事件回放（事件前 10s + 过程 + 后 10s · 截图模式）">
        {replays.length === 0 ? (
          <EmptyState text="暂无回放（触发开始抽烟/抽烟结束事件后自动生成）" />
        ) : (
          <div className="space-y-2">
            <p className="text-[10px] text-zinc-600">
              提示：双击截图可查看大图并标记（方向键切换 / Esc 关闭）
            </p>
            {msg && <p className="rounded bg-zinc-800 px-2 py-1 text-xs text-emerald-300">{msg}</p>}
            {selectedReplay ? (
              selectedReplay.snapshots && selectedReplay.snapshots.length > 0 ? (
                <div className="grid max-h-64 grid-cols-4 gap-1.5 overflow-y-auto rounded-lg border border-zinc-800 p-1.5">
                  {selectedReplay.snapshots.map((name, idx) => (
                    <div key={name} className="relative">
                      <img
                        src={api.replaySnapshotUrl(selectedReplay.event_id, name)}
                        alt={`${selectedReplay.event_type} ${name}`}
                        onDoubleClick={() => setViewIdx(idx)}
                        className="w-full cursor-zoom-in rounded border border-zinc-800/60 transition hover:border-emerald-400/60"
                      />
                      {frameBadge(fv[name])}
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState text="该回放无截图（旧版视频回放不再支持播放）" />
              )
            ) : null}
            <ul className="max-h-40 space-y-1.5 overflow-y-auto">
              {replays.map((replay) => (
                <li
                  key={replay.event_id}
                  className={`flex items-center justify-between rounded-md px-3 py-1.5 text-xs ${
                    selected === replay.event_id ? "bg-emerald-500/15 text-emerald-300" : "bg-zinc-800/60"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => setSelected(replay.event_id)}
                    className="flex w-full items-center justify-between text-left"
                  >
                    <span className="flex items-center gap-2">
                      {eventLabel(replay.event_type)}
                      <span className="text-zinc-500">
                        {replay.snapshots ? `${replay.snapshots.length} 张截图` : `${replay.frame_count} 帧`}
                        {markedCount(replay) > 0 && (
                          <span className="ml-1 text-emerald-400/80">· 已标记 {markedCount(replay)}</span>
                        )}
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

      {/* 大图灯箱（可标记当前图片） */}
      {viewIdx !== null && selectedReplay && currFrame ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4"
          onClick={() => setViewIdx(null)}
        >
          <button
            type="button"
            aria-label="关闭"
            onClick={(e) => {
              e.stopPropagation();
              setViewIdx(null);
            }}
            className="absolute right-4 top-4 z-10 rounded-full bg-zinc-800/80 px-3 py-1 text-lg text-zinc-300 hover:bg-zinc-700 hover:text-white"
          >
            ✕
          </button>
          <button
            type="button"
            aria-label="上一张"
            onClick={(e) => {
              e.stopPropagation();
              go(-1);
            }}
            className="absolute left-3 top-1/2 z-10 -translate-y-1/2 rounded-full bg-zinc-800/80 px-3 py-2 text-2xl text-zinc-200 hover:bg-zinc-700 hover:text-white"
          >
            ‹
          </button>
          <button
            type="button"
            aria-label="下一张"
            onClick={(e) => {
              e.stopPropagation();
              go(1);
            }}
            className="absolute right-3 top-1/2 z-10 -translate-y-1/2 rounded-full bg-zinc-800/80 px-3 py-2 text-2xl text-zinc-200 hover:bg-zinc-700 hover:text-white"
          >
            ›
          </button>
          <div className="relative max-h-[92vh] max-w-[92vw]" onClick={(e) => e.stopPropagation()}>
            <img
              src={api.replaySnapshotUrl(selectedReplay.event_id, currFrame)}
              alt={`${selectedReplay.event_type} ${currFrame}`}
              className="max-h-[82vh] max-w-[90vw] rounded object-contain shadow-2xl"
            />
            <div className="mt-2 flex items-center justify-center gap-2 text-sm">
              <span className="tabular-nums text-zinc-300">
                {viewIdx + 1} / {n}
              </span>
              <span className="mx-2 h-3 w-px bg-zinc-700" />
              <span className="text-xs text-zinc-400">标记：</span>
              <button
                type="button"
                disabled={busy === currFrame}
                onClick={() => mark(currFrame, "wrong")}
                className={`rounded px-2 py-0.5 text-xs transition-colors disabled:opacity-50 ${
                  currVerdict === "wrong"
                    ? "bg-red-500/30 text-red-200"
                    : "bg-zinc-800 text-zinc-400 hover:bg-red-500/20 hover:text-red-300"
                }`}
              >
                误判
              </button>
              <button
                type="button"
                disabled={busy === currFrame}
                onClick={() => mark(currFrame, "correct")}
                className={`rounded px-2 py-0.5 text-xs transition-colors disabled:opacity-50 ${
                  currVerdict === "correct"
                    ? "bg-emerald-500/30 text-emerald-200"
                    : "bg-zinc-800 text-zinc-400 hover:bg-emerald-500/20 hover:text-emerald-300"
                }`}
              >
                有烟
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
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
