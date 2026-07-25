[Setup]
AppId={{024D8DE0-D8D7-46BD-B09D-CB89484282B4}
AppName=桌面灵伴
AppVersion=2.4.7
AppPublisher=桌面灵伴
DefaultDirName={localappdata}\Programs\DesktopCompanion
DefaultGroupName=桌面灵伴
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\artifacts
OutputBaseFilename=桌面灵伴安装程序
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=force
RestartApplications=no
UninstallDisplayIcon={app}\DesktopCompanion.exe
SetupIconFile=..\src\shiyi_desktop_pet\resources\app.ico
VersionInfoVersion=2.4.7.0

[Languages]
Name: chinesesimplified; MessagesFile: "languages\ChineseSimplified.isl"

[Tasks]
Name: startup; Description: 开机自动启动桌面灵伴; Flags: checkedonce

[Files]
Source: ..\dist\DesktopCompanion\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\桌面灵伴; Filename: {app}\DesktopCompanion.exe
Name: {autodesktop}\桌面灵伴; Filename: {app}\DesktopCompanion.exe

[Registry]
Root: HKCU; Subkey: Software\Microsoft\Windows\CurrentVersion\Run; ValueType: string; ValueName: DesktopCompanion; ValueData: """{app}\DesktopCompanion.exe"" --startup"; Tasks: startup; Flags: uninsdeletevalue; Check: ShouldWriteStartup

[Run]
Filename: {app}\DesktopCompanion.exe; Description: 立即运行桌面灵伴; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: {app}\DesktopCompanion.exe; Parameters: --quit-existing; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: QuitExisting

[UninstallDelete]
Type: filesandordirs; Name: {userappdata}\DesktopCompanion
Type: filesandordirs; Name: {localappdata}\DesktopCompanion

[Code]
var
  WasUpgrade: Boolean;

function InitializeSetup(): Boolean;
begin
  WasUpgrade := RegKeyExists(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{024D8DE0-D8D7-46BD-B09D-CB89484282B4}_is1'
  );
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExistingExe: String;
  ResultCode: Integer;
begin
  Result := '';
  ExistingExe := ExpandConstant('{app}\DesktopCompanion.exe');
  if FileExists(ExistingExe) then
  begin
    if (not Exec(
      ExistingExe,
      '--quit-existing',
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    )) or (ResultCode <> 0) then
      Result := '无法关闭已运行的桌面灵伴，请稍后重试。';
  end;
end;

function ShouldWriteStartup(): Boolean;
begin
  Result := (not WasUpgrade) and WizardIsTaskSelected('startup');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(
      HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      'DesktopCompanion'
    );
end;
