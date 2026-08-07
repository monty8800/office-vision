"""Debug Center HTTP API（仅开发模式启用，监听 agent.yaml 的 debug.port）。

端点：
    GET  /debug/state             当前行为状态 / 插件状态 / 性能 / Overlay 开关
    GET  /debug/events            Event Timeline（JSON，自动滚动数据源）
    GET  /debug/logs              实时日志（仅内存环形缓冲，不落盘）
    GET  /debug/stream            MJPEG 实时画面（含 Overlay）
    GET  /debug/snapshot.png      最新带 Overlay 画面
    GET  /debug/raw.png           最新原始帧（无 Overlay，数据集采集用）
    POST /debug/snapshot          一键截图（图片 + Overlay + Event + 状态）
    POST /debug/overlays          修改 Overlay 开关 {face: false, ...}
    GET  /debug/replays           回放列表
    GET  /debug/replays/{id}.mp4  回放视频播放
    POST /debug/labels            Label Mode 接口（预留）

安全说明：仅供本机开发调试使用，无鉴权；发布版 enabled=false 不会启动。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from agent.debug.hub import DebugHub

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


def create_debug_app(hub: DebugHub) -> FastAPI:
    app = FastAPI(title="Office Vision Agent - Debug Center", docs_url="/debug/docs")

    @app.get("/debug/state")
    async def state() -> dict[str, Any]:
        return hub.state_snapshot()

    @app.get("/debug/events")
    async def events(limit: int = 100) -> dict[str, Any]:
        return {"events": hub.timeline(limit)}

    @app.get("/debug/logs")
    async def logs(limit: int = 200) -> dict[str, Any]:
        return {"logs": hub.logs(limit)}

    @app.get("/debug/stream")
    async def stream() -> StreamingResponse:
        return StreamingResponse(
            _mjpeg(hub), media_type="multipart/x-mixed-replace; boundary=frame"
        )

    @app.get("/debug/snapshot.png")
    async def snapshot_png() -> Response:
        jpeg = await asyncio.to_thread(hub.render_jpeg)
        if jpeg is None:
            raise HTTPException(status_code=404, detail="暂无画面")
        return Response(content=jpeg, media_type="image/jpeg")

    @app.get("/debug/raw.png")
    async def raw_png() -> Response:
        """最新原始帧（无 Overlay），供数据集采集脚本使用。"""
        jpeg = await asyncio.to_thread(hub.render_raw_jpeg)
        if jpeg is None:
            raise HTTPException(status_code=404, detail="暂无画面")
        return Response(content=jpeg, media_type="image/jpeg")

    @app.post("/debug/snapshot")
    async def snapshot_save() -> dict[str, Any]:
        result = await asyncio.to_thread(hub.save_snapshot)
        if result is None:
            raise HTTPException(status_code=404, detail="暂无画面或快照已禁用")
        return result

    @app.post("/debug/overlays")
    async def overlays(changes: OverlayChanges) -> dict[str, Any]:
        provided = {k: v for k, v in changes.model_dump().items() if v is not None}
        hub.toggles.update(provided)
        return hub.toggles.as_dict()

    @app.get("/debug/replays")
    async def replays() -> dict[str, Any]:
        return {"replays": await asyncio.to_thread(hub.replay.list_replays)}

    @app.get("/debug/replays/{event_id}.mp4")
    async def replay_video(event_id: str) -> FileResponse:
        path = await asyncio.to_thread(hub.replay.video_path, event_id)
        if path is None:
            raise HTTPException(status_code=404, detail="回放不存在")
        return FileResponse(path, media_type="video/mp4")

    @app.post("/debug/labels")
    async def labels(request: LabelRequest) -> dict[str, Any]:
        try:
            return hub.record_label(request.event_id, request.verdict, request.note)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


async def _mjpeg(hub: DebugHub) -> AsyncIterator[bytes]:
    """MJPEG 推流：<img src> 直接可播。"""
    interval = 1.0 / _STREAM_FPS
    while True:
        jpeg = await asyncio.to_thread(hub.render_jpeg)
        if jpeg is not None:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        await asyncio.sleep(interval)
