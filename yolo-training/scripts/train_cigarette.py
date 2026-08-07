"""香烟目标检测模型训练脚本：微调 YOLO11n（本地 M4 MPS 加速）。

用法（项目根目录执行）:
    uv run python scripts/train_cigarette.py                 # 默认 100 epochs
    uv run python scripts/train_cigarette.py --epochs 150    # 自定义轮数
    uv run python scripts/train_cigarette.py --resume        # 恢复上次训练
    uv run python scripts/train_cigarette.py --finetune      # 追加数据后从 best.pt 继续微调

前置步骤:
    1. labelme 完成标注（见 datasets/cigarette/README.md）
    2. uv run python scripts/labelme2yolo.py 生成 YOLO 数据集

产物: runs/detect/cigarette/weights/best.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "datasets" / "cigarette" / "dataset"
DATA_YAML = DATASET_DIR / "data.yaml"

MIN_TRAIN_IMAGES = 100  # 低于该数量训练意义不大
BEST_PT = PROJECT_ROOT / "runs" / "detect" / "cigarette" / "weights" / "best.pt"


def validate_dataset() -> None:
    """校验 labelme2yolo 产物是否就绪。"""
    if not DATA_YAML.exists():
        print(f"未找到 {DATA_YAML}", file=sys.stderr)
        print("请先完成标注，再运行: uv run python scripts/labelme2yolo.py", file=sys.stderr)
        raise SystemExit(1)
    for split in ("train", "val"):
        images = list((DATASET_DIR / "images" / split).glob("*.jpg"))
        labels = list((DATASET_DIR / "labels" / split).glob("*.txt"))
        n_boxes = sum(len(p.read_text().splitlines()) for p in labels)
        print(f"  {split}: {len(images)} 张 / {n_boxes} 个标注框")
        if split == "train" and len(images) < MIN_TRAIN_IMAGES:
            print(f"警告: 训练集仅 {len(images)} 张，建议标注 150+ 张", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="微调 YOLO11n 香烟检测模型")
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数（默认 100）")
    parser.add_argument(
        "--imgsz", type=int, default=640, help="输入尺寸（默认 640，小目标需大尺寸）"
    )
    parser.add_argument("--batch", type=int, default=8, help="批大小（默认 8）")
    parser.add_argument("--resume", action="store_true", help="从上次中断处恢复训练")
    parser.add_argument(
        "--finetune",
        action="store_true",
        help="从已有 best.pt 继续微调（追加数据集后推荐，收敛更快）",
    )
    parser.add_argument("--weights", help="自定义初始权重路径（优先级高于 --finetune）")
    args = parser.parse_args()

    if args.finetune and args.resume:
        print("--finetune 与 --resume 不能同时使用", file=sys.stderr)
        return 1

    print("校验数据集:")
    validate_dataset()

    from ultralytics import YOLO  # noqa: PLC0415

    if args.resume:
        last = PROJECT_ROOT / "runs" / "detect" / "cigarette" / "weights" / "last.pt"
        if not last.exists():
            print(f"找不到可恢复的权重: {last}", file=sys.stderr)
            return 1
        model = YOLO(str(last))
    elif args.weights:
        weights = Path(args.weights)
        if not weights.exists():
            print(f"找不到权重文件: {weights}", file=sys.stderr)
            return 1
        print(f"使用自定义权重微调: {weights}")
        model = YOLO(str(weights))
    elif args.finetune:
        if not BEST_PT.exists():
            print(f"找不到已有权重: {BEST_PT}（首次训练无需 --finetune）", file=sys.stderr)
            return 1
        print(f"从已有权重继续微调: {BEST_PT}")
        model = YOLO(str(BEST_PT))
    else:
        if BEST_PT.exists():
            print("提示: 已存在 best.pt，追加数据后可加 --finetune 从已有权重继续微调")
        model = YOLO("yolo11n.pt")  # 官方检测预训练权重，首次自动下载

    print(f"开始训练（device=mps / epochs={args.epochs} / imgsz={args.imgsz}）")
    model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device="mps",  # Apple Silicon GPU 加速
        patience=30,  # 早停：30 轮无提升即止
        project=str(PROJECT_ROOT / "runs" / "detect"),
        name="cigarette",
        exist_ok=True,
    )

    best = PROJECT_ROOT / "runs" / "detect" / "cigarette" / "weights" / "best.pt"
    metrics = model.val(data=str(DATA_YAML))
    print(f"\n训练完成: {best}")
    map50 = float(metrics.box.map50) * 100
    map5095 = float(metrics.box.map) * 100
    print(f"验证集 mAP50: {map50:.1f}% | mAP50-95: {map5095:.1f}%")
    print("下一步: 将 best.pt 配入 agent.yaml 的 detector.cigarette_weights")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
