; Office Vision Tray Windows 安装器（Inno Setup 6）
; 当前用户级安装（%LOCALAPPDATA%\Programs），无需管理员权限；
; 应用首次启动自动下载运行环境（uv/仓库/依赖/模型），安装包本身保持精简。

#define MyAppName "Office Vision Tray"
#define MyAppExe "Office Vision Tray.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{B7F4C6A2-3D5E-4A8B-9C1F-2E6D8A0B4C71}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Office Vision
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=OfficeVisionTray-Windows-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 安装完成页提供"立即运行"勾选
DisableProgramGroupPage=yes

[Languages]
; 仅英文：CI runner 的 Inno Setup 未内置简体中文语言文件，避免编译失败
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; onedir 产物整体安装（PyInstaller 目录式输出）
Source: "..\dist\stage\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理运行产生的日志（保留用户配置与克隆的仓库，避免误删）
Type: filesandordirs; Name: "{app}\data"
