"""监控中心配置（来自 agent.yaml 的 monitor 段）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MonitorSettings:
    """enabled=false 时整个监控中心不装配，不影响生产性能。"""

    enabled: bool = False
    overlay: bool = True
    performance: bool = True
    timeline: bool = True
    replay: bool = True
    save_snapshot: bool = True
    replay_before_seconds: float = 10.0
    replay_after_seconds: float = 10.0
    replay_snapshot_interval: float = 1.0
    frame_buffer_seconds: float = 30.0
    port: int = 8100
    host: str = "127.0.0.1"  # 跨设备采集/调试时可在 agent.yaml 改为 0.0.0.0
    data_dir: str = "data/monitor"
    annotate_dir: str = "data/annotate"  # 页面标注产出的图像+labelme JSON 目录（相对 agent 项目根）

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> MonitorSettings:
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in config.items() if k in known})
