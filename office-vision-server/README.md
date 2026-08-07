# Office Vision Server

Office Vision AI 的服务端：事件接收与处理、PostgreSQL 存储、Dashboard API、自动化联动。

## 边界（架构红线）

| 允许 | 禁止 |
| --- | --- |
| 接收 Agent 事件并持久化 | 接触摄像头 / 视觉推理 |
| Dashboard 查询 API | 直接调用检测逻辑 |
| 订阅事件触发 Home Assistant 联动 | 绕过事件直接控制设备 |

## 目录结构

```
office-vision-server/
├── server/
│   ├── core/        配置、日志（阶段7）
│   ├── events/      事件契约与处理器分发（阶段2/6）
│   ├── api/routes/  events 接收 + stats 查询（阶段6/7）
│   ├── database/    SQLAlchemy 2 + PostgreSQL + Alembic（阶段6）
│   ├── automation/  Home Assistant 联动（后续版本）
│   └── main.py      FastAPI 入口（阶段6/7）
├── config/server.yaml
└── tests/
```

## 开发

```bash
uv sync
uv run pytest
uv run ruff check . && uv run black --check . && uv run mypy server tests
```
