"""Debug Center 配置（来自 agent.yaml 的 debug 段）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DebugSettings:
    """enabled=false 时整个 Debug Center 不装配，不影响生产性能。"""

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
    data_dir: str = "data/debug"

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> DebugSettings:
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in config.items() if k in known})
