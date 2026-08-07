"""抽烟行为分类模型训练脚本：微调 YOLO11-cls（本地 M4 MPS 加速）。

用法（项目根目录执行）:
    uv run python scripts/train_smoking.py                 # 默认 50 epochs
    uv run python scripts/train_smoking.py --epochs 100    # 自定义轮数
    uv run python scripts/train_smoking.py --resume        # 恢复上次训练

产物: runs/classify/smoking/weights/best.pt
训练前请确认 dataset/ 已整理好（见 datasets/smoking/README.md）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "datasets" / "smoking" / "dataset"

CLASSES = ("normal", "smoking")
SPLITS = ("train", "val")


def validate_dataset() -> dict[str, int]:
    """校验目录结构与样本量，返回每类样本数。"""
    counts: dict[str, int] = {}
    for split in SPLITS:
        for cls in CLASSES:
            d = DATASET_DIR / split / cls
            n = len(list(d.glob("*.jpg"))) + len(list(d.glob("*.png"))) if d.exists() else 0
            counts[f"{split}/{cls}"] = n
    missing = [k for k, n in counts.items() if n == 0]
    if missing:
        print(f"数据集不完整，以下目录为空或不存在: {missing}", file=sys.stderr)
        print("请先按 datasets/smoking/README.md 采集并整理数据。", file=sys.stderr)
        raise SystemExit(1)
    for k, n in counts.items():
        print(f"  {k}: {n} 张")
    total_train = counts["train/smoking"] + counts["train/normal"]
    if total_train < 100:
        print(f"警告: 训练集仅 {total_train} 张，建议每类 300+ 以获得可用精度", file=sys.stderr)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="微调 YOLO11-cls 抽烟行为分类模型")
    parser.add_argument("--epochs", type=int, default=50, help="训练轮数（默认 50）")
    parser.add_argument("--imgsz", type=int, default=224, help="输入尺寸（默认 224）")
    parser.add_argument("--batch", type=int, default=32, help="批大小（默认 32）")
    parser.add_argument("--resume", action="store_true", help="从上次中断处恢复训练")
    args = parser.parse_args()

    print("校验数据集:")
    validate_dataset()

    from ultralytics import YOLO  # noqa: PLC0415

    if args.resume:
        last = PROJECT_ROOT / "runs" / "classify" / "smoking" / "weights" / "last.pt"
        if not last.exists():
            print(f"找不到可恢复的权重: {last}", file=sys.stderr)
            return 1
        model = YOLO(str(last))
    else:
        model = YOLO("yolo11n-cls.pt")  # 官方分类预训练权重，首次自动下载

    print(f"开始训练（device=mps / epochs={args.epochs} / imgsz={args.imgsz}）")
    model.train(
        data=str(DATASET_DIR),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device="mps",  # Apple Silicon GPU 加速
        project=str(PROJECT_ROOT / "runs" / "classify"),
        name="smoking",
        exist_ok=True,
    )

    best = PROJECT_ROOT / "runs" / "classify" / "smoking" / "weights" / "best.pt"
    metrics = model.val(data=str(DATASET_DIR))
    print(f"\n训练完成: {best}")
    top1 = float(metrics.top1) * 100
    top5 = float(metrics.top5) * 100
    print(f"验证集 top1 精度: {top1:.1f}% | top5: {top5:.1f}%")
    print("下一步: 将 best.pt 接入 agent 的抽烟检测链路")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
