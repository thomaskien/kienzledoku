#ifndef PackageDir
  #error PackageDir fehlt
#endif
[Setup]
AppId={{49E665CD-61CE-426A-A64C-BE1CE11AE019}
AppName=kienzledoku record
AppVersion=1.3.3
DefaultDirName={localappdata}\Programs\kienzledoku record
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=kienzledoku-record-1.3.3-windows-x64-setup
SetupIconFile=..\assets\kienzledoku-record.ico
UninstallDisplayIcon={app}\assets\kienzledoku-record.ico
Compression=lzma2
SolidCompression=yes
[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Parameters: String;
begin
  if CurStep = ssPostInstall then
  begin
    Parameters := ExpandConstant('-NoProfile -ExecutionPolicy Bypass -File "{app}\install.ps1" -InPlace -TargetDirectory "{app}"');
    if WizardSilent then
      Parameters := Parameters + ' -NoOpen';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters,
      '', SW_SHOW, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
      RaiseException('Einrichtung nicht abgeschlossen. Servereinrichtung, WebView2 Runtime und Installationsausgabe pruefen. Anschliessend dieses Setup erneut ausfuehren.');
  end;
end;
[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"" -KeepFiles"; Flags: runhidden waituntilterminated
