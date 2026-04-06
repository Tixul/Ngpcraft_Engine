; installer.iss — Inno Setup script for NgpCraft Engine
; Requirements:
;   1. Build the exe first:  pyinstaller ngpcraft_engine.spec
;   2. Open this file in Inno Setup Compiler and click Compile.
;
; Output: Output\NgpCraftEngine_Setup_1.0.0.exe

#define AppName      "NgpCraft Engine"
#define AppVersion   "1.0.0"
#define AppPublisher "NGPC"
#define AppURL       "https://github.com/Tixul/Ngpcraft_Engine"
#define AppExeName   "NgpCraftEngine.exe"
#define BuildDir     "dist\NgpCraftEngine"

[Setup]
AppId={{A3F2C1D4-7B8E-4F9A-B2C3-D4E5F6A7B8C9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
; Icon shown in the installer itself and in Add/Remove Programs
SetupIconFile=assets\ngpcraft.ico
UninstallDisplayIcon={app}\{#AppExeName}
; Installer exe output
OutputDir=Output
OutputBaseFilename=NgpCraftEngine_Setup_{#AppVersion}
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Require Win 10+
MinVersion=10.0
; Request admin if needed (for Program Files), user-level otherwise
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
; Show license if you have one
; LicensFile=LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french";  MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon";   Description: "{cm:CreateDesktopIcon}";   GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Everything built by PyInstaller
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\ngpcraft.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
; Desktop (optional)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\ngpcraft.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
