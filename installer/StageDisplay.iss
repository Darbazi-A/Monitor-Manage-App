; Inno Setup script: one installer for Stage Display Controller (installer\build.ps1 runs it).
; Installs for the current user (no administrator needed), adds Start-menu and Desktop
; shortcuts, lets the phone remote and the laptop share through the Windows firewall,
; and appears in Windows Settings -> Apps for uninstalling.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppName
  #define AppName "Stage Display Controller"
#endif
; a test build installs beside the real one under a name and AppId of its own
#ifndef AppGuid
  #define AppGuid "{{6F2C1B9E-4A7D-4C5E-9B1F-5D3A2E8C7B41}"
#endif
#define AppExe "Stage Display Controller.exe"

[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=European School
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=StageDisplayController-Setup-{#AppVersion}
SetupIconFile=..\stage_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
; Inno Setup has no Georgian of its own; the wizard is a few clicks, the program itself speaks Georgian
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Stage Display Controller\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; the phone remote (8765) and the laptop share (8443) are reached from the hall's Wi-Fi:
; with administrator rights the installer lets them through the firewall (private networks
; only); without, Windows asks the first time they are switched on.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private"; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; an update the program started itself (Install now): open it again when done
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: Relaunch

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; Check: IsAdminInstallMode; RunOnceId: "DelFirewallRule"

[UninstallDelete]
; the program's own folder only - the hall's presets, running orders and backups in
; AppData\Roaming\StageDisplayController are kept, for the next installation
Type: filesandordirs; Name: "{app}"

[Code]
// /RELAUNCH: the program started this update and wants to be opened again afterwards
function Relaunch: Boolean;
begin
  Result := WizardSilent and (Pos('/RELAUNCH', Uppercase(GetCmdTail)) > 0);
end;
