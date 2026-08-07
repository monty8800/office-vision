"""抽烟数据集帧采集脚本：从运行中的 Agent 拉取原始帧（无 Overlay）。

用法（项目根目录执行）:
    # 模拟抽烟姿势时采集 100 张，每 0.5 秒一张
    uv run python scripts/collect_dataset.py --label smoking --count 100

    # 正常办公状态采集负样本
    uv run python scripts/collect_dataset.py --label normal --count 100 --interval 1.0

采集前请确认 Agent 正在运行且画面正常（Debug 页可见）。
输出目录: datasets/smoking/raw/<label>/
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "datasets" / "smoking" / "raw"


def fetch_frame(base_url: str) -> bytes:
    url = f"{base_url}/debug/raw.png"
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        return resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="从 Agent 采集原始帧到数据集 raw/ 目录")
    parser.add_argument(
        "--label", required=True, choices=["smoking", "normal"], help="本批帧的类别"
    )
    parser.add_argument("--count", type=int, default=100, help="采集张数（默认 100）")
    parser.add_argument("--interval", type=float, default=0.5, help="采集间隔秒数（默认 0.5）")
    parser.add_argument("--url", default="http://127.0.0.1:8100", help="Agent Debug 服务地址")
    args = parser.parse_args()

    out_dir = RAW_DIR / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    saved = 0
    out_rel = out_dir.relative_to(PROJECT_ROOT)
    print(f"开始采集: {args.count} 张 → {out_rel}（间隔 {args.interval}s）")
    for i in range(args.count):
        try:
            data = fetch_frame(args.url)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"拉帧失败（Agent 是否在运行？）: {exc}", file=sys.stderr)
            return 1
        path = out_dir / f"{stamp}-{i:04d}.jpg"
        path.write_bytes(data)
        saved += 1
        if saved % 20 == 0:
            print(f"  已采集 {saved}/{args.count}")
        time.sleep(args.interval)
    print(f"完成: {saved} 张 → {out_dir}")
    print("下一步: 把 raw/ 图片整理到 dataset/<train|val>/<smoking|normal>/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
