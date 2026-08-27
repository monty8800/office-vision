"""用已训练香烟检测模型自动预标注（model-in-the-loop / 自举）。

背景
----
采集到的新帧大多来自与训练集相同场景，用当前 best 模型跑一遍即可得到"大致正确"的
香烟框；人只需要在 labelme / X-AnyLabeling 里纠错（改框、补漏、删误检），再走
labelme2yolo.py。这样把"逐张手工画框"变成"只改错的"，大幅降低标注量。

用法（项目根目录执行）
--------------------
    # 用默认权重+默认 smoking 正样本目录自动预标注
    uv run python scripts/auto_annotate.py

    # 指定帧目录 / 权重 / 置信度 / 标签
    uv run python scripts/auto_annotate.py \
        --images datasets/cigarette/annotate/smoking \
        --weights ../weights/cigarette-best.pt --conf 0.25 --label cigarette

    # 覆盖已存在的 json（默认跳过已标注，怕覆盖人工纠错成果）
    uv run python scripts/auto_annotate.py --images <帧目录> --overwrite

产物
----
与每张图同名的 .json（labelme 格式，shapes 为 rectangle、label=cigarette），供
labelme 打开复核。未检出香烟的帧写入空 shapes 的 json（labelme2yolo.py 会将其视为
"抽烟帧但未标注"，本次不入训练集——需要人工补框）。

负样本（normal 帧）无需跑本脚本：无框即负样本，labelme2yolo.py 会自动当背景处理。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = PROJECT_ROOT / "weights" / "cigarette-best.pt"
DEFAULT_IMAGES = PROJECT_ROOT / "datasets" / "cigarette" / "annotate" / "smoking"
DEFAULT_LABEL = "cigarette"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def _resolve_images_dir(path: str | None) -> Path:
    """解析帧目录：默认为 smoking 正样本工作区。"""
    d = Path(path) if path else DEFAULT_IMAGES
    if not d.is_dir():
        raise SystemExit(f"帧目录不存在: {d}（请先采集，或 --images 指定）")
    return d


def main() -> int:
    parser = argparse.ArgumentParser(description="用已训练香烟检测模型自动预标注")
    parser.add_argument("--images", default=str(DEFAULT_IMAGES), help="待标注帧目录（默认 smoking）")
    parser.add_argument("--weights", default=str(DEFAULT_WEIGHTS), help="香烟检测权重（默认 cigarette-best.pt）")
    parser.add_argument("--conf", type=float, default=0.25, help="置信度阈值（香烟是小目标，默认 0.25）")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="输出 shape 标签名（默认 cigarette）")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的 json")
    args = parser.parse_args()

    weights = Path(args.weights)
    if not weights.exists():
        raise SystemExit(f"找不到权重: {weights}")

    images_dir = _resolve_images_dir(args.images)

    from ultralytics import YOLO  # noqa: PLC0415

    model = YOLO(str(weights))
    print(f"模型: {weights} | 阈值: {args.conf} | 标签: {args.label}")

    images = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise SystemExit(f"{images_dir} 下没有图片")
    print(f"发现 {len(images)} 张帧")

    done = skipped = 0
    for img in images:
        json_path = img.with_suffix(".json")
        if json_path.exists() and not args.overwrite:
            skipped += 1
            continue

        results = model.predict(str(img), conf=args.conf, verbose=False)
        res = results[0]
        h, w = int(res.orig_shape[0]), int(res.orig_shape[1])
        shapes: list[dict[str, object]] = []
        for box in res.boxes:  # type: ignore[union-attr]
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            # 夹紧到图内，过滤小于 1px 的无效框
            x1, x2 = max(0.0, min(x1, x2)), min(float(w), max(x1, x2))
            y1, y2 = max(0.0, min(y1, y2)), min(float(h), max(y1, y2))
            if x2 - x1 < 1 or y2 - y1 < 1:
                continue
            shapes.append(
                {
                    "label": args.label,
                    "points": [[x1, y1], [x2, y2]],
                    "group_id": None,
                    "shape_type": "rectangle",
                    "flags": {},
                }
            )

        data = {
            "version": "5.2.0",
            "flags": {},
            "shapes": shapes,
            "imagePath": img.name,
            "imageWidth": w,
            "imageHeight": h,
            "imageData": None,
        }
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        done += 1
        print(f"  {img.name}: {len(shapes)} 个香烟框")

    print(f"\n完成: 标注 {done} 张，跳过已有 {skipped} 张")
    print("下一步: 用 labelme / X-AnyLabeling 打开复核纠错 -> uv run python scripts/labelme2yolo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
