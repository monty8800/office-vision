"""把 labelme 标注结果转换为 YOLO 检测数据集。

用法（项目根目录执行）:
    uv run python scripts/labelme2yolo.py

输入:  datasets/cigarette/annotate/{smoking,normal}/*.jpg + 同名 .json（labelme 产物）
输出:  datasets/cigarette/dataset/
       ├── images/{train,val}/
       ├── labels/{train,val}/
       └── data.yaml

无标注 json 的图片视为负样本（背景图，不含目标）。
train:val 按 8:2 随机拆分（类别分层，固定种子可复现）。
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANNOTATE_DIR = PROJECT_ROOT / "datasets" / "cigarette" / "annotate"
OUTPUT_DIR = PROJECT_ROOT / "datasets" / "cigarette" / "dataset"
CLASSES = ["cigarette"]
VAL_RATIO = 0.2
SEED = 42


def parse_labelme_json(json_path: Path) -> list[tuple[float, float, float, float]] | None:
    """解析单个 labelme 标注文件，返回归一化 (cx, cy, w, h) 列表。

    返回 None 表示该图无 json（负样本）；空列表表示 json 存在但无目标。
    """
    if not json_path.exists():
        return None
    data = json.loads(json_path.read_text(encoding="utf-8"))
    boxes: list[tuple[float, float, float, float]] = []
    img_w, img_h = data["imageWidth"], data["imageHeight"]
    for shape in data.get("shapes", []):
        if shape.get("label") != CLASSES[0]:
            continue
        points = shape["points"]
        if shape.get("shape_type") == "rectangle" and len(points) == 2:
            (x1, y1), (x2, y2) = points
        else:  # 多边形取外接矩形
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
        x1, x2 = max(0.0, min(x1, x2)), min(float(img_w), max(x1, x2))
        y1, y2 = max(0.0, min(y1, y2)), min(float(img_h), max(y1, y2))
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        boxes.append(
            (
                (x1 + x2) / 2 / img_w,
                (y1 + y2) / 2 / img_h,
                (x2 - x1) / img_w,
                (y2 - y1) / img_h,
            )
        )
    return boxes


def collect_entries() -> list[tuple[Path, bool, list[tuple[float, float, float, float]]]]:
    """收集全部图片: (路径, 是否正样本目录, 标注框列表)。"""
    entries: list[tuple[Path, bool, list[tuple[float, float, float, float]]]] = []
    for sub in sorted(p for p in ANNOTATE_DIR.iterdir() if p.is_dir()):
        for img in sorted(sub.glob("*.jpg")):
            boxes = parse_labelme_json(img.with_suffix(".json"))
            entries.append((img, sub.name == "smoking", boxes or []))
    return entries


def main() -> int:
    entries = collect_entries()
    if not entries:
        print(f"未在 {ANNOTATE_DIR} 找到图片", flush=True)
        return 1

    positives = [e for e in entries if e[1] and e[2]]
    unannotated = [e for e in entries if e[1] and not e[2]]
    negatives = [e for e in entries if not e[1]]
    print(f"正样本（含香烟框）: {len(positives)} 张")
    print(f"抽烟帧但未标注: {len(unannotated)} 张（本次不参与训练）")
    print(f"负样本（背景）: {len(negatives)} 张")
    if len(positives) < 50:
        print("警告: 已标注正样本少于 50 张，建议至少标注 150 张再训练", flush=True)

    random.seed(SEED)
    random.shuffle(positives)
    random.shuffle(negatives)
    n_pos_val = round(len(positives) * VAL_RATIO)
    n_neg_val = round(len(negatives) * VAL_RATIO)
    splits = {
        "val": positives[:n_pos_val] + negatives[:n_neg_val],
        "train": positives[n_pos_val:] + negatives[n_neg_val:],
    }

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    for split, items in splits.items():
        (OUTPUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)
        for img, _, boxes in items:
            shutil.copy(img, OUTPUT_DIR / "images" / split / img.name)
            txt = OUTPUT_DIR / "labels" / split / (img.stem + ".txt")
            if boxes:  # 负样本不写标签文件（ultralytics 视为背景图）
                lines = [f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for cx, cy, w, h in boxes]
                txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{split}: {len(items)} 张")

    yaml_path = OUTPUT_DIR / "data.yaml"
    yaml_path.write_text(
        f"path: {OUTPUT_DIR}\n"
        "train: images/train\n"
        "val: images/val\n"
        f"names: [{', '.join(CLASSES)}]\n",
        encoding="utf-8",
    )
    print(f"数据集已生成: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
