; Inno Setup script for Tephra. Compile with: iscc packaging\tephra.iss
; Produces a per-user installer that needs no admin rights.

#define AppName    "Tephra"
#define AppVersion "1.0.0"
#define AppExe     "Tephra.exe"

[Setup]
AppId={{9E3C7A54-6B2F-4B8E-9D31-6F1A2C7E51B4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Tephra
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Tephra-{#AppVersion}-windows-x64-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install: no UAC prompt, and no "unknown publisher" admin dialog
; on top of the SmartScreen warning an unsigned build already gets.
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Tephra\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}";        Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{group}\Uninstall {#AppName}";    Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only app files. The vault lives in Documents and is never touched —
; uninstalling must not be able to destroy someone's notes.
Type: filesandordirs; Name: "{app}"

[Code]
{ pywebview renders through Edge WebView2. It ships with Windows 11 and
  current Windows 10, but not with older builds, so check and bootstrap. }
function WebView2Missing(): Boolean;
var
  V: String;
begin
  Result :=
    not RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V)
    and not RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Tmp: String;
begin
  if (CurStep = ssPostInstall) and WebView2Missing() then
  begin
    Tmp := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
    if not DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703',
                                 'MicrosoftEdgeWebview2Setup.exe', '', nil) = 0 then
      Exec(Tmp, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;
