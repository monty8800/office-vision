# Office Vision Tray（Agent 端托盘应用）

Agent 端的托盘小应用，替代 `scripts/service.sh`，macOS / Windows 通用：

- 状态栏/托盘图标实时反映 Agent 运行状态（绿=运行中，灰=已停止，红=启动失败，蓝=升级/部署中）
- 菜单一键启动/停止 Agent，崩溃自动重启（连续快速崩溃 5 次后熔断）
- 新设备首次启动自动部署环境（安装 uv/克隆仓库/装依赖/下模型，macOS 与 Windows 双平台）
- 一键打开远程 Dashboard（Server 与 Dashboard 部署在服务器上）
- 在线升级：从 GitHub Releases 检查新版本，下载对应平台资产，自替换后重启

> 部署形态：本应用只运行在监控点电脑（Agent 端）；Server 与 Dashboard 在远程服务器。

## 新设备部署（自动安装）

新监控点无需手动装环境，只需三步：

1. 从 GitHub Releases 下载安装包（macOS 用 DMG / Windows 用 exe），新建一个专用文件夹，
   把应用与 `config.yaml` 都放进去（⚠️ 不要在 DMG 卷内直接运行）
2. 编辑 `config.yaml`：`server_url` 指向服务器（如 `http://192.168.x.x:8000`）；
   仓库已公开无需 Token，若改为私有仓库再填 `github_token`
3. 启动应用：检测到环境缺失后自动完成 安装 uv → 克隆仓库 → 装依赖 → 下载模型，
   托盘图标变蓝并实时展示当前步骤，完成后自动拉起 Agent；失败时菜单显示原因，点击可重试

目录约定：仓库会克隆到托盘文件夹的上级（与 `office-vision-agent` 平级），
与 `config.yaml` 的 `workdir: "../office-vision-agent"` 相对路径保持一致。

> macOS 首次启动需 `xattr -cr` 或右键打开解除 Gatekeeper，并在系统设置授权摄像头；
> 授权对已启动进程不生效，若授权前 Agent 已启动过一次，点击菜单重启即可。

## 开发模式运行

```bash
uv sync
uv run office-vision-tray   # 或 uv run python -m launcher
```

应用启动即自动拉起 Agent（`office-vision-agent`，经 `uv run`），日志写入 `data/logs/agent.log`。

## 配置（config.yaml）

| 配置项 | 说明 | 环境变量覆盖 |
| --- | --- | --- |
| `server_url` | Server 服务地址，默认 `http://localhost:8000`；启动 Agent 前自动同步到 agent.yaml | `OVA_SERVER_URL` |
| `dashboard_url` | 远程 Dashboard 地址，按实际服务器修改 | `OVA_DASHBOARD_URL` |
| `github_repo` | 升级源仓库（owner/repo） | `OVA_GITHUB_REPO` |
| `github_token` | 私有仓库访问 Token（**勿明文提交**） | `OVA_GITHUB_TOKEN` |
| `services` | 受管服务定义（端口/命令/工作目录） | — |

> 修改服务地址的两种方式：① 托盘菜单「服务地址：xxx（点击修改）」打开 config.yaml
> 编辑后重启应用；② 环境变量 `OVA_SERVER_URL`（优先级最高）。
> 地址变更会在下次启动 Agent 时自动写入 agent.yaml 的 `server.url`（保留注释，幂等）。

## 在线升级

1. 托盘菜单「检查更新」→ 查询 `GitHub Releases` 最新 tag
2. 版本更高时显示「发现新版本 vX.Y.Z，点击安装」
3. 点击后按平台下载自更新资产（两平台均为 zip：应用本体 + config.yaml），退出当前进程，由临时脚本完成替换并重新拉起（保留已有 config.yaml）

> 源码运行模式下无法自替换，仅提示 `git pull` 后重启。

## 发布新版本

版本号唯一来源：`launcher/__init__.py` 的 `__version__`。

### 方式一：GitHub Actions（推荐，RFC-0008，一次打包双平台）

打包逻辑统一在 `build/` 目录（本地与 CI 共用），workflow 只负责调度：

```
build/
├── macos.sh      # 产出 DMG 安装包 + 自更新 zip
├── windows.ps1   # 产出便携版 exe + 自更新 zip
├── linux.sh      # 占位（未来 AppImage/deb/rpm）
└── packlib.py    # 共享打包逻辑
```

```bash
# 1. 修改 __version__ 并提交
# 2. 打 tag 触发（tag 必须与 __version__ 一致，CI 会校验）
git tag v0.2.0 && git push origin v0.2.0
# 或在 Actions 页面手动 Run workflow（按当前 __version__ 发布）
```

### 方式二：本地手动打包（兜底，仅当前平台）

```bash
sh build/macos.sh                            # 直接调平台脚本
uv run python scripts/release.py --build     # 等价入口，产物在 dist/
uv run python scripts/release.py             # 打包 + gh CLI 创建 Release
```

产物清单（dist/）：

| 文件 | 用途 |
| --- | --- |
| `OfficeVisionLauncher-macOS.dmg` | macOS 人工安装包 |
| `OfficeVisionLauncher-Windows.exe` | Windows 便携版 |
| `office-vision-tray-darwin.zip` | macOS 自更新资产（.app + config.yaml） |
| `office-vision-tray-windows.zip` | Windows 自更新资产（exe + config.yaml） |

自更新资产命名与 `config.yaml` 的 `asset_pattern` 对应。

> 部署目录结构：解压后 config.yaml 与应用本体同级放置，且 `office-vision-agent`
> 目录位于 config.yaml 的上级目录旁（workdir 相对路径 `../office-vision-agent`）。
> config.yaml 缺失时应用会自动生成默认配置（优先部署目录，只读卷则落到
> 用户配置目录）。在线升级只替换应用本体，不会覆盖用户已修改的 config.yaml。
>
> macOS 首次打开提示「已阻止以保护 Mac」（未签名应用）：右键 → 打开，或
> `xattr -dr com.apple.quarantine "Office Vision Tray.app"` 解除隔离。

## 路线图（RFC-0008）

- Windows Setup.exe（Inno Setup 安装向导）
- 打包器从 PyInstaller 迁移到 Nuitka（启动更快、源码保护更好）
- Linux 支持（AppImage / deb / rpm）

## Windows 开机自启

将打包产物放入启动目录即可：`Win+R` → `shell:startup` → 放入 exe 快捷方式。
macOS 可在「系统设置 → 通用 → 登录项」添加 `.app`。
