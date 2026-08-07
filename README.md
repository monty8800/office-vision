# Office Vision AI

AI-powered Office Behavior Analysis Platform —— 基于 AI 视觉的办公室行为分析与自动化平台。

定位为个人行为统计、健康分析与办公自动化（Home Assistant 联动），而非员工监控。

## 系统架构（三项目分离）

```
┌─────────────────────┐         HTTP API          ┌──────────────────────┐
│ office-vision-agent │  ────── 事件上报 ───────► │ office-vision-server │
│ （Mac / Pi / 跨平台）│   ◄──── 配置/状态 ──────  │ （本地或云服务器）    │
│ 摄像头+AI识别+发事件 │   （离线时 SQLite 缓存）   │ FastAPI + PostgreSQL │
└─────────────────────┘                           └──────────┬───────────┘
                                                             │ REST API
                                                  ┌──────────▼───────────┐
                                                  │office-vision-dashboard│
                                                  │     Next.js 16       │
                                                  └──────────────────────┘
```

| 项目 | 职责 | 禁止 |
| --- | --- | --- |
| `office-vision-agent/` | 摄像头采集、AI 视觉分析、行为识别、发布事件 | 数据库存储、Dashboard、用户管理、HA 控制 |
| `office-vision-server/` | 事件处理、PostgreSQL、Dashboard API、自动化、AI 分析 | 接触摄像头、视觉推理 |
| `office-vision-dashboard/` | 今日统计、趋势、配置、系统状态、插件管理 | 直连 Agent / 数据库 |
| `yolo-training/` | 自训练数据集：采集、标注、训练（产物部署回 Agent） | 运行时逻辑、接触三端代码 |

## 开发原则

1. Agent 与 Server 完全解耦：Agent 不关心数据库，Server 不关心摄像头
2. 所有行为识别插件化，禁止修改已有 Detector（开闭原则）
3. 所有 AI 模块可替换，不得写死 YOLO（BaseDetector 抽象）
4. 所有配置来自配置文件，不得硬编码
5. 所有硬件抽象，不得直接调用 USB Camera（BaseCamera 抽象）
6. 所有业务基于 Event，禁止模块间直接调用
7. 新增功能优先新增模块，保持核心稳定
8. 平台无关（Platform Agnostic）：macOS 开发（Logitech USB 摄像头），
   可部署到 Raspberry Pi / Windows / Linux；平台相关代码全部经抽象接口隔离

## 第一阶段开发路线（已完成 ✅）

1. 搭建项目目录与三个独立项目骨架 ✅
2. EventBus ✅
3. PluginManager ✅
4. PresenceManager（智能休眠/恢复）✅
5. Camera / Detector 抽象 ✅
6. HTTP 通信 + 离线缓存同步 ✅
7. 配置系统 + 存量代码迁移 ✅
8. 完整架构图 ✅（见 `ARCHITECTURE.md`）

## MVP（V1）范围

摄像头接入、人员检测、在岗检测、抽烟检测（夹烟手势 + 往返运动双重判定）、
Dashboard、事件记录、自动休眠、实时监控可视化。
（不含喝水、玩手机等其他行为识别）

## 项目结构

单体原型（`backend/` / `frontend/` / `plugins/` / `configs/`）的代码已全部迁入
三个新项目并清理移除；模型资产与下载脚本位于 `office-vision-agent/models/` 与
`office-vision-agent/scripts/`。自训练数据集与训练脚本独立于 `yolo-training/` 项目
（数据集、标注、训练产物 runs/，权重部署回 Agent）。
