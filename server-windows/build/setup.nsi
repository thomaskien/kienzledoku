Unicode true
!include "x64.nsh"
!ifndef PRODUCT_VERSION
  !error "Bitte build/build.py mit zentraler VERSION verwenden."
!endif
!ifndef FILE_VERSION
  !error "Dateiversion fehlt; bitte build/build.py verwenden."
!endif
Name "kienzledoku Server Installer"
OutFile "../dist/kienzledoku-Server-Installer-${PRODUCT_VERSION}.exe"
RequestExecutionLevel user
SilentInstall silent
SetCompressor /SOLID lzma
VIProductVersion "${FILE_VERSION}"
VIAddVersionKey /LANG=1031 "ProductName" "kienzledoku Server Installer"
VIAddVersionKey /LANG=1031 "ProductVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=1031 "FileVersion" "${FILE_VERSION}"
VIAddVersionKey /LANG=1031 "FileDescription" "Windows 11 / WSL2 Server-Installationsassistent"
VIAddVersionKey /LANG=1031 "LegalCopyright" "kienzledoku"
Section
  InitPluginsDir
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Windows 11 x64 wird benötigt."
    SetErrorLevel 1
    Quit
  ${EndIf}
  SetRegView 64
  SetOutPath "$PLUGINSDIR\kienzledoku-server"
  File /r /x "__pycache__" "../windows"
  File "../VERSION"
  File "../models.json"
  File "../audio-files.json"
  File "../ubuntu.json"
  File "../README.txt"
  File "../linux-payload.tar"
  ExecWait '"$WINDIR\SysNative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -STA -File "$PLUGINSDIR\kienzledoku-server\windows\Wizard.ps1" -SourceDirectory "$EXEDIR\."' $0
  IfErrors launch_error
  StrCmp $0 "0" finished
  launch_error:
    MessageBox MB_ICONSTOP "Der Installationsassistent konnte nicht gestartet werden. Windows PowerShell 5.1 und Windows 11 x64 prüfen."
    SetErrorLevel 1
  finished:
SectionEnd
