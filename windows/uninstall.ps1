param([switch]$KeepFiles)
$ErrorActionPreference = 'Stop'
$Destination = $PSScriptRoot
foreach ($Scheme in @('kienzledoku', 'kienzledoku-record')) {
    $Key = "HKCU:\Software\Classes\$Scheme"
    $Command = (Get-ItemProperty "$Key\shell\open\command" -ErrorAction SilentlyContinue).'(default)'
    if ($Command -and $Command.Contains($Destination)) { Remove-Item $Key -Recurse -Force }
}
$Link = Join-Path ([Environment]::GetFolderPath('Programs')) 'kienzledoku record.lnk'
if (Test-Path $Link) { Remove-Item $Link }
if (!$KeepFiles -and (Test-Path $Destination)) { Remove-Item $Destination -Recurse -Force }
Write-Host 'Programm entfernt. Einstellungen und offene Wiederherstellungsdaten bleiben erhalten.'
