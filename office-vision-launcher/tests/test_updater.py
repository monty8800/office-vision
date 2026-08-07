"""launcher.updater 测试：版本解析与解压权限恢复。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from launcher.updater import _parse_version, _restore_unix_modes


def test_parse_version_handles_v_prefix_and_suffix() -> None:
    assert _parse_version("v0.2.4") == (0, 2, 4)
    assert _parse_version("V1.0") == (1, 0)
    assert _parse_version("v0.2.10") > _parse_version("v0.2.9")


def test_restore_unix_modes_recovers_exec_bit(tmp_path: Path) -> None:
    """extractall 丢失的可执行位必须按 zip 元数据补回（macOS 自更新关键路径）。"""
    src = tmp_path / "launcher"
    src.write_text("#!/bin/sh\n")
    src.chmod(0o755)
    data = tmp_path / "data.txt"
    data.write_text("x")
    data.chmod(0o644)
    zp = tmp_path / "asset.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.write(src, "App.app/Contents/MacOS/launcher")
        zf.write(data, "App.app/config.yaml")
    out = tmp_path / "out"
    with zipfile.ZipFile(zp) as zf:
        zf.extractall(out)
        _restore_unix_modes(zf, out)
    assert (out / "App.app/Contents/MacOS/launcher").stat().st_mode & 0o755 == 0o755
    assert (out / "App.app/config.yaml").stat().st_mode & 0o777 == 0o644
