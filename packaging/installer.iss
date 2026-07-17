[Setup]
AppId={{5F4B3AD9-7C91-4E2D-A4C4-70C5C4F5A211}
AppName=十一桌面宠物
AppVersion=1.0.0
AppPublisher=十一桌面宠物
DefaultDirName={localappdata}\Programs\ShiyiDesktopPet
DefaultGroupName=十一桌面宠物
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\artifacts
OutputBaseFilename=十一桌面宠物安装程序
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=force
RestartApplications=no
UninstallDisplayIcon={app}\ShiyiDesktopPet.exe
SetupIconFile=..\src\shiyi_desktop_pet\resources\app.ico
VersionInfoVersion=1.0.0.0

[Languages]
Name: chinesesimplified; MessagesFile: "languages\ChineseSimplified.isl"

[Tasks]
Name: startup; Description: 开机自动启动十一; Flags: checkedonce

[Files]
Source: ..\dist\ShiyiDesktopPet\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\十一桌面宠物; Filename: {app}\ShiyiDesktopPet.exe

[Registry]
Root: HKCU; Subkey: Software\Microsoft\Windows\CurrentVersion\Run; ValueType: string; ValueName: ShiyiDesktopPet; ValueData: """{app}\ShiyiDesktopPet.exe"" --startup"; Tasks: startup; Flags: uninsdeletevalue; Check: ShouldWriteStartup

[Run]
Filename: {app}\ShiyiDesktopPet.exe; Description: 立即运行十一; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: {app}\ShiyiDesktopPet.exe; Parameters: --quit-existing; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: QuitExisting

[UninstallDelete]
Type: filesandordirs; Name: {userappdata}\ShiyiDesktopPet
Type: filesandordirs; Name: {localappdata}\ShiyiDesktopPet

[Code]
var
  WasUpgrade: Boolean;

function InitializeSetup(): Boolean;
begin
  WasUpgrade := RegKeyExists(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{5F4B3AD9-7C91-4E2D-A4C4-70C5C4F5A211}_is1'
  );
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExistingExe: String;
  ResultCode: Integer;
begin
  Result := '';
  ExistingExe := ExpandConstant('{app}\ShiyiDesktopPet.exe');
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
      Result := '无法关闭已运行的十一桌面宠物，请稍后重试。';
  end;
end;

function ShouldWriteStartup(): Boolean;
begin
  Result := (not WasUpgrade) and WizardIsTaskSelected('startup');
end;
