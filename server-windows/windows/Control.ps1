param(
    [ValidateSet('Start','Stop','Status','Verify','Uninstall')][string]$Action='Status',
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [switch]$Quiet
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$remove=$false
if($Action -eq 'Uninstall'){
    $answer=[Windows.Forms.MessageBox]::Show('Server deinstallieren? Ja = eigene WSL-Umgebung und aktive Modelle entfernen. Nein = Server deaktivieren und die vorbereitete WSL-Umgebung samt Modellen behalten. Abbrechen = nichts ändern. Downloadarchive auf SSD/Netzlaufwerk bleiben immer erhalten.','kienzledoku Server deinstallieren','YesNoCancel','Question')
    if($answer -eq 'Cancel'){exit 0};$remove=$answer -eq 'Yes'
}
$engine=Join-Path $PSScriptRoot 'Engine.ps1'
$parameters=@{Action=$Action;ConfigPath=$ConfigPath}
if($remove){$parameters.RemoveModels=$true}
& $engine @parameters
$code=$LASTEXITCODE
if(-not $Quiet){
    Import-Module (Join-Path $PSScriptRoot 'Core.psm1') -Force
    $cfg=Read-Json $ConfigPath;$progress=Read-Json (Join-Path $cfg.StateDirectory 'progress.json')
    $message=$progress.Message
    if($Action -eq 'Status'){$message+="`r`n`r`nDetails: "+(Join-Path $cfg.StateDirectory 'installation.log')}
    [Windows.Forms.MessageBox]::Show($message,'kienzledoku Server')|Out-Null
}
exit $code
