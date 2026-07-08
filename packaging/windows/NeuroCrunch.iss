; Inno Setup script for NeuroCrunch (Windows installer).
; Compiled in CI by .github/workflows/build.yml:
;   ISCC.exe /DMyAppVersion=<version> /F<output-basename> packaging/windows/NeuroCrunch.iss
; Packages the PyInstaller EXE output (dist/NeuroCrunch.exe) into a single Setup.exe.

#define MyAppName "NeuroCrunch"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Daniel Zanelli"
#define MyAppExeName "NeuroCrunch.exe"

[Setup]
; AppId uniquely identifies the app so upgrades replace the previous install
; instead of creating a second entry. Do NOT change it between releases.
AppId={{8F3A1C2E-5B7D-4E9A-9C1F-2A6B4D8E0F13}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=NeuroCrunch-{#MyAppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=..\..\assets\icons\app_icon.ico
LicenseFile=..\..\LICENSE
; Let the in-app updater re-run this silently over a running install:
;   Setup.exe /SILENT /CLOSEAPPLICATIONS
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\NeuroCrunch.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
