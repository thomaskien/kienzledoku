param(
    [ValidateSet('Install','Download','Start','Stop','Status','Verify','Uninstall','Features','Network')]
    [string]$Action='Install',
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [switch]$RemoveModels
)
Set-StrictMode -Version 2
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'Core.psm1') -Force
$script:InstallerVersion=Get-InstallerVersion
$script:Cfg=Read-Json $ConfigPath
$script:Root=Split-Path -Parent $PSScriptRoot
$script:Token=''
if ($script:Cfg.TokenFile -and (Test-Path -LiteralPath $script:Cfg.TokenFile)) {
    $script:Token=(Get-Content -LiteralPath $script:Cfg.TokenFile -Raw -Encoding UTF8).Trim()
}
$script:ProgressPath=Join-Path $script:Cfg.StateDirectory 'progress.json'
$script:LogPath=Join-Path $script:Cfg.StateDirectory 'installation.log'
[IO.Directory]::CreateDirectory($script:Cfg.StateDirectory) | Out-Null
$script:ModelOptions=Get-ModelOptions $script:Cfg
$script:Cfg | Add-Member -NotePropertyName VerifyModelFiles -NotePropertyValue $script:ModelOptions.VerifyModelFiles -Force
$script:Cfg | Add-Member -NotePropertyName CleanupModelStaging -NotePropertyValue $script:ModelOptions.CleanupModelStaging -Force
$forceModels=$Action -in @('Install','Download') -and $script:ModelOptions.VerifyModelFiles -and $script:Cfg.PSObject.Properties['ForceModelVerification'] -and $script:Cfg.ForceModelVerification
Initialize-ModelVerificationCache (Join-Path $script:Cfg.StateDirectory 'model-verifications.json') -Force:$forceModels
$script:CurrentCommand='';$script:CurrentPhase='initializing'
Set-ModelVerificationMode $script:ModelOptions.VerifyModelFiles {param($message) Progress 'models' $message 12}

function Log([string]$Message) {
    if ($script:Token) { $Message=$Message.Replace($script:Token,'[Token ausgelassen]') }
    $line='[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),$Message
    Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
}
function Progress([string]$Phase,[string]$Message,[int]$Percent) {
    $script:CurrentPhase=$Phase
    Log $Message
    Write-Json $script:ProgressPath @{ Phase=$Phase; Message=$Message; Percent=$Percent; Action=$Action; Finished=$false }
}
function Invoke-Native([string]$Exe,[string[]]$Arguments,[switch]$Capture,[switch]$AllowFailure,[switch]$Result,[Text.Encoding]$OutputEncoding=[Text.Encoding]::UTF8) {
    # Stream both pipes: pip/apt write progress to stderr even on success. Avoid
    # Windows PowerShell's NativeCommandError conversion, and never invoke cmd.
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$Exe;$info.Arguments=ConvertTo-NativeArguments $Arguments;$info.UseShellExecute=$false
    $info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $info.StandardOutputEncoding=$OutputEncoding
    $info.StandardErrorEncoding=$OutputEncoding
    $process=New-Object Diagnostics.Process;$process.StartInfo=$info
    $lines=New-Object 'Collections.Generic.List[string]'
    $recent=New-Object 'Collections.Generic.Queue[string]'
    $command=$Exe+' '+(ConvertTo-NativeArguments $Arguments)
    if($script:Token){$command=$command.Replace($script:Token,'[Token ausgelassen]')}
    $script:CurrentCommand=$command
    try{
        $null=$process.Start()
        if(-not $Capture -and -not $Result){Log ('Prozess '+$process.Id+': '+$command)}
        if(Get-Variable -Name Cfg -Scope Script -ErrorAction SilentlyContinue){
            Write-Json (Join-Path $script:Cfg.StateDirectory 'native-process.json') @{Command=$command;Pid=$process.Id;Phase=$script:CurrentPhase;StartedAt=(Get-Date).ToString('o')}
        }
        $stdout=$process.StandardOutput.ReadLineAsync();$stderr=$process.StandardError.ReadLineAsync()
        while($null -ne $stdout -or $null -ne $stderr){
            foreach($name in @('stdout','stderr')){
                $task=Get-Variable -Name $name -ValueOnly
                if($null -ne $task -and $task.IsCompleted){
                    $line=$task.GetAwaiter().GetResult()
                    if($null -eq $line){Set-Variable -Name $name -Value $null}
                    else{
                        if($Capture -or $Result){
                            $lines.Add($line)
                            if($line.StartsWith('MODEL_CHECK:')){Progress 'models' $line.Substring(12) 10}
                        }else{
                            Log $line;$recent.Enqueue($line);if($recent.Count -gt 15){$null=$recent.Dequeue()}
                        }
                        $reader=$process.StandardOutput;if($name -eq 'stderr'){$reader=$process.StandardError}
                        Set-Variable -Name $name -Value ($reader.ReadLineAsync())
                    }
                }
            }
            Start-Sleep -Milliseconds 30
        }
        $process.WaitForExit()
        if($Result){return [pscustomobject]@{ExitCode=$process.ExitCode;Output=($lines -join "`n").Trim()}}
        if($process.ExitCode -ne 0){
            foreach($line in $lines){Log $line}
            if($AllowFailure){return $process.ExitCode}
            $detail=('Aufruf fehlgeschlagen: {0}`r`nExitcode {1} (0x{1:X8})' -f $command,$process.ExitCode).Replace('`r`n',"`r`n")
            if($recent.Count){$detail+="`r`nLetzte Programmausgaben:`r`n"+($recent.ToArray() -join "`r`n")}
            throw $detail
        }
        if($AllowFailure){return 0}
        if($Capture){return ($lines -join "`n").Trim([char]0).Trim()}
    }finally{$process.Dispose()}
}
function Invoke-WslManagement([string[]]$Arguments,[switch]$Capture,[switch]$AllowFailure,[switch]$Result) {
    # wsl.exe management output is UTF-16LE, unlike Linux --exec output (UTF-8).
    $exe=Get-WslExecutable
    Log ('WSL-Aufruf: '+$exe+' '+(ConvertTo-NativeArguments $Arguments))
    Invoke-Native $exe $Arguments -Capture:$Capture -AllowFailure:$AllowFailure -Result:$Result -OutputEncoding ([Text.Encoding]::Unicode)
}
function Get-WslVersion($Probe) {
    if($Probe.ExitCode -ne 0){return $null}
    $first=@($Probe.Output -split '\r?\n'|Where-Object {$_.Trim()})|Select-Object -First 1
    if($first -match '(?i)WSL.*?[:：]\s*(\d+\.\d+\.\d+(?:\.\d+)?)') {return [version]$Matches[1]}
    return $null
}
function Initialize-WslFeatures {
    $restart=$false
    foreach($name in @('VirtualMachinePlatform','Microsoft-Windows-Subsystem-Linux')){
        $feature=Get-WindowsOptionalFeature -Online -FeatureName $name
        if($feature.State -eq 'Enabled'){continue}
        if($feature.State -in @('EnablePending','DisablePending')){$restart=$true;continue}
        Log ('Windows-Komponente aktivieren: '+$name)
        $result=Enable-WindowsOptionalFeature -Online -FeatureName $name -All -NoRestart
        if($result.RestartNeeded){$restart=$true}
    }
    if($restart){return 3010}
    $probe=Invoke-WslManagement @('--version') -Result
    $version=Get-WslVersion $probe
    if($version -and $version -ge [version]'2.0.0'){Log ('WSL bereits installiert: '+$version);return 0}
    $arguments=@('--install','--no-distribution','--web-download')
    if($version){$arguments=@('--update','--web-download')}
    Log ('WSL einrichten: wsl.exe '+($arguments -join ' '))
    $install=Invoke-WslManagement $arguments -Result
    Log $install.Output
    if($install.ExitCode -in @(3010,1641)){return 3010}
    # A fresh WSL bootstrap may install the package yet return -1 because no
    # distro exists. Verify the actual installed CLI; never trust success text
    # or silently swallow an unsuccessful installation.
    $probe=Invoke-WslManagement @('--version') -Result
    $version=Get-WslVersion $probe
    if($version -and $version -ge [version]'2.0.0'){
        Log ('WSL-Versionsprüfung erfolgreich: '+$version+' (Bootstrap-Exit '+$install.ExitCode+'). Eigene Ubuntu-Umgebung folgt.')
        return 0
    }
    Log $probe.Output
    throw ('WSL ist nach Installation/Aktualisierung nicht mit mindestens Version 2.0.0 nachweisbar (Exit '+$install.ExitCode+'). installation.log prüfen.')
}
function Wsl([string[]]$Arguments,[switch]$Capture) {
    Invoke-Native (Get-WslExecutable) (@('--distribution','kienzledoku-server','--user','root','--exec')+$Arguments) -Capture:$Capture
}
function Wsl-Path([string]$WindowsPath) {
    $path=Wsl @('wslpath','-u',$WindowsPath) -Capture
    if (-not $path.StartsWith('/')) { throw 'Windows-Pfad konnte nicht in WSL geöffnet werden.' }
    $path
}
function Is-Admin {
    $principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Registered-Distros {
    foreach($key in @(Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' -ErrorAction SilentlyContinue)){
        $value=Get-ItemProperty -LiteralPath $key.PSPath
        if($value.PSObject.Properties['DistributionName']){[string]$value.DistributionName}
    }
}
function Get-OwnDistroDirectory {
    foreach($key in @(Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' -ErrorAction SilentlyContinue)){
        $value=Get-ItemProperty -LiteralPath $key.PSPath
        if($value.PSObject.Properties['DistributionName'] -and $value.DistributionName -eq 'kienzledoku-server'){
            if(-not $value.PSObject.Properties['BasePath']){throw 'WSL-Datenverzeichnis kann nicht ermittelt werden.'}
            $path=[Environment]::ExpandEnvironmentVariables([string]$value.BasePath)
            if($path.StartsWith('\\?\') -or $path.StartsWith('\??\')){$path=$path.Substring(4)}
            return $path
        }
    }
    return ''
}
function Assert-InstallationSpace {
    Progress 'space' 'Zusätzlichen Platzbedarf prüfen; vorhandene geprüfte Modelle berücksichtigen.' 1
    $files=@(Get-RequiredFiles $script:Root $script:Cfg.Models)
    [long]$total=($files | Measure-Object -Property bytes -Sum).Sum
    $directory=Get-OwnDistroDirectory
    $script:StorageProbe=[pscustomobject]@{AdditionalBytes=$total;ReusedBytes=0;ReusedFiles=0;RuntimeReady=$false;RequiredPaths=@($files | ForEach-Object {$_.path});FreeBytes=$null}
    $planned=(Get-Variable -Name ModelPlan -Scope Script -ErrorAction SilentlyContinue) -and $script:ModelPlan
    if($planned){$script:StorageProbe=$script:PlannedStorageProbe}
    elseif($directory){
        $source=[IO.File]::ReadAllText((Join-Path $script:Root 'windows/storage_probe.py'))
        $probeFiles=@($files | Select-Object path,bytes,sha256,git_blob_sha1)
        $request=@{Files=$probeFiles;Force=[bool]$forceModels} | ConvertTo-Json -Depth 24 -Compress
        $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($request))
        $raw=Wsl @('python3','-c',$source,$encoded) -Capture
        $line=@($raw -split '\r?\n' | Where-Object {$_.StartsWith('KIENZLEDOKU_STORAGE=')}) | Select-Object -Last 1
        if(-not $line){throw 'WSL-Platzprüfung liefert keinen gültigen Bestand. installation.log prüfen.'}
        $script:StorageProbe=$line.Substring('KIENZLEDOKU_STORAGE='.Length) | ConvertFrom-Json
    }else{$directory=Join-Path $script:Cfg.InstallDirectory 'wsl'}
    if(-not $directory){$directory=Join-Path $script:Cfg.InstallDirectory 'wsl'}
    $requirements=@(@{Path=$script:Cfg.InstallDirectory;Bytes=64MB;Reason='Assistent und Konfiguration'},
                    @{Path=$script:Cfg.StateDirectory;Bytes=128MB;Reason='Protokolle und Zwischenstände'})
    if($planned){
        $stageFiles=@($files | Where-Object {$script:ModelPlan[$_.path].Kind -eq 'pending' -and $script:ModelPlan[$_.path].Owned})
        $archiveFiles=@($files | Where-Object {$script:ModelPlan[$_.path].Kind -eq 'pending' -and -not $script:ModelPlan[$_.path].Owned})
        $stageSpace=Get-ModelTargetSpace (Get-StageDirectory) $stageFiles -Missing
        $requirements+=@{Path=$script:Cfg.InstallDirectory;Bytes=$stageSpace.AdditionalBytes;Reason='Noch benötigte lokale Zwischenkopien'}
        if($archiveFiles.Count){
            $cacheSpace=Get-ModelTargetSpace $script:Cfg.CacheDirectory $archiveFiles -Missing
            $requirements+=@{Path=$script:Cfg.CacheDirectory;Bytes=([long]$cacheSpace.AdditionalBytes+64MB);Reason='Fehlende Modelle im lokalen Archiv'}
        }
    }else{
    if(-not(Test-NetworkPath $script:Cfg.CacheDirectory)){
        $cacheSpace=Get-ModelTargetSpace $script:Cfg.CacheDirectory $files
        $requirements+=@{Path=$script:Cfg.CacheDirectory;Bytes=([long]$cacheSpace.AdditionalBytes+64MB);Reason='Fehlende Dateien und Metadaten im Modellarchiv'}
    }else{
        $stageFiles=@($files | Where-Object {$_.path -in $script:StorageProbe.RequiredPaths})
        $stageSpace=Get-ModelTargetSpace (Join-Path $script:Cfg.InstallDirectory 'models') $stageFiles
        $requirements+=@{Path=$script:Cfg.InstallDirectory;Bytes=$stageSpace.AdditionalBytes;Reason='Noch benötigte lokale Netzlaufwerk-Zwischenkopien'}
    }
    }
    [long]$reserve=35GB;if($script:StorageProbe.RuntimeReady){$reserve=5GB}
    [long]$wslNeed=[long]$script:StorageProbe.AdditionalBytes+$reserve
    $requirements+=@{Path=$directory;Bytes=$wslNeed;Reason=('WSL: fehlende Modelle und '+($reserve/1GB)+' GiB Laufzeitreserve')}
    if(-not $script:StorageProbe.RuntimeReady){$requirements+=@{Path=$script:Cfg.StateDirectory;Bytes=1GB;Reason='Ubuntu-Download und Bootstrap'}}
    $plan=@(Get-VolumeSpacePlan $requirements)
    Write-Json (Join-Path $script:Cfg.StateDirectory 'disk-space.json') @{Volumes=$plan;Wsl=$script:StorageProbe;RuntimeReserveBytes=$reserve}
    Log ('WSL-Modellbestand: '+$script:StorageProbe.ReusedFiles+' Dateien wiederverwendbar; zusätzlich '+('{0:N2}' -f ($script:StorageProbe.AdditionalBytes/1GB))+' GiB. Laufzeitreserve '+($reserve/1GB)+' GiB.')
    foreach($volume in $plan){Log ('Platz auf {0}: zusätzlich benötigt {1:N2} GiB, frei {2:N2} GiB; {3}' -f $volume.Volume,($volume.RequiredBytes/1GB),($volume.AvailableBytes/1GB),($volume.Components -join '; '))}
    Assert-VolumeSpace $plan
    if($null -ne $script:StorageProbe.FreeBytes -and [long]$script:StorageProbe.FreeBytes -lt $wslNeed){
        throw ('Zu wenig freier Platz innerhalb der WSL-Umgebung: zusätzlich benötigt {0:N2} GiB, frei {1:N2} GiB. disk-space.json prüfen.' -f ($wslNeed/1GB),($script:StorageProbe.FreeBytes/1GB))
    }
}
function Invoke-AdminProcess([string]$FilePath,[string]$Arguments) {
    # Start-Process can replace a Win32Exception with a message-only error.
    # Call the same shell elevation API through .NET to retain NativeErrorCode.
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$FilePath;$info.Arguments=$Arguments
    $info.UseShellExecute=$true;$info.Verb='runas'
    $process=New-Object Diagnostics.Process;$process.StartInfo=$info
    try{
        if(-not $process.Start()){throw 'Der administrative Prozess konnte nicht gestartet werden.'}
        $process.WaitForExit()
        return $process.ExitCode
    }finally{$process.Dispose()}
}
function Assert-AdminRetryNotCancelled {
    $path=Get-AdminRetryCancelPath $script:Cfg
    if($path -and [IO.File]::Exists($path)){
        throw [OperationCanceledException]::new('Installation vom Benutzer abgebrochen. Bereits übernommene Modelle und Zwischenkopien bleiben erhalten.')
    }
}
function Wait-AdminRetry([string]$Description,[long]$Attempt,[int]$Percent) {
    Progress 'admin_wait' ('Administrator nicht bestätigt; neuer Versuch in 30 Sekunden. Schritt: '+$Description+'. Versuch '+$Attempt+'.') $Percent
    foreach($second in 1..30){Assert-AdminRetryNotCancelled;Start-Sleep -Seconds 1}
    Assert-AdminRetryNotCancelled
}
function Elevated([string]$Operation) {
    $arguments='-NoProfile -ExecutionPolicy Bypass -File "{0}" -Action {1} -ConfigPath "{2}"' -f $PSCommandPath,$Operation,$ConfigPath
    $description='WSL-Voraussetzungen';$phase='wsl';$percent=44
    if($Operation -eq 'Network'){$description='Netzwerkfreigabe (Firewall und Portweiterleitung)';$phase='network';$percent=96}
    [long]$attempt=0
    while($true){
        Assert-AdminRetryNotCancelled;$attempt++
        $script:CurrentCommand='Windows-Administratoranforderung: '+$Operation+'; Versuch '+$attempt
        Progress 'admin_prompt' ('Windows fragt nach Administratorrechten für '+$description+' (Versuch '+$attempt+'). Die Sicherheitsabfrage auf dem Windows-Desktop bestätigen.') $percent
        try{
            $code=Invoke-AdminProcess (Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe') $arguments
        }catch{
            $cause=$_.Exception;$unconfirmed=$false
            while($cause){
                if($cause -is [ComponentModel.Win32Exception] -and $cause.NativeErrorCode -eq 1223){$unconfirmed=$true;break}
                $cause=$cause.InnerException
            }
            if(-not $unconfirmed){throw}
            Wait-AdminRetry $description $attempt $percent
            continue
        }
        # This code belongs to the elevated helper after consent. A real
        # feature/network failure must not be mistaken for a missed prompt.
        Assert-AdminRetryNotCancelled
        if($code -notin @(0,3010)){throw "Administrativer Schritt fehlgeschlagen: $Operation (Exit $code)."}
        Progress $phase ('Administrativer Schritt abgeschlossen: '+$description+'.') $percent
        return $code
    }
}
function Ensure-Wsl {
    Progress 'wsl' 'WSL2-Voraussetzungen prüfen und bei Bedarf ergänzen.' 44
    $code=Elevated 'Features'
    if ($code -eq 3010) { throw [InvalidOperationException]::new('NEUSTART: Windows neu starten und die installierte Verknüpfung Installation fortsetzen öffnen.') }
    $registered=@(Registered-Distros)
    $runningText=''
    try{$runningText=Invoke-WslManagement @('--list','--running','--quiet') -Capture}catch{
        if($registered.Count){throw}
    }
    $running=@($runningText.Replace([string][char]0,'') -split '\r?\n' | ForEach-Object {$_.Trim()} | Where-Object {$_ -in $registered})
    $other=@($running | Where-Object { $_ -ne 'kienzledoku-server' })
    if ($other.Count) { throw ('Andere WSL-Instanzen laufen: '+($other -join ', ')+'. Diese zuerst schließen; danach Installation fortsetzen. Das RAM-Limit gilt für alle WSL2-Instanzen dieses Benutzers.') }
    $path=Join-Path $env:USERPROFILE '.wslconfig'
    $old='';if(Test-Path -LiteralPath $path){$old=Get-Content -LiteralPath $path -Raw -Encoding UTF8}
    if($old -match '(?im)^\s*localhostForwarding\s*=\s*false\s*(?:#.*)?$'){
        throw 'Die vorhandene .wslconfig deaktiviert localhostForwarding. Für die Windows-Anbindung muss dieser Wert auf true gesetzt werden. Bestehende Einstellungen werden nicht still überschrieben.'
    }
    $new=Set-WslMemoryText $old $script:Cfg.WslRamGiB
    if ($old -ne $new) {
        if(Test-Path -LiteralPath $path){Copy-Item -LiteralPath $path -Destination ($path+'.kienzledoku-'+(Get-Date -Format 'yyyyMMddHHmmss')+'.bak')}
        [IO.File]::WriteAllText($path,$new,(New-Object Text.UTF8Encoding($false)))
        # No unrelated running instances exist; restart the utility VM to apply memory.
        Invoke-WslManagement @('--shutdown')
    }
    $names=@(Registered-Distros)
    $distroPath=Join-Path $script:Cfg.InstallDirectory 'wsl'
    if ('kienzledoku-server' -notin $names) {
        Progress 'wsl' 'Eigene Ubuntu-24.04-Umgebung herunterladen und prüfen.' 48
        $ubuntu=Read-Json (Join-Path $script:Root 'ubuntu.json')
        $url=$ubuntu.url
        $archive=Join-Path $script:Cfg.StateDirectory 'ubuntu-24.04.5.wsl'
        $sha=$ubuntu.sha256
        if (-not (Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $sha) {
            Get-Download $url $archive
            if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $sha) { throw 'Ubuntu-Prüfsumme stimmt nicht.' }
        }
        Invoke-WslManagement @('--import','kienzledoku-server',$distroPath,$archive,'--version','2')
        Wsl @('mkdir','-p','/etc/kienzledoku-server')
        Wsl @('touch','/etc/kienzledoku-server/windows-installer-owned')
    } else {
        $null=Wsl @('test','-f','/etc/kienzledoku-server/windows-installer-owned') -Capture
    }
    $wslConf="[boot]`nsystemd=true`n[user]`ndefault=root`n"
    $temporary=Join-Path $script:Cfg.StateDirectory 'wsl.conf'
    [IO.File]::WriteAllText($temporary,$wslConf,(New-Object Text.UTF8Encoding($false)))
    Wsl @('cp',(Wsl-Path $temporary),'/etc/wsl.conf')
    Invoke-WslManagement @('--terminate','kienzledoku-server')
    Wsl @('true')
    $kernel=Wsl @('uname','-r') -Capture
    if ($kernel -notmatch 'WSL2|microsoft-standard') { throw 'Die eigene Instanz läuft nicht unter WSL2.' }
    $pid1=Wsl @('cat','/proc/1/comm') -Capture
    if ($pid1.Trim() -ne 'systemd') { throw 'systemd startet nicht. WSL aktualisieren und fortsetzen.' }
}
function Ensure-ModelFiles {
    if($Action -eq 'Install'){Ensure-InstallModels;return}
    Progress 'models' 'Modellarchiv für den reinen Download vorbereiten.' 3
    $hfChecked=$false
    $files=@(Get-RequiredFiles $script:Root $script:Cfg.Models)
    $groups=Get-ModelSourceGroups
    $sources=@((Get-StageDirectory))+$groups.Local+$groups.Remote
    $cacheSpace=Get-ModelTargetSpace $script:Cfg.CacheDirectory $files
    [long]$needed=$cacheSpace.AdditionalBytes
    $driveRoot=[IO.Path]::GetPathRoot($script:Cfg.CacheDirectory)
    if ($driveRoot -notlike '\\*') {
        $free=(New-Object IO.DriveInfo($driveRoot)).AvailableFreeSpace
        if($free -lt $needed+64MB){throw ('Zu wenig freier Speicher im Modell-Downloadverzeichnis: zusätzlich benötigt {0:N2} GiB einschließlich Metadatenreserve, frei {1:N2} GiB.' -f (($needed+64MB)/1GB),($free/1GB))}
    }
    $index=0
    foreach($file in $files){
        $index++
        Progress 'models' ("Prüfe/übernehme $($file.path) ($index/$($files.Count)).") (4+[int](36*$index/$files.Count))
        $dest=Get-ContainedPath $script:Cfg.CacheDirectory $file.path
        $hits=(Get-ModelVerificationStats).Reused
        if(Test-ModelFile $dest $file -Full){
            if((Get-ModelVerificationStats).Reused -gt $hits){Log ('Bereits geprüft, unverändert: '+$file.path)}
            continue
        }
        $source=Find-ModelFile $sources $file -Full
        [IO.Directory]::CreateDirectory((Split-Path -Parent $dest)) | Out-Null
        if($source){
            Remove-ModelVerification ($dest+'.part')
            Copy-Item -LiteralPath $source -Destination ($dest+'.part') -Force
            if(-not(Test-ModelFile ($dest+'.part') $file -Full)){throw 'Kopierte Datei stimmt nicht: '+$file.path}
            Move-VerifiedModelFile ($dest+'.part') $dest $file
        }else{
            if($file.PSObject.Properties['gated'] -and $file.gated -and -not $hfChecked){Test-HfAccess $script:Token $script:Root;$hfChecked=$true}
            Progress 'models' ('Lade '+$file.path+'. Vorhandene .part-Dateien werden fortgesetzt.') (4+[int](36*$index/$files.Count))
            Get-Download $file.url $dest $script:Token $file.bytes
            if(-not(Test-ModelFile $dest $file -Full)){
                Move-Item -LiteralPath $dest -Destination ($dest+'.ungueltig-'+(Get-Date -Format 'yyyyMMddHHmmss')) -Force
                throw 'Download-Prüfsumme stimmt nicht: '+$file.path
            }
        }
    }
    Write-Json (Join-Path $script:Cfg.CacheDirectory 'verified-manifest.json') @{ Version=$script:InstallerVersion; Models=$script:Cfg.Models; Files=$files; ChecksumsVerified=$script:ModelOptions.VerifyModelFiles; VerifiedAt=$(if($script:ModelOptions.VerifyModelFiles){(Get-Date).ToString('o')}else{$null}) }
}
function Install-App {
    $app=Join-Path $script:Cfg.InstallDirectory 'app'
    [IO.Directory]::CreateDirectory($app) | Out-Null
    if([IO.Path]::GetFullPath($app) -ne [IO.Path]::GetFullPath($script:Root)){
        foreach($name in @('windows','VERSION','models.json','audio-files.json','ubuntu.json','linux-payload.tar','README.txt')){
            Copy-Item -LiteralPath (Join-Path $script:Root $name) -Destination $app -Recurse -Force
        }
    }
    $installedConfig=Join-Path $script:Cfg.InstallDirectory 'config.json'
    Write-Json $installedConfig $script:Cfg
    Set-PrivateFile $installedConfig
    $shell=New-Object -ComObject WScript.Shell
    $folder=Join-Path ([Environment]::GetFolderPath('Programs')) 'kienzledoku Server'
    [IO.Directory]::CreateDirectory($folder) | Out-Null
    foreach($item in @(@('Server starten','Start'),@('Server stoppen','Stop'),@('Serverstatus','Status'),@('Server prüfen','Verify'),@('Server deinstallieren','Uninstall'))){
        $link=$shell.CreateShortcut((Join-Path $folder ($item[0]+'.lnk')))
        $link.TargetPath=Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $link.Arguments='-NoProfile -ExecutionPolicy Bypass -File "{0}" -Action {1} -ConfigPath "{2}"' -f (Join-Path $app 'windows\Control.ps1'),$item[1],$installedConfig
        $link.WorkingDirectory=$app;$link.Save()
    }
    $link=$shell.CreateShortcut((Join-Path $folder 'Installation fortsetzen.lnk'))
    $link.TargetPath=Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $link.Arguments='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -STA -File "{0}" -ResumeConfig "{1}"' -f (Join-Path $app 'windows\Wizard.ps1'),$installedConfig
    $link.WorkingDirectory=$app;$link.Save()
    $reg='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\kienzledoku-server'
    $null=New-Item -Path $reg -Force
    $uninstall='"{0}" -NoProfile -ExecutionPolicy Bypass -File "{1}" -Action Uninstall -ConfigPath "{2}"' -f (Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe'),(Join-Path $app 'windows\Control.ps1'),$installedConfig
    foreach($pair in @(@('DisplayName','kienzledoku Server Installer'),@('DisplayVersion',$script:InstallerVersion),@('Publisher','kienzledoku'),@('InstallLocation',$script:Cfg.InstallDirectory),@('UninstallString',$uninstall))){Set-ItemProperty -Path $reg -Name $pair[0] -Value $pair[1]}
    foreach($name in @('NoModify','NoRepair')){Set-ItemProperty -Path $reg -Name $name -Type DWord -Value 1}
}
function Set-ServerNetwork {
    if(-not(Is-Admin)){throw 'Administratorrechte fehlen. Netzwerkfreigabe im erhöhten Installationsschritt ausführen.'}
    $state=Join-Path $script:Cfg.StateDirectory 'network-owned.json'
    if(Test-Path -LiteralPath $state){
        $previous=Read-Json $state
        $null=Invoke-Native 'netsh.exe' @('interface','portproxy','delete','v4tov4',('listenaddress='+$previous.Address),'listenport=8185') -AllowFailure
        Remove-Item -LiteralPath $state -Force
    }
    Get-NetFirewallRule -Name 'kienzledoku-server-8185' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if($script:Cfg.NetworkMode -ne 'lan' -or $script:Cfg.NetworkRemove){return}
    $ip=[Net.IPAddress]::Parse($script:Cfg.NetworkAddress)
    if($ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or [Net.IPAddress]::IsLoopback($ip) -or $ip.ToString() -eq '0.0.0.0'){throw 'Konkrete lokale IPv4-Adresse erforderlich.'}
    if(-not(Get-NetIPAddress -AddressFamily IPv4 -IPAddress $ip.ToString() -ErrorAction SilentlyContinue)){throw 'Ausgewählte Netzwerk-IP ist auf diesem Rechner nicht vorhanden.'}
    $busy=@(Get-NetTCPConnection -LocalPort 8185 -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalAddress -in @($ip.ToString(),'0.0.0.0','::')})
    if($busy.Count){throw 'Port 8185 ist auf der ausgewählten Netzwerkadresse bereits belegt. Bestehenden Dienst prüfen.'}
    Start-Service iphlpsvc
    # The selected LAN address is explicitly authorized by the user. Windows
    # commonly classifies new Ethernet networks as Public. Scope by address,
    # port and LocalSubnet instead of accidentally excluding that profile.
    Write-Json $state @{Address=$ip.ToString();Port=8185;FirewallProfile='Any'}
    Invoke-Native 'netsh.exe' @('interface','portproxy','add','v4tov4',('listenaddress='+$ip.ToString()),'listenport=8185','connectaddress=127.0.0.1','connectport=8185')
    $null=New-NetFirewallRule -Name 'kienzledoku-server-8185' -DisplayName 'kienzledoku Server (8185)' -Direction Inbound -Action Allow -Enabled True -Protocol TCP -LocalPort 8185 -LocalAddress $ip.ToString() -RemoteAddress LocalSubnet -Profile Any
    $rule=Get-NetFirewallRule -Name 'kienzledoku-server-8185' -PolicyStore ActiveStore -ErrorAction Stop
    if(-not $rule -or $rule.Enabled.ToString() -ne 'True' -or $rule.Profile.ToString() -ne 'Any' -or $rule.Action.ToString() -ne 'Allow'){
        throw 'Die Server-Firewallregel ist nicht mit allen Netzwerkprofilen aktiv. Windows-Firewallrichtlinien prüfen.'
    }
    Log ('Firewallregel aktiv: '+$ip.ToString()+':8185; TCP; lokales Subnetz; alle Netzwerkprofile. Windows-Netzwerkprofil unverändert.')
}
function Configure-Network {
    $owned=Test-Path -LiteralPath (Join-Path $script:Cfg.StateDirectory 'network-owned.json')
    $rule=Get-NetFirewallRule -Name 'kienzledoku-server-8185' -ErrorAction SilentlyContinue
    if($script:Cfg.NetworkMode -eq 'local' -and -not $owned -and -not $rule){return}
    $null=Elevated 'Network'
    if($script:Cfg.NetworkMode -eq 'lan'){
        $address=$script:Cfg.NetworkAddress
        Log ('Netzwerk-Endpunkt: http://'+$address+':8185')
    }
}
function Configure-Autostart {
    # HKCU Run needs no administrator credentials and starts in the same account
    # that owns the WSL distribution, after that user's Windows logon.
    $path='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $null=New-Item -Path $path -Force
    if($script:Cfg.Autostart){
        $control=Join-Path $script:Cfg.InstallDirectory 'app\windows\Control.ps1'
        $config=Join-Path $script:Cfg.InstallDirectory 'config.json'
        $command='"{0}" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{1}" -Action Start -ConfigPath "{2}" -Quiet' -f (Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe'),$control,$config
        Set-ItemProperty -Path $path -Name 'kienzledoku Server' -Value $command
    }else{
        Remove-ItemProperty -Path $path -Name 'kienzledoku Server' -ErrorAction SilentlyContinue
    }
}
function Ensure-KeepAlive {
    $marker='/opt/kienzledoku-server/installer/keep_alive.py'
    $existing=@(Get-CimInstance Win32_Process -Filter "Name = 'wsl.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine.Contains($marker) -and $_.CommandLine.Contains('kienzledoku-server')
    })
    if(-not $existing.Count){
        $arguments='--distribution kienzledoku-server --user root --exec python3 '+$marker
        $null=Start-Process -FilePath (Get-WslExecutable) -ArgumentList $arguments -WindowStyle Hidden -PassThru
    }
}
function Assert-WindowsEndpoint([string]$Address,[string]$Token) {
    $request=[Net.HttpWebRequest]::Create('http://'+$Address+':8185/v1/runtime/status')
    $request.Proxy=$null;$request.AllowAutoRedirect=$false;$request.Timeout=15000
    $request.Headers['Authorization']='Bearer '+$Token
    $response=$request.GetResponse()
    try{
        $reader=New-Object IO.StreamReader($response.GetResponseStream())
        try{$status=$reader.ReadToEnd()|ConvertFrom-Json}finally{$reader.Dispose()}
        if($status.name -ne 'kienzledoku-commander' -or -not $status.asr_ready -or $status.last_error){throw 'Server-Endpunkt meldet keine fehlerfreie ASR-Bereitschaft.'}
    }finally{$response.Dispose()}
    Log ('Windows-Endpunkt lokal geprüft: '+$Address+':8185 (Aufruf vom Serverrechner).')
}

. (Join-Path $PSScriptRoot 'Models.ps1')
$operationMutex=$null;$operationHeld=$false
try {
    if($env:OS -ne 'Windows_NT'){throw 'Windows 11 x64 erforderlich.'}
    Log ('Installer '+$script:InstallerVersion+'; Aktion '+$Action+'; 64-Bit-Prozess='+[Environment]::Is64BitProcess)
    if($Action -notin @('Features','Network')){
        $operationMutex=New-Object Threading.Mutex($false,'Local\kienzledoku-server-operation')
        try{$operationHeld=$operationMutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$operationHeld=$true}
        if(-not $operationHeld){throw 'Ein anderer Installations- oder Servervorgang läuft bereits.'}
        $cancelPath=Get-AdminRetryCancelPath $script:Cfg
        if($cancelPath){Remove-Item -LiteralPath $cancelPath -Force -ErrorAction SilentlyContinue}
    }
    if($Action -eq 'Features'){
        if(-not(Is-Admin)){throw 'Administratorrechte fehlen.'}
        $featureCode=Initialize-WslFeatures
        exit $featureCode
    }
    if($Action -eq 'Network'){
        Set-ServerNetwork
        exit 0
    }
    if($Action -in @('Download','Install')){
        $script:Cfg.Version=$script:InstallerVersion
        if($Action -eq 'Install'){
            $hw=Get-Hardware
            if($hw.Build -lt 22000 -or $hw.Architecture -ne 'AMD64'){throw 'Windows 11 x64 erforderlich.'}
            if(($hw.RamBytes/1GB)-$script:Cfg.WslRamGiB -lt 3.5){throw 'Mindestens etwa 4 GiB müssen für Windows eingeplant bleiben. Kleinere WSL-Stufe wählen.'}
            $gpu=@($hw.Gpus | Where-Object {$_.Index -eq $script:Cfg.GpuIndex})
            if($gpu.Count -ne 1){throw 'Ausgewählte NVIDIA-GPU fehlt. Windows-Treiber installieren.'}
            $parallelModel='';if($script:Cfg.PSObject.Properties['ParallelModel']){$parallelModel=[string]$script:Cfg.ParallelModel}
            $script:Cfg.Profiles=Get-ProfilePlan (Get-Catalog $script:Root) $script:Cfg.Models $script:Cfg.DefaultModel $script:Cfg.Mode $gpu[0].VramMiB $script:Cfg.WslRamGiB $script:Cfg.AudioCache $parallelModel
            if(Test-NetworkPath $script:Cfg.InstallDirectory){throw 'Die aktive WSL-Umgebung benötigt ein lokales Laufwerk.'}
            Initialize-ModelPlan
            $script:PlannedStorageProbe=$script:StorageProbe
            Assert-InstallationSpace
            Install-App
        }
        Ensure-ModelFiles
        if($Action -eq 'Install'){
            Ensure-Wsl
            Set-LinuxModelSources
            $linuxConfig=Join-Path $script:Cfg.StateDirectory 'linux-install.json'
            Write-Json $linuxConfig $script:Cfg
            Progress 'server' 'Serverlaufzeiten und Modelle in der eigenen WSL-Umgebung installieren. Dieser Schritt kann länger dauern.' 58
            Wsl @('mkdir','-p','/opt/kienzledoku-server/installer')
            Wsl @('tar','-xf',(Wsl-Path (Join-Path $script:Root 'linux-payload.tar')),'-C','/opt/kienzledoku-server/installer')
            Wsl @('python3','/opt/kienzledoku-server/installer/install_server.py','--config',(Wsl-Path $linuxConfig))
            Progress 'start' 'Server starten und Bereitschaft prüfen.' 87
            Wsl @('python3','/opt/kienzledoku-server/installer/control.py','start')
            Ensure-KeepAlive
            if($script:Cfg.Verify){
                Progress 'verify' 'Synthetische Audiokette und ausgewählte Modelle prüfen.' 91
                Wsl @('python3','/opt/kienzledoku-server/installer/control.py','verify')
            }
            Progress 'network' 'Netzwerkfreigabe einrichten. Die folgende Windows-Administratorabfrage bestätigen.' 96
            Configure-Network;Configure-Autostart
            # Secret output is captured directly to a protected local file, never logged.
            $token=Wsl @('python3','/opt/kienzledoku-server/installer/control.py','token') -Capture
            Assert-WindowsEndpoint '127.0.0.1' $token
            if($script:Cfg.NetworkMode -eq 'lan'){Assert-WindowsEndpoint $script:Cfg.NetworkAddress $token}
            $clientFile=Join-Path $script:Cfg.StateDirectory 'client.token'
            [IO.File]::WriteAllText($clientFile,$token,(New-Object Text.UTF8Encoding($false)));Set-PrivateFile $clientFile
            if(-not $script:Cfg.StartAfterInstall){Wsl @('python3','/opt/kienzledoku-server/installer/control.py','stop')}
            Write-Json (Join-Path $script:Cfg.InstallDirectory 'config.json') $script:Cfg
            Set-PrivateFile (Join-Path $script:Cfg.InstallDirectory 'config.json')
            Complete-ModelStaging
            if(-not $script:Cfg.StartAfterInstall){Invoke-WslManagement @('--terminate','kienzledoku-server')}
        }
    }elseif($Action -eq 'Uninstall'){
        if($RemoveModels){Wsl @('python3','/opt/kienzledoku-server/installer/control.py','remove-models')}
        else{Wsl @('python3','/opt/kienzledoku-server/installer/control.py','stop')}
        $script:Cfg | Add-Member -NotePropertyName NetworkRemove -NotePropertyValue $true -Force
        Write-Json $ConfigPath $script:Cfg
        Configure-Network
        Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'kienzledoku Server' -ErrorAction SilentlyContinue
        Invoke-WslManagement @('--terminate','kienzledoku-server')
        if($RemoveModels){Invoke-WslManagement @('--unregister','kienzledoku-server')}
        Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Programs')) 'kienzledoku Server') -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\kienzledoku-server' -Recurse -Force -ErrorAction SilentlyContinue
        Log 'Server deaktiviert. WSL/Modelle bleiben bei gewähltem Behalten erhalten; Downloadquellen wurden nicht gelöscht.'
    }else{
        if($Action -eq 'Status'){
            $statusText=Wsl @('python3','/opt/kienzledoku-server/installer/control.py','status') -Capture
            Log $statusText
        }elseif($Action -eq 'Verify'){
            $wasRunning=(Wsl @('python3','/opt/kienzledoku-server/installer/control.py','state') -Capture | ConvertFrom-Json).active
            try{
                if(-not $wasRunning){Wsl @('python3','/opt/kienzledoku-server/installer/control.py','start');Ensure-KeepAlive}
                Wsl @('python3','/opt/kienzledoku-server/installer/control.py','verify')
            }finally{
                if(-not $wasRunning){
                    Wsl @('python3','/opt/kienzledoku-server/installer/control.py','stop')
                    Invoke-WslManagement @('--terminate','kienzledoku-server')
                }
            }
        }else{Wsl @('python3','/opt/kienzledoku-server/installer/control.py',$Action.ToLowerInvariant())}
        if($Action -eq 'Start'){
            Ensure-KeepAlive
            $token=Wsl @('python3','/opt/kienzledoku-server/installer/control.py','token') -Capture
            Assert-WindowsEndpoint '127.0.0.1' $token
        }
        if($Action -eq 'Stop'){Invoke-WslManagement @('--terminate','kienzledoku-server')}
    }
    $resultMessage='Vorgang erfolgreich abgeschlossen.'
    if($Action -eq 'Status'){$resultMessage=$statusText}
    if($Action -in @('Install','Download') -and -not $script:ModelOptions.VerifyModelFiles){$resultMessage+=' Modell-Prüfsummenprüfung deaktiviert; nur Dateigrößen kontrolliert.'}
    Write-Json $script:ProgressPath @{Phase='complete';Message=$resultMessage;Percent=100;Action=$Action;Finished=$true;Success=$true}
    exit 0
}catch{
    $message=$_.Exception.Message
    if($script:Token){$message=$message.Replace($script:Token,'[Token ausgelassen]')}
    if($message.StartsWith('NEUSTART:')){
        Log $message
        Write-Json $script:ProgressPath @{Phase='restart';Message=$message;Percent=44;Action=$Action;Finished=$true;Success=$false;RestartRequired=$true}
        exit 3010
    }
    Log ('Fehlerkennung: '+$_.FullyQualifiedErrorId)
    Log ('Installationsphase: '+$script:CurrentPhase)
    if($script:CurrentCommand){Log ('Letzter Prozessaufruf: '+$script:CurrentCommand)}
    Log ('Ausnahmetyp: '+$_.Exception.GetType().FullName)
    if($_.ScriptStackTrace){Log ('Aufrufstelle: '+$_.ScriptStackTrace)}
    Log $message
    Write-Json $script:ProgressPath @{Phase='error';Message=$message;Percent=0;Action=$Action;Finished=$true;Success=$false;RestartRequired=$false}
    exit 1
}finally{
    if($operationHeld){$operationMutex.ReleaseMutex()}
    if($operationMutex){$operationMutex.Dispose()}
}
