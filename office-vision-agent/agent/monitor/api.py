"""监控中心 HTTP API（仅开发模式启用，监听 agent.yaml 的 monitor.port）。

端点：
    GET  /monitor/state             当前行为状态 / 插件状态 / 性能 / Overlay 开关
    GET  /monitor/events            Event Timeline（JSON，自动滚动数据源）
    GET  /monitor/logs              实时日志（仅内存环形缓冲，不落盘）
    GET  /monitor/stream            MJPEG 实时画面（含 Overlay）
    GET  /monitor/snapshot.png      最新带 Overlay 画面
    GET  /monitor/raw.png           最新原始帧（无 Overlay，数据集采集用）
    POST /monitor/snapshot          一键截图（图片 + Overlay + Event + 状态）
    POST /monitor/overlays          修改 Overlay 开关 {face: false, ...}
    GET  /monitor/replays           回放列表
    GET  /monitor/replays/{id}/frames/{name}  回放截图浏览（不录视频，节省磁盘）
    POST /monitor/labels            Label Mode 接口（预留）

安全说明：仅供本机开发调试使用，无鉴权；发布版 enabled=false 不会启动。
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from agent.monitor.hub import MonitorHub

_STREAM_FPS = 10


class OverlayChanges(BaseModel):
    """Overlay 开关修改请求（未传的字段保持原值）。"""

    face: bool | None = None
    hand: bool | None = None
    mouth: bool | None = None
    bbox: bool | None = None
    state: bool | None = None
    fps: bool | None = None
    event: bool | None = None
    distance: bool | None = None


class LabelRequest(BaseModel):
    """Label Mode 人工确认请求（接口预留）。"""

    event_id: str
    verdict: str
    note: str = ""


class MarkRequest(BaseModel):
    """标记抽烟事件为误判/正常。

    - verdict: correct=正常(确实抽烟) / wrong=误判(不是抽烟)
    - export_negatives: 误判时是否把回放帧导出为训练负样本（默认 True）
    """

    verdict: str
    note: str = ""
    export_negatives: bool = True


class BoxPayload(BaseModel):
    """一个检测框（像素坐标）。"""

    x1: float
    y1: float
    x2: float
    y2: float


class AnnotateRequest(BaseModel):
    """数据集标注保存请求：把当前帧 + 框存为标注（labelme JSON）。

    - image:      dataURL 或裸 base64 的 JPEG 帧
    - boxes:      画出的香烟框（像素坐标）；negative=True 时忽略并视为负样本
    - label:      标签名（默认 cigarette）
    - negative:   True 表示"此帧无烟"（存到 annotate/normal/，不含框）
    """

    image: str
    boxes: list[BoxPayload] = []
    label: str = "cigarette"
    negative: bool = False
    device_id: str = ""


def _decode_jpeg(data_url_or_b64: str, hub: MonitorHub) -> tuple[bytes, int, int]:
    """解码 dataURL/裸 base64 的 JPEG，返回 (bytes, 宽, 高)。"""
    raw = data_url_or_b64
    if "," in raw[:32] and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    img_bytes = base64.b64decode(raw)
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("图像解码失败（需 JPEG）")
    return img_bytes, img.shape[1], img.shape[0]


def _save_annotation(hub: MonitorHub, req: AnnotateRequest) -> dict[str, Any]:
    """把帧 + 框存为 labelme JSON（正样本 smoking/ 负样本 normal/）。"""
    img_bytes, w, h = _decode_jpeg(req.image, hub)
    sub = "normal" if req.negative else "smoking"
    out_dir = Path(hub.settings.annotate_dir) / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    uniq = f"{ts}-{int(time.time() * 1000) % 1000}"
    img_path = out_dir / f"{uniq}.jpg"
    img_path.write_bytes(img_bytes)

    shapes: list[dict[str, object]] = []
    if not req.negative:
        for b in req.boxes:
            shapes.append(
                {
                    "label": req.label,
                    "points": [[b.x1, b.y1], [b.x2, b.y2]],
                    "group_id": None,
                    "shape_type": "rectangle",
                    "flags": {},
                }
            )
    data = {
        "version": "5.2.0",
        "flags": {},
        "shapes": shapes,
        "imagePath": img_path.name,
        "imageWidth": w,
        "imageHeight": h,
        "imageData": None,
    }
    json_path = out_dir / f"{uniq}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "saved_image": img_path.name,
        "saved_json": json_path.name,
        "boxes": len(shapes),
        "negative": req.negative,
        "recorded_at": ts,
    }


def create_monitor_app(hub: MonitorHub) -> FastAPI:
    app = FastAPI(title="Office Vision Agent - Monitor Center", docs_url="/monitor/docs")

    @app.get("/monitor/state")
    async def state() -> dict[str, Any]:
        return hub.state_snapshot()

    @app.get("/monitor/events")
    async def events(limit: int = 100) -> dict[str, Any]:
        return {"events": hub.timeline(limit)}

    @app.get("/monitor/logs")
    async def logs(limit: int = 200) -> dict[str, Any]:
        return {"logs": hub.logs(limit)}

    @app.get("/monitor/stream")
    async def stream() -> StreamingResponse:
        return StreamingResponse(
            _mjpeg(hub), media_type="multipart/x-mixed-replace; boundary=frame"
        )

    @app.get("/monitor/snapshot.png")
    async def snapshot_png() -> Response:
        jpeg = await asyncio.to_thread(hub.render_jpeg)
        if jpeg is None:
            raise HTTPException(status_code=404, detail="暂无画面")
        return Response(content=jpeg, media_type="image/jpeg")

    @app.get("/monitor/raw.png")
    async def raw_png() -> Response:
        """最新原始帧（无 Overlay），供数据集采集脚本使用。"""
        jpeg = await asyncio.to_thread(hub.render_raw_jpeg)
        if jpeg is None:
            raise HTTPException(status_code=404, detail="暂无画面")
        return Response(content=jpeg, media_type="image/jpeg")

    @app.post("/monitor/snapshot")
    async def snapshot_save() -> dict[str, Any]:
        result = await asyncio.to_thread(hub.save_snapshot)
        if result is None:
            raise HTTPException(status_code=404, detail="暂无画面或快照已禁用")
        return result

    @app.post("/monitor/overlays")
    async def overlays(changes: OverlayChanges) -> dict[str, Any]:
        provided = {k: v for k, v in changes.model_dump().items() if v is not None}
        hub.toggles.update(provided)
        return hub.toggles.as_dict()

    @app.get("/monitor/replays")
    async def replays() -> dict[str, Any]:
        items = await asyncio.to_thread(hub.replay.list_replays)
        for r in items:
            eid = str(r.get("event_id", ""))
            fv: dict[str, str] = {}
            for name in r.get("snapshots") or []:
                v = hub.frame_verdict_for(eid, str(name))
                if v:
                    fv[str(name)] = v
            r["frame_verdicts"] = fv
        return {"replays": items}

    @app.get("/monitor/replays/{event_id}/frames/{name}")
    async def replay_snapshot(event_id: str, name: str) -> FileResponse:
        path = await asyncio.to_thread(hub.replay.snapshot_path, event_id, name)
        if path is None:
            raise HTTPException(status_code=404, detail="回放截图不存在")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/monitor/events/{event_id}/frames/{frame}/mark")
    async def mark_frame(event_id: str, frame: str, request: MarkRequest) -> dict[str, Any]:
        """标记某张回放图片（误判/正常）；误判时导出该帧为训练负样本。"""
        try:
            return await asyncio.to_thread(
                hub.mark_frame, event_id, frame, request.verdict, request.note, request.export_negatives
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/monitor/labels")
    async def labels(request: LabelRequest) -> dict[str, Any]:
        try:
            return hub.record_label(request.event_id, request.verdict, request.note)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/monitor/annotate")
    async def annotate(request: AnnotateRequest) -> dict[str, Any]:
        """保存数据集标注：帧 + 框 → labelme JSON（供 labelme2yolo → 训练）。"""
        try:
            return await asyncio.to_thread(_save_annotation, hub, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


async def _mjpeg(hub: MonitorHub) -> AsyncIterator[bytes]:
    """MJPEG 推流：<img src> 直接可播。"""
    interval = 1.0 / _STREAM_FPS
    while True:
        jpeg = await asyncio.to_thread(hub.render_jpeg)
        if jpeg is not None:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        await asyncio.sleep(interval)
