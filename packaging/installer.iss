; Inno Setup script for the XT-Forge Desktop Windows installer.
; Run from `desktop-app/` (Inno Setup 6):  iscc packaging\installer.iss
; Produces  desktop-app\dist\XT-Forge-Setup.exe
;
; Phase 7.4 — This installer ships the PyInstaller-bundled runtime
; (Python + PySide6 + playwright pip package). On first launch the app
; auto-downloads Chromium via `bootstrap.py`, so end users never touch a
; terminal to get running.
;
; The installer is UNSIGNED (per Phase 7 non-goals). Windows SmartScreen
; will show an "Unverified publisher" warning on first run — users click
; "More info" → "Run anyway". See SETUP.md for the walkthrough.

#define AppVersion "0.1.0"

[Setup]
AppId={{2F1E9F73-3E5C-4B18-8B24-8B0D4A4E5D51}
AppName=XT-Forge
AppVersion={#AppVersion}
AppPublisher=XT-Forge
AppPublisherURL=https://github.com/xt-forge
AppSupportURL=https://github.com/xt-forge/desktop-app
DefaultDirName={autopf}\XT-Forge
DefaultGroupName=XT-Forge
OutputDir=..\dist
OutputBaseFilename=XT-Forge-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
; Custom icon for the installer + uninstall entry in Programs & Features.
; The .ico is bundled by PyInstaller under ui/, but Inno Setup needs the
; source path relative to this .iss file. If the file is missing we skip
; (the compiler prints a warning but still builds).
#if FileExists("..\ui\xt-forge.ico")
SetupIconFile=..\ui\xt-forge.ico
UninstallDisplayIcon={app}\XT-Forge.exe
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\XT-Forge\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\XT-Forge"; Filename: "{app}\XT-Forge.exe"
Name: "{group}\Uninstall XT-Forge"; Filename: "{uninstallexe}"
Name: "{autodesktop}\XT-Forge"; Filename: "{app}\XT-Forge.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\XT-Forge.exe"; Description: "Launch XT-Forge"; Flags: nowait postinstall skipifsilent
