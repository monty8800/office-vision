# yolo-training

Office Vision 自训练数据集工程（独立于 agent/server/dashboard 三个运行时项目）。
负责数据采集、标注、训练；产出的权重文件部署回 `office-vision-agent` 使用。

> 分工约定：**所有训练在 Windows GPU 机器上进行**，Mac 仅消费 `weights/` 下的模型权重，
> 不保留训练数据；训练数据通过私有仓库 `monty8800/office-vision-data` 同步。

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

# 智能自动预标注（用已训练香烟模型批量生成初步标注，人只纠错，大幅减少手工画框）
uv run python scripts/auto_annotate.py --images datasets/cigarette/annotate/smoking

# 标注（labelme 已全局安装）
labelme datasets/cigarette/annotate --labels cigarette

# 转换 + 训练
uv run python scripts/labelme2yolo.py
uv run python scripts/train_cigarette.py
uv run python scripts/train_smoking.py
```

## 模型部署

训练完成后，将 `runs/` 下对应任务的 `best.pt` 复制到 `weights/`（重命名为
`cigarette-best.pt` / `smoking-cls-best.pt`），commit + push 后 Mac 侧拉取即生效
（配置见 `office-vision-agent/config/agent.yaml` 的 `detector.cigarette_weights`，
权重缺失时 Agent 自动降级）。

> 注：`datasets/` 与 `runs/` 含私有训练数据，已在 .gitignore 中排除，仅 `weights/` 入库；
> 标注数据统一托管于私有仓库 `monty8800/office-vision-data`（目录结构与本工程一致，
> clone 后将 `annotate/` 拷入本工程对应位置即可）。

## 经验备忘

- 分类数据务必覆盖各姿态（曾因 smoking 全抬头、normal 全低头导致捷径学习误判）
- 香烟是极小目标：imgsz=640，框宁大勿漏
- **智能标注降低人工成本**：`scripts/auto_annotate.py` 用现有 `cigarette-best.pt` 自动预标注新帧（labelme JSON，与 `labelme2yolo.py` 的 `with_suffix(".json")` 命名一致），人只纠错——比逐张画框省大量时间。**应采集的优先级**：难负样本（Pencil/手表/耳/首饰等被误检为香烟）+ 复现漏检的真实姿态（侧/背角度、远近交替、旋转香烟），这比重复加水印式同场景更能提精度。
- 若仍要进一步提升：可试更大模型（YOLO11s/m）、把 `smoking-cls` 分类模型接入 agent 作确认通道（目前 agent 只用香烟检测+手势融合）。
- `metrics.top1` 等指标是 0-1 比例，打印时记得 ×100
