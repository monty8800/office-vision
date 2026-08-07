# yolo-training

Office Vision 自训练数据集工程（独立于 agent/server/dashboard 三个运行时项目）。
负责数据采集、标注、训练；产出的权重文件部署回 `office-vision-agent` 使用。

## 目录结构

```
yolo-training/
├── datasets/
│   ├── smoking/           # 抽烟行为分类数据集（normal / smoking 二分类）
│   │   ├── raw/           # collect_dataset.py 采集的原始帧
│   │   └── dataset/       # 整理后的 train/val（YOLO11-cls 目录格式）
│   └── cigarette/         # 香烟目标检测数据集（详见其 README.md）
│       ├── annotate/      # labelme 标注工作区
│       └── dataset/       # labelme2yolo.py 生成（YOLO 格式）
├── scripts/
│   ├── collect_dataset.py # 从运行中的 Agent 拉帧采集（/debug/raw.png）
│   ├── labelme2yolo.py    # labelme 标注 → YOLO 数据集
│   ├── train_smoking.py   # 训练行为分类模型（YOLO11-cls）
│   └── train_cigarette.py # 训练香烟检测模型（YOLO11n）
├── weights/               # 已入库的训练产出权重
│   ├── cigarette-best.pt  # 香烟检测模型（mAP50 97.5%）
│   └── smoking-cls-best.pt# 抽烟行为分类模型
└── runs/                  # 训练中间产物（不入库，含训练画面可视化）
    ├── classify/smoking/weights/best.pt   # 分类模型
    └── detect/cigarette/weights/best.pt   # 检测模型（mAP50 97.5%）
```

## 常用命令（本项目根目录执行）

```bash
# 采集（需 Agent 在 :8100 运行）
uv run python scripts/collect_dataset.py --label smoking --count 100

# 标注（labelme 已全局安装）
labelme datasets/cigarette/annotate --labels cigarette

# 转换 + 训练
uv run python scripts/labelme2yolo.py
uv run python scripts/train_cigarette.py
uv run python scripts/train_smoking.py
```

## 模型部署

训练完成后，将 `runs/` 下对应任务的 `best.pt` 复制到 `weights/`（重命名为
`cigarette-best.pt` / `smoking-cls-best.pt`），并配置到
`office-vision-agent/config/agent.yaml`（如 `detector.cigarette_weights`），
权重缺失时 Agent 自动降级。

> 注：`datasets/` 与 `runs/` 含私有训练数据，已在 .gitignore 中排除，仅 `weights/` 入库。

## 经验备忘

- 分类数据务必覆盖各姿态（曾因 smoking 全抬头、normal 全低头导致捷径学习误判）
- 香烟是极小目标：imgsz=640，框宁大勿漏
- `metrics.top1` 等指标是 0-1 比例，打印时记得 ×100
