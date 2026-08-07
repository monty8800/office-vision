"""下载 Office Vision AI 所需的全部模型文件到 models/ 目录。

用法（项目根目录执行）:
    uv run python scripts/download_models.py
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

MEDIAPIPE_MODELS: dict[str, str] = {
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
    "hand_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task"
    ),
}


def download_mediapipe_models() -> None:
    for filename, url in MEDIAPIPE_MODELS.items():
        target = MODELS_DIR / filename
        if target.exists():
            print(f"[skip] {filename} 已存在")
            continue
        print(f"[download] {filename} <- {url}")
        tmp = target.with_suffix(".tmp")
        urllib.request.urlretrieve(url, tmp)  # noqa: S310
        tmp.rename(target)
        print(f"[ok] {filename}")


def download_yolo_weights() -> None:
    target = MODELS_DIR / "yolo11n.pt"
    if target.exists():
        print("[skip] yolo11n.pt 已存在")
        return
    print("[download] yolo11n.pt（通过 ultralytics 自动下载）")
    # ultralytics 会自动从官方 release 下载权重到当前目录
    from ultralytics import YOLO  # noqa: PLC0415

    model = YOLO("yolo11n.pt")
    downloaded = Path(model.ckpt_path or "yolo11n.pt")
    if downloaded.resolve() != target.resolve():
        shutil.copy2(downloaded, target)
    print("[ok] yolo11n.pt")


def main() -> int:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        download_mediapipe_models()
        download_yolo_weights()
    except Exception as exc:  # noqa: BLE001
        print(f"模型下载失败: {exc}", file=sys.stderr)
        return 1
    print("全部模型就绪:", MODELS_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
