[CmdletBinding()]
param([string]$Config, [switch]$InPlace, [switch]$NoOpen, [string]$TargetDirectory, [string]$WizardConfig)
$ErrorActionPreference = 'Stop'
$Destination = if ($TargetDirectory) { $TargetDirectory } else { Join-Path $env:LOCALAPPDATA 'Programs/kienzledoku record' }
if ([IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') -eq [IO.Path]::GetFullPath($Destination).TrimEnd('\')) { $InPlace = $true }
$Data = Join-Path $env:LOCALAPPDATA 'kienzledoku record'
. (Join-Path $PSScriptRoot 'ClientRuntime.ps1')
# Check native requirements before replacing the installed client tree.
Initialize-ClientRuntime $PSScriptRoot
# Evergreen WebView2 runtime is independent from the application package.
$RuntimeKey = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
$RuntimeFound = @('HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients', 'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients', 'HKCU:\Software\Microsoft\EdgeUpdate\Clients') | ForEach-Object {
    Get-ChildItem $_ -ErrorAction SilentlyContinue | ForEach-Object { Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue } | Where-Object { $_.name -like '*WebView2*' -and $_.pv -and $_.pv -ne '0.0.0.0' }
}
if (!$RuntimeFound) {
    $Offline = Join-Path $PSScriptRoot 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
    if (!(Test-Path $Offline)) {
        [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -UseBasicParsing -OutFile $Offline
    }
    $Signature = Get-AuthenticodeSignature $Offline
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { throw 'WebView2-Installer hat keine gueltige Microsoft-Signatur.' }
    $Process = Start-Process $Offline -ArgumentList '/silent /install' -Wait -PassThru
    if ($Process.ExitCode -notin @(0, 3010)) { throw 'WebView2-Installation fehlgeschlagen.' }
}
# Keep the update lock until payload, registrations and self-test agree.
. (Join-Path $PSScriptRoot 'Update.ps1')
$null=Assert-CodePath $Data
New-Item -ItemType Directory -Force $Data | Out-Null
$updateLease=[IO.File]::Open((Join-Path $Data 'update.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$transaction=$null;$validated=$false
try {
 Assert-ClientClosed $Destination
 if($InPlace){Assert-CodeInventory $Destination}else{$transaction=Start-CodeUpdate $PSScriptRoot $Destination 'kienzledoku.py'}
$Python = Join-Path $Destination 'runtime/pythonw.exe'
$Script = Join-Path $Destination 'kienzledoku.py'
$DirectLauncher = Join-Path $Destination 'kienzledoku_launch.py'
$Connect = Join-Path $Destination 'kienzleconnect.exe'
if (!(Test-Path $Python) -or !(Test-Path $Connect)) { throw 'Unvollstaendiges Record-Paket.' }
New-Item -ItemType Directory -Force $Data | Out-Null
# Existing configuration takes precedence. Preseed only a fresh installation.
if ($Config -and !(Test-Path (Join-Path $Data 'config.toml'))) {
    & (Join-Path $Destination 'runtime/python.exe') $Script --import-config $Config
    if ($LASTEXITCODE -ne 0) { throw 'TOML-Vorbelegung konnte nicht uebernommen werden.' }
}
function Register-Protocol([string]$Scheme, [string]$Command) {
    $Key = "HKCU:\Software\Classes\$Scheme"
    New-Item -Force $Key | Out-Null
    Set-Item $Key -Value 'URL:kienzledoku record'
    New-ItemProperty $Key -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
    New-Item -Force "$Key\DefaultIcon" | Out-Null
    Set-Item "$Key\DefaultIcon" -Value ('"' + (Join-Path $Destination 'assets/kienzledoku-record.ico') + '"')
    New-Item -Force "$Key\shell\open\command" | Out-Null
    Set-Item "$Key\shell\open\command" -Value $Command
}
Register-Protocol 'kienzledoku' ('"' + $Connect + '" "%1"')
Register-Protocol 'kienzledoku-record' ('"' + $Python + '" "' + $DirectLauncher + '" "%1"')
$Shell = New-Object -ComObject WScript.Shell
$LinkPath = Join-Path ([Environment]::GetFolderPath('Programs')) 'kienzledoku record.lnk'
$Shortcut = $Shell.CreateShortcut($LinkPath)
$Shortcut.TargetPath = $Python
$Shortcut.Arguments = '"' + $Script + '" --settings'
$Shortcut.WorkingDirectory = $Destination
$Shortcut.IconLocation = Join-Path $Destination 'assets/kienzledoku-record.ico'
$Shortcut.Save()
Assert-ClientVad $Destination
& (Join-Path $Destination 'runtime/python.exe') $Script --self-test
if ($LASTEXITCODE -ne 0) { throw 'Der neue Client hat seinen Selbsttest nicht bestanden.' }
Assert-ClientClosed $Destination
if($WizardConfig){
    & (Join-Path $Destination 'runtime/python.exe') (Join-Path $Destination 'installer_client.py') --wizard-config $WizardConfig
    if($LASTEXITCODE -ne 0){throw 'Clienteinstellungen konnten nicht gespeichert werden.'}
}
$validated=$true
Complete-CodeUpdate $transaction
} catch {
 if(!$validated){Undo-CodeUpdate $transaction}
 throw
} finally {$updateLease.Dispose()}
if (!$NoOpen) {
    Write-Host 'Bitte im Record-Fenster die Server eintragen und die Installation abschliessen.'
    $Setup = Start-Process $Python -ArgumentList ('"' + $Script + '" --setup') -Wait -PassThru
    if ($Setup.ExitCode -ne 0) {
        throw 'Servereinrichtung wurde abgebrochen oder konnte nicht gestartet werden. Vorhandene Einstellungen bleiben erhalten. Bitte dieses Setup erneut ausfuehren.'
    }
}
Write-Host 'kienzledoku record 1.8.3 installiert. Einstellungen und Betriebsart bleiben bei Updates erhalten.'
