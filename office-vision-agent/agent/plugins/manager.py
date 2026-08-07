"""PluginManager：行为检测插件的发现、加载与生命周期管理。

插件规范（plugins/<name>/）:
    plugin.py     暴露 create_detector(device_id, config) -> BaseBehaviorDetector
    config.yaml   插件私有配置
    README.md     插件说明

生命周期：
- load_all()     扫描目录并实例化全部插件
- suspend()      Presence 休眠时停用全部插件（不卸载）
- resume()       Presence 恢复时重新启用
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml
from loguru import logger

from agent.events.types import Event
from agent.vision.behavior.base import BaseBehaviorDetector
from agent.vision.frame import VisionContext


class PluginLoadError(Exception):
    """插件加载失败。"""


class PluginManager:
    """管理全部行为检测插件。"""

    def __init__(self, plugins_root: Path, device_id: str) -> None:
        self._root = plugins_root
        self._device_id = device_id
        self._detectors: list[BaseBehaviorDetector] = []

    @property
    def detectors(self) -> list[BaseBehaviorDetector]:
        return list(self._detectors)

    @property
    def names(self) -> list[str]:
        return [d.name for d in self._detectors]

    def debug_infos(self) -> list[dict[str, Any]]:
        """各插件的内部状态快照（Debug Center 诊断用）。"""
        infos: list[dict[str, Any]] = []
        for detector in self._detectors:
            try:
                info = detector.debug_info()
            except Exception:
                logger.exception("插件 {} debug_info 失败", detector.name)
                info = {}
            infos.append({"name": detector.name, **info})
        return infos

    def load_all(self) -> list[BaseBehaviorDetector]:
        """扫描插件目录；单个插件失败不影响其他插件。"""
        self._detectors = []
        if not self._root.exists():
            logger.warning("插件目录不存在: {}", self._root)
            return []
        for plugin_dir in sorted(self._root.iterdir()):
            if not plugin_dir.is_dir() or plugin_dir.name.startswith((".", "_")):
                continue
            if not (plugin_dir / "plugin.py").exists():
                continue
            try:
                detector = self._load_one(plugin_dir)
                self._detectors.append(detector)
                logger.info("插件已加载: {}", detector.name)
            except PluginLoadError as exc:
                logger.error("插件加载失败: {}", exc)
            except Exception:
                logger.exception("插件加载异常: {}", plugin_dir.name)
        return self._detectors

    def _load_one(self, plugin_dir: Path) -> BaseBehaviorDetector:
        module_path = plugin_dir / "plugin.py"
        module_name = f"ova_plugin_{plugin_dir.name}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"{plugin_dir.name}: 无法创建模块 spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        # 临时加入 sys.path，支持插件内部相对导入（如 from detector import ...）
        dir_str = str(plugin_dir)
        sys.path.insert(0, dir_str)
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(dir_str)

        factory = getattr(module, "create_detector", None)
        if not callable(factory):
            raise PluginLoadError(f"{plugin_dir.name}: plugin.py 未暴露 create_detector()")
        create = cast("Callable[[str, dict[str, Any]], BaseBehaviorDetector]", factory)
        detector = create(self._device_id, self._load_config(plugin_dir))
        if not isinstance(detector, BaseBehaviorDetector):
            raise PluginLoadError(f"{plugin_dir.name}: 返回值不是 BaseBehaviorDetector")
        return detector

    @staticmethod
    def _load_config(plugin_dir: Path) -> dict[str, Any]:
        config_path = plugin_dir / "config.yaml"
        if not config_path.exists():
            return {}
        with config_path.open(encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
            return cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else {}

    # ---- Presence 生命周期联动 ----

    def suspend(self) -> None:
        for detector in self._detectors:
            detector.disable()
        logger.info("全部插件已停用（休眠）")

    def resume(self) -> None:
        for detector in self._detectors:
            detector.enable()
        logger.info("全部插件已恢复")

    def process_frame(self, context: VisionContext) -> list[Event]:
        """将视觉上下文分发给全部启用的插件，汇总产出的事件。"""
        events: list[Event] = []
        for detector in self._detectors:
            if not detector.enabled:
                continue
            try:
                events.extend(detector.on_frame(context))
            except Exception:
                logger.exception("插件 {} 处理失败", detector.name)
        return events
