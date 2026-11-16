Unicode true
!include "x64.nsh"
Name "kienzledoku 1.8"
OutFile "${OUTPUT}"
RequestExecutionLevel user
ShowInstDetails show
AutoCloseWindow true
Page instfiles
Caption "kienzledoku 1.8 — Vorbereitung"
SetCompressor lzma
VIProductVersion "1.8.0.0"
VIAddVersionKey /LANG=1031 "ProductName" "kienzledoku"
VIAddVersionKey /LANG=1031 "ProductVersion" "1.8"
VIAddVersionKey /LANG=1031 "FileVersion" "1.8"
VIAddVersionKey /LANG=1031 "FileDescription" "Client und Server installieren"
VIAddVersionKey /LANG=1031 "LegalCopyright" "kienzledoku"
Section
 DetailPrint "Installationsassistent wird vorbereitet. Dateien werden entpackt …"
 InitPluginsDir
 ${IfNot} ${RunningX64}
  MessageBox MB_ICONSTOP "Windows x64 erforderlich."
  SetErrorLevel 1
  Quit
 ${EndIf}
 SetOutPath "$PLUGINSDIR\kienzledoku"
 File /r "${PAYLOAD}\*"
 DetailPrint "Assistent starten; Voraussetzungen prüfen …"
 ExecWait '"$WINDIR\SysNative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "$PLUGINSDIR\kienzledoku\Setup.ps1" -SourceDirectory "$EXEDIR\." -BootstrapWindow $HWNDPARENT' $0
 SetErrorLevel $0
SectionEnd
