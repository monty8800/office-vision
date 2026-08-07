"""本地发布兜底脚本（RFC-0008）：正式发布渠道为 GitHub Actions。

调用当前平台的 build/ 脚本打包，可选经 gh CLI 创建 GitHub Release。

用法（在本子项目目录执行）：
    uv run python scripts/release.py            # 打包 + 创建 Release + 上传全部产物
    uv run python scripts/release.py --build    # 仅打包，产物在 dist/

版本号以 launcher/__init__.py 的 __version__ 为准。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_version() -> str:
    text = (ROOT / "launcher" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("无法从 launcher/__init__.py 读取 __version__")
    return match.group(1)


def build() -> None:
    """委托当前平台的 build/ 脚本（RFC-0008：打包逻辑统一在 build/ 目录）。"""
    if sys.platform == "win32":
        subprocess.run(["pwsh", str(ROOT / "build" / "windows.ps1")], check=True)
    else:
        subprocess.run(["sh", str(ROOT / "build" / "macos.sh")], check=True)


def publish(version: str) -> None:
    """创建 Release 并上传 dist/ 全部产物（tag 已存在时覆盖上传）。"""
    artifacts = sorted(p for p in (ROOT / "dist").iterdir()
                       if p.is_file() and p.suffix in {".zip", ".dmg", ".exe"})
    if not artifacts:
        raise SystemExit("dist/ 中没有可发布产物，请先打包")
    tag = f"v{version}"
    result = subprocess.run(["gh", "release", "view", tag], capture_output=True)
    if result.returncode == 0:
        print(f"Release {tag} 已存在，覆盖上传产物")
        subprocess.run(["gh", "release", "upload", tag, *map(str, artifacts), "--clobber"],
                       check=True)
    else:
        subprocess.run(
            ["gh", "release", "create", tag, *map(str, artifacts),
             "--title", tag, "--notes", f"Office Vision Tray v{version}"],
            check=True,
        )
    print(f"已发布 {tag}：" + ", ".join(p.name for p in artifacts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="仅打包，不发布")
    args = parser.parse_args()

    build()
    if not args.build:
        publish(read_version())


if __name__ == "__main__":
    main()
