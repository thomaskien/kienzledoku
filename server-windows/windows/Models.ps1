# Model source selection and owned staging. Dot-sourced by Engine.ps1.
function Get-StageDirectory { Join-Path $script:Cfg.InstallDirectory 'models' }
function Get-ModelSourceGroups {
    $local=@();$remote=@()
    foreach($path in @($script:Cfg.CacheDirectory)+@($script:Cfg.Sources)){
        if(-not $path){continue}
        if(Test-NetworkPath $path){$remote+=$path}else{$local+=$path}
    }
    [pscustomobject]@{Local=@($local | Select-Object -Unique);Remote=@($remote | Select-Object -Unique)}
}
function Read-WslModelState([object[]]$Files,[switch]$Validate) {
    [long]$total=($Files | Measure-Object -Property bytes -Sum).Sum
    $report=[pscustomobject]@{AdditionalBytes=$total;ReusedBytes=0;ReusedFiles=0;RuntimeReady=$false;RequiredPaths=@($Files | ForEach-Object {$_.path});FreeBytes=$null;Validated=$false}
    if(-not(Get-OwnDistroDirectory)){return $report}
    $source=[IO.File]::ReadAllText((Join-Path $script:Root 'windows/storage_probe.py'))
    $request=@{Files=@($Files | Select-Object path,bytes,sha256,git_blob_sha1);Force=[bool]$forceModels;VerifyModelFiles=$script:ModelOptions.VerifyModelFiles;Validate=[bool]$Validate}
    $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($request | ConvertTo-Json -Depth 24 -Compress)))
    $raw=Wsl @('python3','-c',$source,$encoded) -Capture
    $line=@($raw -split '\r?\n' | Where-Object {$_.StartsWith('KIENZLEDOKU_STORAGE=')}) | Select-Object -Last 1
    if(-not $line){throw 'WSL-Modellbestand konnte nicht ermittelt werden. installation.log prüfen.'}
    $line.Substring('KIENZLEDOKU_STORAGE='.Length) | ConvertFrom-Json
}
function Initialize-ModelPlan {
    Progress 'models' 'Zuerst vorhandene WSL-Modelle und lokale Kopien prüfen.' 2
    if(-not $script:ModelOptions.VerifyModelFiles){Log 'Modell-Prüfsummenprüfung deaktiviert: nur Vorhandensein und Dateigröße kontrollieren.'}
    $files=@(Get-RequiredFiles $script:Root $script:Cfg.Models)
    $script:StorageProbe=Read-WslModelState $files -Validate
    $script:ProtectedPathCache=@{}
    $script:ModelPlan=@{};$groups=Get-ModelSourceGroups;$stage=Get-StageDirectory
    $localRoots=@($stage)+$groups.Local
    foreach($file in $files){
        if($file.path -notin $script:StorageProbe.RequiredPaths){
            if($script:ModelOptions.CleanupModelStaging){
                $older=Get-ContainedPath $stage $file.path
                if(Test-ModelFile $older $file){Register-LegacyStage $older $file}
            }
            $script:ModelPlan[$file.path]=[pscustomobject]@{Kind='wsl';Source='';Target='';Owned=$false};continue
        }
        $source=Find-ModelFile $localRoots $file -Full
        if($source){
            $script:ModelPlan[$file.path]=[pscustomobject]@{Kind='local';Source=$source;Target='';Owned=$false}
            Log ('Lokale Modelldatei wiederverwenden: '+$file.path)
            Register-LegacyStage $source $file
        }else{
            $owned=Test-NetworkPath $script:Cfg.CacheDirectory
            $targetRoot=$script:Cfg.CacheDirectory;if($owned){$targetRoot=$stage}
            $script:ModelPlan[$file.path]=[pscustomobject]@{Kind='pending';Source='';Target=(Get-ContainedPath $targetRoot $file.path);Owned=$owned}
        }
    }
    Log ('WSL-Bestand wiederverwendet: '+$script:StorageProbe.ReusedFiles+' Modelldateien. Prüfsummenprüfung: '+$script:ModelOptions.VerifyModelFiles)
}
function Copy-ModelFile([string]$Source,[string]$Destination,$File) {
    Progress 'models' ('Kopiere Modell: '+$File.path) 24
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Destination)) | Out-Null
    Remove-ModelVerification ($Destination+'.part')
    Copy-Item -LiteralPath $Source -Destination ($Destination+'.part') -Force
    Move-VerifiedModelFile ($Destination+'.part') $Destination $File
}
function Ensure-InstallModels {
    $groups=Get-ModelSourceGroups;$hfChecked=$false
    foreach($file in @(Get-RequiredFiles $script:Root $script:Cfg.Models)){
        $item=$script:ModelPlan[$file.path]
        if($item.Kind -ne 'pending'){continue}
        Progress 'models' ('Benötigte Quelle im Modellarchiv suchen: '+$file.path) 15
        $source=Find-ModelFile $groups.Remote $file -Full
        if($source){Copy-ModelFile $source $item.Target $file}else{
            if($file.PSObject.Properties['gated'] -and $file.gated -and -not $hfChecked){
                Test-HfAccess $script:Token $script:Root;$hfChecked=$true
            }
            Progress 'models' ('Download fehlender Modelldatei: '+$file.path) 25
            Get-Download $file.url $item.Target $script:Token $file.bytes
            if(-not(Test-ModelFile $item.Target $file -Full)){throw 'Download stimmt nicht: '+$file.path}
        }
        $item.Source=$item.Target;$item.Kind='local'
        if($item.Owned){Register-ModelStage $item.Source $file}
    }
}
function Set-LinuxModelSources {
    $paths=@{}
    foreach($entry in $script:ModelPlan.GetEnumerator()){
        if($entry.Value.Kind -eq 'local'){$paths[$entry.Key]=$entry.Value.Source}
    }
    $mapped=@{}
    if($paths.Count){
        $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($paths | ConvertTo-Json -Compress)))
        $code='import base64,json,subprocess,sys; paths=json.loads(base64.b64decode(sys.argv[1]).decode("utf-8-sig")); print("KIENZLEDOKU_SOURCES="+json.dumps({k:subprocess.check_output(["wslpath","-u",v],text=True).strip() for k,v in paths.items()}))'
        $raw=Wsl @('python3','-c',$code,$encoded) -Capture
        $line=@($raw -split '\r?\n' | Where-Object {$_.StartsWith('KIENZLEDOKU_SOURCES=')}) | Select-Object -Last 1
        if(-not $line){throw 'Lokale Modellquellen konnten nicht nach WSL übersetzt werden.'}
        $mapped=$line.Substring('KIENZLEDOKU_SOURCES='.Length) | ConvertFrom-Json
    }
    $script:Cfg | Add-Member -NotePropertyName LinuxModelSources -NotePropertyValue $mapped -Force
    $script:Cfg | Add-Member -NotePropertyName LinuxModelSource -NotePropertyValue '/opt/kienzledoku-server/models' -Force
    $script:Cfg | Add-Member -NotePropertyName ModelPreflightVerified -NotePropertyValue ([bool]$script:StorageProbe.Validated) -Force
    $script:Cfg | Add-Member -NotePropertyName ModelImportId -NotePropertyValue ([guid]::NewGuid().ToString('N')) -Force
}
function Test-ModelPathOverlap([string]$First,[string]$Second) {
    $a=[IO.Path]::GetFullPath($First).TrimEnd('\','/');$b=[IO.Path]::GetFullPath($Second).TrimEnd('\','/')
    return $a.Equals($b,[StringComparison]::OrdinalIgnoreCase) -or
        $a.StartsWith($b+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
        $b.StartsWith($a+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)
}
function Test-ModelPathWithoutLinks([string]$Path) {
    $current=[IO.Path]::GetFullPath($Path)
    while($current){
        if(Test-Path -LiteralPath $current){
            if((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){return $false}
        }
        $parent=[IO.Path]::GetDirectoryName($current)
        if($parent -eq $current){break};$current=$parent
    }
    return $true
}
function Resolve-ModelProtectedPath([string]$Path) {
    $full=[IO.Path]::GetFullPath($Path)
    if($env:OS -ne 'Windows_NT'){return $full}
    if($full -match '^([A-Za-z]:)\\' -and (Test-NetworkPath $full)){
        $drive=Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='"+$Matches[1]+"'") -ErrorAction SilentlyContinue
        if(-not $drive -or -not $drive.ProviderName){return $null}
        $full=$drive.ProviderName.TrimEnd('\')+$full.Substring(2)
    }
    if($full -notmatch '^\\\\([^\\]+)\\([^\\]+)(.*)$'){
        # Different drive letters can still refer to one volume (SUBST).
        $archiveRoot=[IO.Path]::GetPathRoot($full).TrimEnd('\')
        $stageRoot=[IO.Path]::GetPathRoot([IO.Path]::GetFullPath((Get-StageDirectory))).TrimEnd('\')
        if($archiveRoot -ne $stageRoot){
            try{
                $a=Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='"+$archiveRoot+"'") -ErrorAction Stop
                $b=Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='"+$stageRoot+"'") -ErrorAction Stop
                if(-not $a.VolumeSerialNumber -or -not $b.VolumeSerialNumber -or $a.VolumeSerialNumber -eq $b.VolumeSerialNumber){return $null}
            }catch{return $null}
        }
        return $full
    }
    $server=$Matches[1];$share=$Matches[2];$tail=$Matches[3].TrimStart('\')
    $local=$server -in @('localhost','127.0.0.1',[Environment]::MachineName,[Net.Dns]::GetHostName())
    if(-not $local){
        # A network alias can point back to this machine and its staging
        # folder. If this cannot be resolved, preserve the copies.
        try{
            $pending=[Net.Dns]::BeginGetHostAddresses($server,$null,$null)
            if(-not $pending.AsyncWaitHandle.WaitOne(1000)){return $null}
            $addresses=[Net.Dns]::EndGetHostAddresses($pending)
        }catch{return $null}
        $own=@([Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | ForEach-Object {$_.GetIPProperties().UnicastAddresses} | ForEach-Object {$_.Address.ToString()})
        $local=@($addresses | Where-Object {$_.ToString() -in $own -or [Net.IPAddress]::IsLoopback($_)}).Count -gt 0
    }
    if(-not $local){return $full}
    try{$mapping=Get-SmbShare -Name $share -ErrorAction Stop}catch{return $null}
    if(-not $mapping.Path){return $null}
    if($tail){return Resolve-ModelProtectedPath ([IO.Path]::GetFullPath((Join-Path $mapping.Path $tail)))}
    return Resolve-ModelProtectedPath ([IO.Path]::GetFullPath($mapping.Path))
}
function Test-StageCleanupLocation {
    $stage=Get-StageDirectory
    if(-not(Test-ModelPathWithoutLinks $stage)){return $false}
    foreach($protected in @($script:Cfg.CacheDirectory)+@($script:Cfg.Sources)){
        if(-not $protected){continue}
        if(-not(Get-Variable -Name ProtectedPathCache -Scope Script -ErrorAction SilentlyContinue)){$script:ProtectedPathCache=@{}}
        $key=[IO.Path]::GetFullPath($protected).ToLowerInvariant()
        if(-not $script:ProtectedPathCache.ContainsKey($key)){$script:ProtectedPathCache[$key]=@{Value=(Resolve-ModelProtectedPath $protected)}}
        $resolved=$script:ProtectedPathCache[$key].Value
        if(-not $resolved -or (Test-ModelPathOverlap $stage $resolved)){return $false}
        if(-not(Test-NetworkPath $resolved) -and -not(Test-ModelPathWithoutLinks $resolved)){return $false}
    }
    return $true
}
function Get-ModelStageRecords {
    $path=Join-Path $script:Cfg.StateDirectory 'staging-files.json'
    if(Test-Path -LiteralPath $path){
        try{
            $saved=Read-Json $path
            if($saved.Schema -eq 1 -and $saved.Root -eq [IO.Path]::GetFullPath((Get-StageDirectory))){return @($saved.Files)}
        }catch{}
    }
    return @()
}
function Register-ModelStage([string]$Path,$File) {
    $expected=Get-ContainedPath (Get-StageDirectory) $File.path
    if([IO.Path]::GetFullPath($Path) -ne $expected){return}
    $records=@(Get-ModelStageRecords | Where-Object {$_.RelativePath -ne $File.path})
    $records+=@{RelativePath=$File.path;Bytes=[long]$File.bytes;Identity=(Get-ModelFileIdentity $Path)}
    $manifest=Join-Path $script:Cfg.StateDirectory 'staging-files.json'
    Write-Json $manifest @{Schema=1;Root=[IO.Path]::GetFullPath((Get-StageDirectory));Files=$records}
    Set-PrivateFile $manifest
}
function Register-LegacyStage([string]$Path,$File) {
    # Only adopt the previous installer's known network-staging layout, never
    # an arbitrary archive file supplied as a source by this run.
    $saved=Join-Path $script:Cfg.InstallDirectory 'config.json'
    if(-not(Test-Path -LiteralPath $saved) -or -not(Test-StageCleanupLocation)){return}
    try{
        $previous=Read-Json $saved
        if($previous.InstallDirectory -eq $script:Cfg.InstallDirectory -and
           (Test-NetworkPath $previous.CacheDirectory) -and
           [IO.Path]::GetFullPath($Path) -eq (Get-ContainedPath (Get-StageDirectory) $File.path)){
            Register-ModelStage $Path $File
        }
    }catch{Log ('Ältere Zwischenkopie ohne eindeutige Zuordnung behalten: '+$File.path)}
}
function Complete-ModelStaging {
    if(-not $script:ModelOptions.CleanupModelStaging){Log 'Lokale Zwischenkopien für spätere Installation behalten.';return}
    $script:ProtectedPathCache=@{}
    if(-not(Test-StageCleanupLocation)){Log 'Bereinigung ausgelassen: Zwischenablage überschneidet sich mit einem Modellarchiv oder enthält Verknüpfungen.';return}
    $raw=Wsl @('cat','/var/lib/kienzledoku-server/model-import.json') -Capture
    $receipt=$raw | ConvertFrom-Json
    if($receipt.run_id -ne $script:Cfg.ModelImportId -or [bool]$receipt.verify_model_files -ne $script:ModelOptions.VerifyModelFiles){throw 'Bereinigungsnachweis gehört nicht zu diesem Installationslauf.'}
    $retained=@();$removed=0
    foreach($record in @(Get-ModelStageRecords)){
        $confirmed=@($receipt.files | Where-Object {$_.path -eq $record.RelativePath -and [long]$_.bytes -eq [long]$record.Bytes})
        $path=Get-ContainedPath (Get-StageDirectory) $record.RelativePath
        if(-not(Test-Path -LiteralPath $path)){continue}
        if($confirmed.Count -eq 1 -and (Test-ModelPathWithoutLinks $path) -and
           (Test-SameModelIdentity $record.Identity (Get-ModelFileIdentity $path))){
            try{
                Remove-Item -LiteralPath $path -Force
                Remove-ModelVerification $path;$removed++;Log ('Zwischenkopie nach erfolgreicher Übernahme entfernt: '+$record.RelativePath)
            }catch{$retained+=$record;Log ('Zwischenkopie konnte nicht entfernt werden und bleibt erhalten: '+$record.RelativePath)}
        }else{$retained+=$record;Log ('Zwischenkopie wegen fehlendem Nachweis oder Änderung behalten: '+$record.RelativePath)}
    }
    Write-Json (Join-Path $script:Cfg.StateDirectory 'staging-files.json') @{Schema=1;Root=[IO.Path]::GetFullPath((Get-StageDirectory));Files=$retained}
    Log ('Bereinigung abgeschlossen: '+$removed+' zusätzliche Modelldateien entfernt.')
}
