# Office Vision AI

AI-powered Office Behavior Analysis Platform —— 基于 AI 视觉的办公室行为分析与自动化平台。

定位为个人行为统计、健康分析与办公自动化（Home Assistant 联动），而非员工监控。

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https%3A%2F%2Fgithub.com%2Fmonty8800%2Foffice-vision&utm_medium=integration&utm_source=button&utm_campaign=office-vision)


## 系统架构（多项目分离）

```
┌─────────────────────────┐       HTTP API          ┌──────────────────────┐
│ office-vision-launcher  │        托管进程          │ office-vision-server │
│ （托盘应用，Agent 端）   │ ──────拉起/监控─────► │ （远程服务器）        │
│ ┌─────────────────────┐ │                          │ FastAPI + PostgreSQL │
│ │ office-vision-agent │ │ ──── 事件上报 ──────► │                      │
│ │ 摄像头+AI识别+发事件 │ │  （离线时 SQLite 缓存） │                      │
│ └─────────────────────┘ │                          └──────────┬───────────┘
└─────────────────────────┘                                     │ REST API
                                                     ┌──────────▼───────────┐
                                                     │office-vision-dashboard│
                                                     │     Next.js 16       │
                                                     └──────────────────────┘
```

部署形态：监控点电脑（Mac/Windows）只跑托盘应用 + Agent；Server 与 Dashboard 部署在远程服务器。

| 项目 | 职责 | 禁止 |
| --- | --- | --- |
| `office-vision-agent/` | 摄像头采集、AI 视觉分析、行为识别、发布事件 | 数据库存储、Dashboard、用户管理、HA 控制 |
| `office-vision-server/` | 事件处理、PostgreSQL、Dashboard API、自动化、AI 分析 | 接触摄像头、视觉推理 |
| `office-vision-dashboard/` | 今日统计、趋势、配置、系统状态、插件管理 | 直连 Agent / 数据库 |
| `office-vision-launcher/` | 托盘应用：托管 Agent 进程、崩溃自重启、服务地址配置、在线升级 | 业务逻辑、接触摄像头 |
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

## 跨平台打包与发布（RFC-0008）

托盘应用通过 GitHub Actions 一次构建双平台，产物统一发布到 GitHub Releases：

- 打包逻辑统一在 `office-vision-launcher/build/`（macos.sh / windows.ps1），
  `.github/workflows/tray-release.yml` 仅负责调度
- 产物：`OfficeVisionLauncher-macOS.dmg`、`OfficeVisionLauncher-Windows.exe`
  及两平台自更新资产（zip）
- 发版：`git tag vX.Y.Z && git push origin vX.Y.Z`，全自动无人工参与
- 在线升级：托盘应用启动后检查 Releases，发现新版本自动下载、替换、重启
- 路线图：Windows Setup.exe、PyInstaller → Nuitka、Linux 支持

## 云端部署（Railway 一键部署）

Server（FastAPI）+ Dashboard（Next.js）+ PostgreSQL 可通过 Railway Template 一键部署；
Agent 依赖摄像头与本地推理，不上云，仍运行在监控点电脑上。

- **一键部署**：点击顶部 Deploy on Railway 按钮直达部署流程，仓库内各服务的
  `railway.toml`（config-as-code）会被自动识别；需在模板编辑器中确认三个服务
  （Postgres / server / dashboard，后两者 root directory 分别指向对应子目录）
- **引用变量**：server 服务 `OVA_DATABASE_URL={{Postgres.DATABASE_URL}}`、
  dashboard 服务 `OVA_SERVER_URL=https://{{server.FQDN}}`（需为 server 开启 Public Networking）
- **部署完成后**：将 Agent `config.yaml` 的 `server_url` 改为云端 Server URL
  （新设备部署唯一必填项）
- **费用**：Railway Hobby 计划 $5/月（含 $5 用量额度），本项目规模通常可被额度覆盖；
  服务不休眠、无冷启动
- **构建配置**：Railpack 经 `uv.lock` 安装 Server 依赖，Dashboard 自动识别 Next.js

可选：维护者部署验证后可在 Railway 项目 Settings → Generate Template from Project
将完整三服务栈固化为模板，届时把顶部按钮链接替换为模板链接（`railway.com/new/template/<code>`），
即可实现含数据库连线的全自动一键部署。

注：云端 Dashboard 的 Agent 调试页（`:8100`）仅对本地环境可用，属预期行为。

## 项目结构

单体原型（`backend/` / `frontend/` / `plugins/` / `configs/`）的代码已全部迁入
各项目并清理移除；模型资产与下载脚本位于 `office-vision-agent/models/` 与
`office-vision-agent/scripts/`。自训练数据集与训练脚本独立于 `yolo-training/` 项目
（数据集、标注、训练产物 runs/，权重部署回 Agent）。
本地开发可继续用 `scripts/service.sh`（tmux）编排三服务；部署到监控点电脑时使用
`office-vision-launcher` 托盘应用（详见其 README）。

## 当前部署状态与运营（2026-08-29）

### 部署形态
- **本地 24h 节点**：VM 115 @ 192.168.9.214（Debian 12，4 核 6G），Agent(:8100) +
  Server(:8000, SQLite) + Dashboard(:3000) 全本地，Logitech C930c 摄像头 USB 直通，
  systemd 自启（`office-vision-{agent,server,dashboard}.service`）。
- **训练在 Windows GPU 机**（192.168.9.204，RTX 5070 Ti）：`C:\Users\dsh\office-vision-training\.venv`
  （uv + Python3.12 + torch cu130 + ultralytics），几分钟一轮。
- 访问：Dashboard http://192.168.9.214:3000（实时监控 `/monitor`、行为分析 `/trends`）。
- **⚠️ VM 系统时区必须为 Asia/Shanghai**：server 统计（时段分布/趋势）用 `strftime(..., "localtime")`
  按 OS 时区取小时，若 VM 是 UTC 会导致时段分布错乱（如凌晨 1 点显示成 17 点）。部署后 `timedatectl set-timezone Asia/Shanghai`。

### 抽烟检测判定（用户规则）
- **烟在手上 或 在嘴里 = 抽烟**；放桌上（不在手/嘴旁）不算。
- `smoking/detector.py`：`evaluate_cigarette` 判定香烟位置锁定（烟框与嘴部重叠/落入放大嘴部区 = 在嘴里；
  靠近任意手 = 在手上），位置锁定检出达标即确认（不要求"手必须近嘴"，避免误挡真实抽烟）。
- smoking-cls 行为分类模型已弃用（不可靠），由位置规则取代（`classifier_confirm_frames: 0`）。
- 香烟检测置信度阈值 `cigarette_confidence: 0.5`（抑制面部/眼镜/笔误检）。

### 数据标注 → GPU 训练 → 自动部署（闭环）
1. 监控页「数据集标注」面板（在实时画面右侧）冻结当前帧 → 拖框标香烟 / 存负样本 →
   落 `agent/data/annotate/{smoking|normal}/`（labelme JSON）。
2. `yolo-training/scripts/sync_and_train.sh`：把标注推到 Windows → `labelme2yolo.py` →
   `train_cigarette.py --finetune`。
3. 新 `best.pt` 回部署（覆盖 `weights/cigarette-best.pt`）。
4. 自动标注脚本 `yolo-training/scripts/auto_annotate.py` 可用已有模型批量预标注。
- 当前香烟检测模型：mAP50 ~98.5–99.4%、P≈0.97–0.98、R≈0.94–0.99（含难负样本训练）。

### 省电：深度休眠 + 凌晨关闭窗口（presence）
- 无人（含启动即无人）超时进入 SLEEPING → `camera.stop()` 关闭摄像头（省电/减压）。
- 深度休眠定时唤醒：每 `wakeup_check_seconds`（300s）开摄像头查人，有人恢复 / 无人再关。
- **凌晨窗口** `off_hours_*`（默认 00:00–08:00）：窗口内无人连续 `off_hours_idle_seconds`（3600s）才关；
  **08:00 准时开启**（`force_wake` 强制唤醒）。

### 后续规划
- 加入**喝水**、**玩手机**行为的事件识别（沿用插件化架构：新增 `plugins/` 行为插件 +
  events handlers 映射表，行为分析页按 `BEHAVIORS` 注册表扩展）。
