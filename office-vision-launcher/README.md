# Office Vision Tray（Agent 端托盘应用）

Agent 端的托盘小应用，替代 `scripts/service.sh`，macOS / Windows 通用：

- 状态栏/托盘图标实时反映 Agent 运行状态（绿=运行中，灰=已停止，红=启动失败，蓝=升级/部署中）
- 菜单一键启动/停止 Agent，崩溃自动重启（连续快速崩溃 5 次后熔断）
- 新设备首次启动自动部署环境（安装 uv/克隆仓库/装依赖/下模型，macOS 与 Windows 双平台）
- 一键打开远程 Dashboard（Server 与 Dashboard 部署在服务器上）
- 在线升级：从 GitHub Releases 检查新版本，下载对应平台资产，自替换后重启

> 部署形态：本应用只运行在监控点电脑（Agent 端）；Server 与 Dashboard 在远程服务器。

## 新设备安装（安装包形态）

- **Windows**：下载 `OfficeVisionTray-Windows-Setup.exe` → 双击安装（当前用户级，无需管理员）→
  桌面/开始菜单出现图标
- **macOS**：下载 DMG → 把 App 拖入“应用程序”文件夹（Mac 标准安装方式）

首次启动自动完成一切：生成配置并自动打开（只需改 `server_url` 指向服务器 IP）→
安装 uv → 克隆仓库 → 装依赖 → 下载模型 → 自动拉起 Agent。
托盘图标变蓝并实时展示当前步骤，失败时菜单显示原因，点击可重试。

安装模式的数据位置（不随应用位置变化）：

| 平台 | 配置/仓库/日志所在目录 |
| --- | --- |
| macOS | `~/Library/Application Support/Office Vision Tray/` |
| Windows | `%LOCALAPPDATA%\Office Vision Tray\` |

仓库公开时自动部署与在线升级均无需 Token；若改回私有再填 `github_token`。

> macOS 需 `xattr -cr` 或右键打开解除 Gatekeeper，并在系统设置授权摄像头；
> 授权对已启动进程不生效，若授权前 Agent 已启动过一次，点击菜单重启即可。

> 便携模式仍兼容：把应用与 config.yaml 放同一文件夹直接运行，
> workdir 按配置文件所在目录相对解析（旧部署方式不受影响）。

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
git tag v0.2.1 && git push origin v0.2.1
# 注意：发布只走 tag 触发，不用 workflow_dispatch 手动构建
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
| `OfficeVisionLauncher-macOS.dmg` | macOS 安装包（拖入应用程序文件夹） |
| `OfficeVisionTray-Windows-Setup.exe` | Windows 安装器（Inno Setup，当前用户级） |
| `office-vision-tray-darwin.zip` | macOS 自更新资产（.app + config.yaml） |
| `office-vision-tray-windows.zip` | Windows 自更新资产（onedir 目录 + config.yaml） |

自更新资产命名与 `config.yaml` 的 `asset_pattern` 对应。

> 便携模式目录结构：解压后 config.yaml 与应用本体同级放置，且 `office-vision-agent`
> 目录位于 config.yaml 的上级目录旁（workdir 相对路径 `../office-vision-agent`）。
> 安装模式无需关心目录：配置/仓库/日志统一在用户配置目录。
> config.yaml 缺失时应用会自动生成默认配置。在线升级只替换应用本体，
> 不会覆盖用户已修改的 config.yaml。
>
> macOS 首次打开提示「已阻止以保护 Mac」（未签名应用）：右键 → 打开，或
> `xattr -dr com.apple.quarantine "Office Vision Tray.app"` 解除隔离。

## 路线图（RFC-0008）

- 打包器从 PyInstaller 迁移到 Nuitka（启动更快、源码保护更好）
- Linux 支持（AppImage / deb / rpm）
- 首次运行服务器地址图形化引导（当前为自动打开 config.yaml）

## Windows 开机自启

安装器已创建开始菜单/桌面快捷方式；开机自启：`Win+R` → `shell:startup` → 放入快捷方式。
macOS 可在「系统设置 → 通用 → 登录项」添加 `.app`。
