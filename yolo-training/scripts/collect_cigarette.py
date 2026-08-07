"""香烟检测数据集增量采集脚本：从运行中的 Agent 拉取原始帧（无 Overlay）。

用法（项目根目录执行）:
    # 手持香烟摆出各种漏检姿势时采集（正样本，进标注队列）
    uv run python scripts/collect_cigarette.py --label smoking --count 80

    # 无香烟场景采集负样本（直接进训练，无需标注）
    uv run python scripts/collect_cigarette.py --label normal --count 40 --interval 1.0

采集技巧（针对漏检场景）:
    - 专门复现漏检的角度/距离/光线，每个姿势采 20~30 张
    - 采集时缓慢转动香烟方向、远近交替，增加样本多样性
    - 文件名带时间戳，与已有样本不会冲突

输出目录: datasets/cigarette/annotate/<label>/
后续步骤: labelme 标注 smoking/ 新帧 → labelme2yolo.py → train_cigarette.py
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANNOTATE_DIR = PROJECT_ROOT / "datasets" / "cigarette" / "annotate"


def fetch_frame(base_url: str) -> bytes:
    url = f"{base_url}/debug/raw.png"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="从 Agent 采集原始帧到香烟标注工作区")
    parser.add_argument(
        "--label", required=True, choices=["smoking", "normal"], help="本批帧的类别"
    )
    parser.add_argument("--count", type=int, default=80, help="采集张数（默认 80）")
    parser.add_argument("--interval", type=float, default=0.5, help="采集间隔秒数（默认 0.5）")
    parser.add_argument("--url", default="http://127.0.0.1:8100", help="Agent Debug 服务地址")
    args = parser.parse_args()

    out_dir = ANNOTATE_DIR / args.label
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
        path = out_dir / f"cig-{stamp}-{i:04d}.jpg"
        path.write_bytes(data)
        saved += 1
        if saved % 20 == 0:
            print(f"  已采集 {saved}/{args.count}")
        time.sleep(args.interval)
    print(f"完成: {saved} 张 → {out_dir}")
    if args.label == "smoking":
        print("下一步: labelme 标注新帧 → uv run python scripts/labelme2yolo.py")
    else:
        print("下一步: 直接 uv run python scripts/labelme2yolo.py（负样本无需标注）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
