# Office Vision Agent

Office Vision AI 的边缘端：摄像头采集、AI 视觉分析、行为识别、发布事件。

## 边界（架构红线）

| 允许 | 禁止 |
| --- | --- |
| 摄像头采集与视觉推理 | 数据库存储业务数据 |
| 行为识别与事件发布 | Dashboard / 用户管理 |
| 离线时本地 SQLite 缓冲（仅传输队列） | 直接控制 Home Assistant |

## 目录结构

```
office-vision-agent/
├── agent/
│   ├── core/           配置、日志
│   ├── events/         EventBus + 事件类型（阶段2）
│   ├── plugins/        PluginManager（阶段3）
│   ├── presence/       PresenceManager（阶段4）
│   ├── vision/
│   │   ├── camera/     BaseCamera 抽象（阶段5）
│   │   ├── detector/   BaseDetector 抽象（阶段5）
│   │   ├── behavior/   BaseBehaviorDetector（阶段3/5）
│   │   └── pipeline.py 视觉流水线（阶段5）
│   ├── transport/      HTTP 上报 + 离线缓存（阶段6）
│   └── main.py         入口（阶段7）
├── plugins/smoking/    抽烟检测插件（阶段3迁入）
├── config/agent.yaml   唯一配置源
└── tests/
```

## 平台无关原则

摄像头、推理引擎、平台相关代码全部经抽象接口隔离（BaseCamera / BaseDetector），
核心业务逻辑不感知 macOS / Raspberry Pi / Windows / Linux 差异。

## 开发

```bash
uv sync                          # 安装依赖
uv run pytest                    # 测试
uv run ruff check . && uv run black --check . && uv run mypy agent tests
```
