param([switch]$KeepFiles)
$ErrorActionPreference='Stop'
$setup=Join-Path $env:LOCALAPPDATA 'Programs/kienzledoku Setup/Setup.ps1'
if(!(Test-Path -LiteralPath $setup)){throw 'Bitte das aktuelle Kienzledoku-Setup öffnen und Deinstallieren wählen.'}
& $setup -Uninstall
