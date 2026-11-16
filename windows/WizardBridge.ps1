param([ValidateSet('Inspect','Install','Uninstall')][string]$Action='Inspect',[string]$InputPath,[string]$ProgressPath,[string]$ResultPath)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$root=$PSScriptRoot
$serverRoot=Join-Path $root 'server'
if(!(Test-Path $serverRoot)){$serverRoot=Join-Path (Split-Path $root -Parent) 'server-windows'}
Import-Module (Join-Path $serverRoot 'windows/Core.psm1') -Force
Import-Module (Join-Path $root 'WizardConfig.psm1') -Force
. (Join-Path $root 'SetupUninstall.ps1')
function Report([string]$Message,[int]$Percent,$Extra=@{}){
    $status=@{message=$Message;progress=$Percent}
    foreach($key in $Extra.Keys){$status[$key]=$Extra[$key]}
    Write-Json $ProgressPath $status
}
function Save-Secret([string]$Path,[string]$Value){
    if(!(Test-Path -LiteralPath $Path)){[IO.File]::WriteAllText($Path,'')}
    Set-PrivateFile $Path
    [IO.File]::WriteAllText($Path,$Value,(New-Object Text.UTF8Encoding($false)))
}
function Run-Engine([string]$Operation,[string]$Config,$Options=@()){
    $arguments=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $serverRoot 'windows/Engine.ps1'),'-Action',$Operation,'-ConfigPath',$Config)+$Options
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=Join-Path $env:windir 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $info.Arguments=ConvertTo-NativeArguments $arguments;$info.UseShellExecute=$false;$info.CreateNoWindow=$true
    $process=[Diagnostics.Process]::Start($info)
    try{$process.WaitForExit();$code=$process.ExitCode}finally{$process.Dispose()}
    if($code -ne 0){
        $engineStatus=Read-Json (Join-Path $env:LOCALAPPDATA 'kienzledoku-server/progress.json')
        if($engineStatus -and $engineStatus.Message){throw $engineStatus.Message}
        throw "Servervorgang nicht abgeschlossen (Exitcode $code)."
    }
    $engineStatus=Read-Json (Join-Path $env:LOCALAPPDATA 'kienzledoku-server/progress.json')
    if(!$engineStatus.Finished -or !$engineStatus.Success){throw 'Der Server hat keinen erfolgreichen Abschluss bestätigt.'}
}
$held=$false;$mutex=$null
try {
    $components=Get-KienzledokuComponents
    $previous=$null
    if($components.ServerConfig){$previous=Read-Json $components.ServerConfig}
    if($Action -eq 'Inspect'){
        $hw=$null;try{$hw=Get-Hardware}catch{}
        # Configuration has file references, never embedded access tokens.
        @{hardware=$hw;previous=$previous;client=$components.ClientInstalled}|ConvertTo-Json -Depth 24 -Compress
        exit 0
    }
    $mutex=New-Object Threading.Mutex($false,'Local\kienzledoku-desktop-setup')
    try{$held=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$held=$true}
    if(!$held){throw 'Ein anderer Kienzledoku-Installer läuft bereits.'}
    Set-PrivateFile $InputPath
    $ui=Read-Json $InputPath
    Assert-KienzledokuClosed $components.Client
    if($Action -eq 'Uninstall'){
        Report 'Gewählte Komponenten werden entfernt.' 10
        if($ui.remove_server -and $components.ServerConfig){
            Assert-KienzledokuPath $components.ServerConfig
            if([IO.Path]::GetFullPath($components.ServerConfig) -ne [IO.Path]::GetFullPath((Join-Path $previous.InstallDirectory 'config.json'))){throw 'Unbekannter Serverpfad.'}
            if([IO.Path]::GetFullPath($previous.StateDirectory) -ne [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'kienzledoku-server'))){throw 'Unbekannter Server-Einstellungspfad.'}
            Assert-KienzledokuPath $previous.InstallDirectory;Assert-KienzledokuPath $previous.StateDirectory
            $options=@();if($ui.remove_models){$options+='-RemoveModels'};if($ui.remove_settings){$options+='-RemoveSettings'}
            Run-Engine 'Uninstall' $components.ServerConfig $options
        }
        if($ui.remove_client){Remove-KienzledokuClient $components.Client -RemoveSettings:$ui.remove_settings}
        Complete-KienzledokuUninstall $components $ui.remove_server $ui.remove_models
        Write-Json $ResultPath @{done=$true;message='Gewählte Komponenten entfernt. Andere WSL-Umgebungen bleiben unverändert.'}
        exit 0
    }
    $state=Join-Path $env:LOCALAPPDATA 'kienzledoku-server'
    $hasServer=$ui.mode -ne 'client';$hasClient=$ui.mode -ne 'server'
    if($hasClient){
        . (Join-Path $root 'client/ClientRuntime.ps1')
        Initialize-ClientRuntime (Join-Path $root 'client') {param($Message) Report $Message 1}
    }
    if($hasServer){
        Report 'Windows-, GPU- und WSL-Voraussetzungen prüfen.' 2
        $hw=Get-Hardware
        if($hw.Build -lt 22000 -or $hw.Architecture -ne 'AMD64'){throw 'Lokaler Server benötigt Windows 11 x64.'}
        if(($hw.RamBytes/1GB)-$ui.wsl_ram_gib -lt 3.5){throw 'Mindestens 4 GB RAM für Windows freihalten.'}
        $cfg=New-WizardServerConfig $ui $previous $hw $state (Get-InstallerVersion) (Get-Catalog $serverRoot)
        [IO.Directory]::CreateDirectory($state)|Out-Null
        Save-Secret $cfg.TokenFile $ui.hf_token
        Save-Secret $cfg.RemoteLlmTokenFile $ui.remote_llm_token
        Save-Secret $cfg.RemoteDiarTokenFile $ui.remote_diar_token
        Save-Secret $cfg.CommanderTokenFile $ui.server_token
        $pending=Join-Path $state 'pending-install.json'
        Write-Json $pending $cfg;Set-PrivateFile $pending
        $engineProgress=Join-Path $state 'progress.json'
        Remove-Item -LiteralPath $engineProgress -ErrorAction SilentlyContinue
        Report 'Serverinstallation vorbereiten.' 5 @{engine_progress=$engineProgress;cancel_path=(Get-AdminRetryCancelPath $cfg)}
        Run-Engine 'Install' $pending
    }
    if($hasClient){
        Report 'Client installieren; Programmdateien und VAD-Laufzeit prüfen.' 89
        & (Join-Path $root 'client/install.ps1') -NoOpen -WizardConfig $InputPath
    }
    Report 'Deinstaller und Programmverknüpfungen fertigstellen.' 97
    Install-KienzledokuMaintenance
    $outcome=@{done=$true;client_installed=$hasClient;message='Installation abgeschlossen';commander_url=$ui.commander_url;launch_url='';server_token=''}
    if($hasServer){
        $outcome.commander_url='http://127.0.0.1:8185'
        if($ui.network -eq 'lan'){$outcome.commander_url='http://'+$ui.listen_host+':8185'}
        if($ui.auth_enabled){$outcome.server_token=([IO.File]::ReadAllText((Join-Path $state 'client.token'))).Trim()}
    }
    if($hasClient){
        $scheme=if($ui.connection_mode -eq 'connect'){'kienzledoku'}else{'kienzledoku-record'}
        $outcome.launch_url=$scheme+'://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}'
    }
    Write-Json $ResultPath $outcome;Set-PrivateFile $ResultPath
} catch {
    $message=$_.Exception.Message
    if($ui){foreach($name in @('hf_token','server_token','remote_llm_token','remote_diar_token','commander_token')){if($ui.PSObject.Properties[$name] -and $ui.$name){$message=$message.Replace($ui.$name,'[Token ausgelassen]')}}}
    if($ResultPath){Write-Json $ResultPath @{done=$false;error=$message}}
    exit 1
} finally {if($held){$mutex.ReleaseMutex()};if($mutex){$mutex.Dispose()}}
