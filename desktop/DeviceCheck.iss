#define AppName "巡测"
#define AppVersion "1.1.0"
[Setup]
AppId=com.devicecheck.desktop
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\DeviceCheck
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installers
OutputBaseFilename=DeviceCheck-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\DeviceCheck.exe
[Files]
Source: "..\dist\desktop\DeviceCheck\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\巡测"; Filename: "{app}\DeviceCheck.exe"
Name: "{group}\配置自动化环境"; Filename: "{app}\DeviceCheck.exe"; Parameters: "--setup-runtime"
Name: "{userdesktop}\巡测"; Filename: "{app}\DeviceCheck.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; Flags: unchecked
[Run]
Filename: "{app}\DeviceCheck.exe"; Description: "启动巡测"; Flags: nowait postinstall skipifsilent
