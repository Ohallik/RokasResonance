; Inno Setup script for Roka's Resonance
;
; Builds a per-user installer that drops the PyInstaller bundle into
;   %LOCALAPPDATA%\Programs\RokasResonance
; and creates Start Menu + Desktop shortcuts.  No admin rights required.
;
; Prerequisites:
;   1. Build the PyInstaller bundle first:
;        pyinstaller --clean --noconfirm RokasResonance.spec
;      (run from this folder; produces dist/RokasResonance/)
;   2. Install Inno Setup 6 from https://jrsoftware.org/isdl.php
;   3. Open this file in Inno Setup and click Compile, or run build.bat.
;
; Output installer lands in installer/output/Install-RokasResonance.exe
;
; The user's data (profiles, database, settings) lives in
;   %LOCALAPPDATA%\RokasResonance
; which is NOT touched by install or uninstall, so switching between the
; copied-files workflow and the installed build shares the same data.

#define MyAppName "Roka's Resonance"
; MyAppVersion is normally passed in from build.bat via /DMyAppVersion=vX.Y.Z,
; which it extracts from VERSION in main.py so there's a single source of truth.
; This fallback only fires if installer.iss is compiled directly (e.g. from the
; Inno Setup IDE) without that define.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Nate"
#define MyAppExeName "RokasResonance.exe"

[Setup]
AppId={{B4D2C3A1-9E6F-4C12-9F3A-ROKASRESONANCE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppSupportURL=https://github.com/natepm/RokasResonance
DefaultDirName={autopf}\RokasResonance
DefaultGroupName=Roka's Resonance
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=admin
OutputDir=output
OutputBaseFilename=Install-RokasResonance
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\banner_logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; Allow uninstaller to clean up even if the exe was renamed
UninstallDisplayName={#MyAppName}
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; The whole PyInstaller bundle. * + recursesubdirs pulls everything inside dist/RokasResonance/.
Source: "dist\RokasResonance\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Both Start Menu and Desktop shortcuts are created unconditionally — no
; Tasks page is shown, so there's nothing for the user to configure.
; {autoprograms}/{autodesktop} resolve to the system-wide location on admin
; installs and the per-user location otherwise.
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
