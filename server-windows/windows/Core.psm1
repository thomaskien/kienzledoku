Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
$script:Product = 'kienzledoku Server Installer'
$script:Version = [IO.File]::ReadAllText((Join-Path (Split-Path -Parent $PSScriptRoot) 'VERSION')).Trim()
function Get-InstallerVersion { $script:Version }
function ConvertTo-NativeArguments([string[]]$Arguments) {
    $parts=@(foreach($argument in $Arguments){
        $value=[string]$argument
        # WSL compares management switches as raw command-line tokens. Quoting
        # --version turns it into a Linux command, before any distro exists.
        # Quote only values that need it, retaining standard CRT escaping there.
        if($value.Length -gt 0 -and $value -notmatch '[\s"]'){$value}
        else{'"'+[regex]::Replace([regex]::Replace($value,'(\\*)"','$1$1\"'),'(\\+)$','$1$1')+'"'}
    })
    $parts -join ' '
}
function Get-WslExecutable {
    if($env:OS -ne 'Windows_NT'){return 'wsl.exe'}
    $system='System32'
    if([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess){$system='Sysnative'}
    $path=Join-Path (Join-Path $env:windir $system) 'wsl.exe'
    if(-not [IO.File]::Exists($path)){throw ('Windows-WSL-Programm fehlt: '+$path)}
    return $path
}

function Read-Json([string]$Path) {
    # Windows PowerShell 5.1 emits a JSON array as ONE pipeline object. Assign
    # first, then emit normally so callers receive individual manifest files
    # on both 5.1 and 7, including empty and single-file arrays.
    $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $value
}
function Write-Json([string]$Path, $Value) {
    $parent = Split-Path -Parent $Path
    if ($parent) { [IO.Directory]::CreateDirectory($parent) | Out-Null }
    $text = $Value | ConvertTo-Json -Depth 24
    [IO.File]::WriteAllText($Path + '.new', $text, (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath ($Path + '.new') -Destination $Path -Force
}
function Get-AdminRetryCancelPath($Config) {
    $id=''
    if($Config -is [Collections.IDictionary]){
        if($Config.Contains('AdminRetryId')){$id=[string]$Config['AdminRetryId']}
    }elseif($Config -and $Config.PSObject.Properties['AdminRetryId']){$id=[string]$Config.AdminRetryId}
    if($id -notmatch '^[a-fA-F0-9]{32}$'){return ''}
    return (Join-Path $Config.StateDirectory ('admin-retry-'+$id+'.cancel'))
}
function Get-FinishedProcessExitCode($Process) {
    # WaitForExit synchronizes the .NET process state and redirected streams.
    # A missing code must stay null; binding it to [int] would invent exit 0.
    try{$Process.WaitForExit();$Process.Refresh();return $Process.ExitCode}catch{return $null}
}
function Get-OperationResult($Progress,[AllowNull()][Nullable[int]]$ExitCode,[string]$StderrPath='', [string]$StdoutPath='', [string]$Token='') {
    $finished=$Progress -and $Progress.PSObject.Properties['Finished'] -and $Progress.Finished
    $phase='unknown';$lastMessage='Kein Zwischenstand vorhanden.'
    if($Progress){
        if($Progress.PSObject.Properties['Phase']){$phase=[string]$Progress.Phase}
        if($Progress.PSObject.Properties['Message']){$lastMessage=[string]$Progress.Message}
    }
    $knownExit=$null -ne $ExitCode
    $success=$false;$restart=$false;$unexpected=$true
    if($finished){
        $success=$knownExit -and $ExitCode -eq 0 -and $Progress.PSObject.Properties['Success'] -and $Progress.Success
        $restart=$phase -eq 'restart' -and $ExitCode -eq 3010
        $unexpected=-not($success -or $restart -or $phase -eq 'error')
    }
    $exitText='Prozess-Exitcode nicht verfügbar'
    if($knownExit){$exitText=('Exitcode {0} (0x{1:X8})' -f $ExitCode,$ExitCode)}
    $message=$lastMessage
    if($unexpected){
        if($finished){$message="Abschlussstatus und Prozessende bestätigen keinen Erfolg. $exitText.`r`nLetzter Schritt: $phase — $lastMessage"}
        else{$message="Der Installationsprozess wurde ohne abschließendes Ergebnis beendet. $exitText.`r`nLetzter Schritt: $phase — $lastMessage"}
    }elseif(-not $success -and -not $restart){$message+="`r`n$exitText"}
    if(-not $success){
        foreach($path in @($StderrPath,$StdoutPath)){
            if($path -and [IO.File]::Exists($path)){
                try{
                    $tail=((Get-Content -LiteralPath $path -Tail 35 -Encoding UTF8) -join "`r`n").Trim()
                    if($tail.Length -gt 6000){$tail=$tail.Substring($tail.Length-6000)}
                    if($tail){$message+="`r`n`r`nZusätzliche Prozessausgabe:`r`n$tail"}
                }catch{}
            }
        }
    }
    if($Token){$message=$message.Replace($Token,'[Token ausgelassen]')}
    $resultPhase='error';if($success){$resultPhase='complete'}elseif($restart){$resultPhase='restart'}
    return [pscustomobject]@{Phase=$resultPhase;Message=$message;Finished=$true;Success=[bool]$success;
        RestartRequired=[bool]$restart;ExitCode=$ExitCode;UnexpectedExit=[bool]$unexpected;LastPhase=$phase;
        StderrPath=$StderrPath;StdoutPath=$StdoutPath}
}
function Get-Catalog([string]$Root) { Read-Json (Join-Path $Root 'models.json') }
function Get-RequiredFiles([string]$Root, [string[]]$Models) {
    $catalog = Get-Catalog $Root
    foreach ($key in $Models) {
        $property = $catalog.PSObject.Properties[$key]
        if (-not $property) { throw "Unbekanntes Modell: $key" }
        foreach ($file in $property.Value.files) { $file }
    }
    foreach ($file in @(Read-Json (Join-Path $Root 'audio-files.json'))) { $file }
}
function Get-ContainedPath([string]$Root, [string]$Relative) {
    if ([IO.Path]::IsPathRooted($Relative) -or $Relative -match '(^|[\\/])\.\.([\\/]|$)') {
        throw 'Unzulässiger relativer Modellpfad.'
    }
    $base = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $path = [IO.Path]::GetFullPath((Join-Path $Root $Relative.Replace('/', [IO.Path]::DirectorySeparatorChar)))
    if (-not $path.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { throw 'Modellpfad außerhalb des Zielverzeichnisses.' }
    $path
}
function Test-NetworkPath([string]$Path) {
    if ($Path.StartsWith('\\')) { return $true }
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))
    $drive = New-Object IO.DriveInfo($root)
    return $drive.DriveType -eq [IO.DriveType]::Network
}
function Get-ModelOptions($Config) {
    $verify=$true;$cleanup=$false
    if($Config){
        if($Config -is [Collections.IDictionary]){
            if($Config.Contains('VerifyModelFiles')){$verify=[bool]$Config['VerifyModelFiles']}
            if($Config.Contains('CleanupModelStaging')){$cleanup=[bool]$Config['CleanupModelStaging']}
        }else{
            if($Config.PSObject.Properties['VerifyModelFiles']){$verify=[bool]$Config.VerifyModelFiles}
            if($Config.PSObject.Properties['CleanupModelStaging']){$cleanup=[bool]$Config.CleanupModelStaging}
        }
    }
    [pscustomobject]@{VerifyModelFiles=$verify;CleanupModelStaging=$cleanup}
}
function Set-ModelVerificationMode([bool]$Enabled=$true,[scriptblock]$Report=$null) {
    $script:ModelChecksEnabled=$Enabled;$script:ModelCheckReport=$Report
}
$script:ModelChecksEnabled=$true;$script:ModelCheckReport=$null
function Write-ModelCheckMessage([string]$Message){if($script:ModelCheckReport){& $script:ModelCheckReport $Message}}
function Initialize-ModelVerificationCache([string]$Path, [switch]$Force) {
    $script:VerificationPath=$Path;$script:Verifications=@{};$script:VerificationHits=0;$script:VerificationForced=[bool]$Force
    if(-not $Force -and [IO.File]::Exists($Path)){
        try{
            $cache=Read-Json $Path
            if($cache.Schema -eq 1){foreach($entry in $cache.Files){
                $complete=$true
                foreach($name in @('Path','Bytes','Written','Created','Checksum')){
                    if(-not $entry -or -not $entry.PSObject.Properties[$name]){$complete=$false;break}
                }
                if($complete){$script:Verifications[[string]$entry.Path]=$entry}
            }}
        }catch{Write-Verbose 'Unlesbarer Prüfcache wird neu aufgebaut.'}
    }
    if($Force){Save-ModelVerificationCache}
}
function Get-ModelVerificationStats { [pscustomobject]@{Reused=$script:VerificationHits} }
function Get-ModelFileIdentity([string]$Path) {
    $item=Get-Item -LiteralPath $Path -Force
    $canonical=[IO.Path]::GetFullPath($item.FullName)
    if([IO.Path]::DirectorySeparatorChar -eq '\'){$canonical=$canonical.ToLowerInvariant()}
    return [pscustomobject]@{Path=$canonical;Bytes=[long]$item.Length;
        Written=$item.LastWriteTimeUtc.Ticks.ToString();Created=$item.CreationTimeUtc.Ticks.ToString()}
}
function Get-ModelChecksum($File) {
    if($File.PSObject.Properties['sha256'] -and $File.sha256){return 'sha256:'+([string]$File.sha256).ToLowerInvariant()}
    if($File.PSObject.Properties['git_blob_sha1'] -and $File.git_blob_sha1){return 'git-blob-sha1:'+([string]$File.git_blob_sha1).ToLowerInvariant()}
    throw 'Prüfsumme fehlt.'
}
function Save-ModelVerificationCache {
    if(-not $script:VerificationPath){return}
    try{Write-Json $script:VerificationPath @{Schema=1;Files=@($script:Verifications.Values)}}
    catch{Write-Verbose ('Prüfcache konnte nicht gespeichert werden: '+$_.Exception.Message)}
}
function Set-ModelVerification($Identity,[string]$Checksum) {
    $script:Verifications[$Identity.Path]=[pscustomobject]@{Path=$Identity.Path;Bytes=$Identity.Bytes;
        Written=$Identity.Written;Created=$Identity.Created;Checksum=$Checksum;VerifiedAt=(Get-Date).ToUniversalTime().ToString('o')}
    Save-ModelVerificationCache
}
function Test-SameModelIdentity($Left,$Right) {
    return $Left.Path -ceq $Right.Path -and $Left.Bytes -eq $Right.Bytes -and
        $Left.Written -eq $Right.Written -and $Left.Created -eq $Right.Created
}
function Remove-ModelVerification([string]$Path) {
    $canonical=[IO.Path]::GetFullPath($Path)
    if([IO.Path]::DirectorySeparatorChar -eq '\'){$canonical=$canonical.ToLowerInvariant()}
    if($script:Verifications.ContainsKey($canonical)){$script:Verifications.Remove($canonical);Save-ModelVerificationCache}
}
function Move-VerifiedModelFile([string]$Source,[string]$Destination,$File) {
    if(-not(Test-ModelFile $Source $File -Full)){throw 'Modelldatei vor Umbenennen ungültig: '+$Source}
    $before=Get-ModelFileIdentity $Source
    Move-Item -LiteralPath $Source -Destination $Destination -Force
    $after=Get-ModelFileIdentity $Destination
    if(-not $script:ModelChecksEnabled){Remove-ModelVerification $Source;Remove-ModelVerification $Destination;return}
    # Only a rename of the already checked file can carry its proof forward.
    if($before.Bytes -eq $after.Bytes -and $before.Written -eq $after.Written -and $before.Created -eq $after.Created){
        $script:Verifications.Remove($before.Path);Set-ModelVerification $after (Get-ModelChecksum $File)
    }elseif(-not(Test-ModelFile $Destination $File -Full)){throw 'Modelldatei nach Umbenennen ungültig: '+$Destination}
}
$script:VerificationPath='';$script:Verifications=@{};$script:VerificationHits=0;$script:VerificationForced=$false
function Test-ModelFile([string]$Path, $File, [switch]$Full) {
    if (-not [IO.File]::Exists($Path)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne [long]$File.bytes) { return $false }
    if (-not $Full -or -not $script:ModelChecksEnabled) { return $true }
    $identity=Get-ModelFileIdentity $Path;$checksum=Get-ModelChecksum $File
    $entry=$script:Verifications[$identity.Path]
    if($entry -and $entry.Checksum -ceq $checksum -and (Test-SameModelIdentity $identity $entry)){
        $script:VerificationHits++;Write-ModelCheckMessage ('Prüfnachweis wiederverwendet: '+$Path);return $true
    }
    if($entry){$script:Verifications.Remove($identity.Path);Save-ModelVerificationCache}
    $reason='kein passender Prüfnachweis (neue/geänderte Datei oder Quelle)'
    if($script:VerificationForced){$reason='vollständige Neuprüfung angefordert'}
    Write-ModelCheckMessage ('Prüfsumme: '+$Path+' — '+$reason)
    if ($File.PSObject.Properties['sha256'] -and $File.sha256) {
        $valid=((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ieq $File.sha256)
        if($valid -and (Test-SameModelIdentity $identity (Get-ModelFileIdentity $Path))){Set-ModelVerification $identity $checksum;return $true}
        return $false
    }
    $hash = [Security.Cryptography.SHA1]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try {
        $prefix = [Text.Encoding]::UTF8.GetBytes("blob $($stream.Length)`0")
        $null = $hash.TransformBlock($prefix, 0, $prefix.Length, $prefix, 0)
        $buffer = New-Object byte[] (1024 * 1024)
        while (($n = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) { $null = $hash.TransformBlock($buffer, 0, $n, $buffer, 0) }
        $null = $hash.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        $valid=(([BitConverter]::ToString($hash.Hash).Replace('-', '')) -ieq $File.git_blob_sha1)
    } finally { $stream.Dispose(); $hash.Dispose() }
    if($valid -and (Test-SameModelIdentity $identity (Get-ModelFileIdentity $Path))){Set-ModelVerification $identity $checksum;return $true}
    return $false
}
function Find-ModelFile([string[]]$Roots, $File, [switch]$Full) {
    foreach ($root in $Roots) {
        if (-not $root) { continue }
        $candidates = @((Get-ContainedPath $root $File.path), (Join-Path $root $File.filename), (Join-Path $root ([IO.Path]::GetFileName($File.filename))))
        foreach ($candidate in ($candidates | Select-Object -Unique)) {
            if (Test-ModelFile $candidate $File -Full:$Full) { return $candidate }
        }
    }
    return $null
}
function Get-ModelTargetSpace([string]$Root,[object[]]$Files,[switch]$Missing) {
    [long]$additional=0;[long]$reused=0;$count=0
    foreach($file in $Files){
        $target=Get-ContainedPath $Root $file.path
        if(-not $Missing -and (Test-ModelFile $target $file -Full)){$reused += [long]$file.bytes;$count++;continue}
        [long]$partial=0
        if([IO.File]::Exists($target+'.part')){$partial=(Get-Item -LiteralPath ($target+'.part')).Length}
        if($partial -lt 0 -or $partial -gt [long]$file.bytes){$partial=0}
        $additional += [long]$file.bytes-$partial
    }
    return [pscustomobject]@{AdditionalBytes=$additional;ReusedBytes=$reused;ReusedFiles=$count}
}
function Get-LocalVolumeInfo([string]$Path) {
    $root=[IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))
    $drive=New-Object IO.DriveInfo($root)
    return [pscustomobject]@{Root=$root;AvailableBytes=[long]$drive.AvailableFreeSpace}
}
function Get-VolumeSpacePlan([object[]]$Requirements) {
    $volumes=@{}
    foreach($item in $Requirements){
        if([long]$item.Bytes -le 0){continue}
        $volume=Get-LocalVolumeInfo $item.Path;$key=$volume.Root.ToLowerInvariant()
        if(-not $volumes.ContainsKey($key)){
            $volumes[$key]=[pscustomobject]@{Volume=$volume.Root;AvailableBytes=[long]$volume.AvailableBytes;RequiredBytes=[long]0;Components=@()}
        }
        $volumes[$key].RequiredBytes += [long]$item.Bytes
        $volumes[$key].Components += ('{0}: {1:N2} GiB' -f $item.Reason,([long]$item.Bytes/1GB))
    }
    return @($volumes.Values | Sort-Object Volume)
}
function Assert-VolumeSpace($Plan) {
    foreach($volume in $Plan){
        if($volume.AvailableBytes -lt $volume.RequiredBytes){
            throw ('Zu wenig zusätzlicher Speicher auf {0}: benötigt {1:N2} GiB, frei {2:N2} GiB, fehlen {3:N2} GiB. Bereits geprüfte Modelle sind abgezogen. Bedarf: {4}.' -f $volume.Volume,($volume.RequiredBytes/1GB),($volume.AvailableBytes/1GB),(($volume.RequiredBytes-$volume.AvailableBytes)/1GB),($volume.Components -join '; '))
        }
    }
}
function Get-Inventory([string]$Root, [string[]]$Sources) {
    $catalog = Get-Catalog $Root
    foreach ($property in $catalog.PSObject.Properties) {
        $found = 0; $partial = $false
        foreach ($file in $property.Value.files) {
            if (Find-ModelFile $Sources $file) { $found++ }
            foreach ($source in $Sources) {
                if ($source -and [IO.File]::Exists((Get-ContainedPath $source ($file.path + '.part')))) { $partial = $true }
            }
        }
        $state = 'fehlt'
        if ($found -eq @($property.Value.files).Count) { $state = 'gefunden (Prüfsumme vor Übernahme)' }
        elseif ($found -or $partial) { $state = 'unvollständig' }
        [pscustomobject]@{ Id=$property.Name; Label=$property.Value.label; State=$state }
    }
    foreach ($group in @('whisper','pyannote')) {
        $files = @(Read-Json (Join-Path $Root 'audio-files.json') | Where-Object { $_.path.StartsWith($group + '/') })
        $found = @($files | Where-Object { Find-ModelFile $Sources $_ }).Count
        $state = 'fehlt'; if ($found -eq $files.Count) { $state = 'gefunden (Prüfsumme vor Übernahme)' } elseif ($found) { $state = 'unvollständig' }
        [pscustomobject]@{ Id=$group; Label=$group; State=$state }
    }
}
function Get-Hardware {
    $os = Get-CimInstance Win32_OperatingSystem
    $ram = [long](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    $gpu = @()
    $smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $smi) {
        $candidate = Join-Path $env:windir 'System32\nvidia-smi.exe'
        if (Test-Path -LiteralPath $candidate) { $smi = Get-Item -LiteralPath $candidate }
    }
    if ($smi) {
        if ($smi.PSObject.Properties['Source']) { $smiPath = $smi.Source }
        else { $smiPath = $smi.FullName }
        $lines = @(& $smiPath '--query-gpu=index,name,memory.total,driver_version' '--format=csv,noheader,nounits' 2>$null)
        if ($LASTEXITCODE -eq 0) {
            foreach ($line in $lines) {
                $p = $line.Split(',') | ForEach-Object { $_.Trim() }
                if ($p.Count -eq 4) { $gpu += [pscustomobject]@{ Index=[int]$p[0]; Name=$p[1]; VramMiB=[int]$p[2]; Driver=$p[3] } }
            }
        }
    }
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
        $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' -and $_.InterfaceAlias -notlike 'vEthernet*'
    } | Select-Object IPAddress, InterfaceAlias)
    [pscustomobject]@{ Build=[int]$os.BuildNumber; Architecture=$env:PROCESSOR_ARCHITECTURE; RamBytes=$ram; Gpus=$gpu; Addresses=$addresses }
}
function Get-ParallelModelChoices($Catalog,[string[]]$Models,[int]$VramMiB) {
    foreach($id in $Models){
        $property=$Catalog.PSObject.Properties[$id]
        if(-not $property){throw "Unbekanntes Modell: $id"}
        $model=$property.Value
        if($null -ne $model.parallel_vram_mib -and $VramMiB -ge $model.parallel_vram_mib -and $VramMiB -ge $model.serial_vram_mib){$id}
    }
}
function Get-ProfilePlan($Catalog, [string[]]$Models, [string]$Default, [string]$Mode, [int]$VramMiB, [int]$RamGiB, [string]$AudioCache='ram', [string]$ParallelModel='') {
    if ($RamGiB -notin @(16,24,28,32)) { throw 'WSL-Speicher muss 16, 24, 28 oder 32 GiB betragen.' }
    if ($Mode -notin @('auto','serial','parallel','selected')) { throw 'Ungültige Betriebsart.' }
    if ($Default -notin $Models) { throw 'Standardmodell muss ausgewählt sein.' }
    if ($AudioCache -notin @('ram','disk')) { throw 'Ungültiger Audiocache.' }
    if($Mode -eq 'selected' -and $ParallelModel -and $ParallelModel -notin $Models){throw 'Parallelmodell muss zur Installation ausgewählt sein.'}
    $qualities=@{}
    $result = @{}
    foreach ($id in $Models) {
        $p = $Catalog.PSObject.Properties[$id]
        if (-not $p) { throw "Unbekanntes Modell: $id" }
        $m = $p.Value
        if($qualities.ContainsKey([string]$m.quality)){throw 'Modell-IDs im Katalog müssen eindeutig sein.'}
        $qualities[[string]$m.quality]=$true
        if ($VramMiB -lt $m.serial_vram_mib) { throw "Zu wenig VRAM für $($m.label). Benötigt: mindestens $([math]::Ceiling($m.serial_vram_mib / 1024)) GiB." }
        $parallel = $null -ne $m.parallel_vram_mib -and $VramMiB -ge $m.parallel_vram_mib
        if ($Mode -eq 'parallel' -and -not $parallel) { throw "Für $($m.label) ist auf dieser GPU kein Parallelprofil freigegeben." }
        $chosen = 'serial'; if ($Mode -eq 'parallel' -or ($Mode -eq 'auto' -and $parallel)) { $chosen = 'parallel' }
        if($Mode -eq 'selected' -and $id -eq $ParallelModel){
            if(-not $parallel){throw "Für $($m.label) ist auf dieser GPU kein Parallelprofil freigegeben."}
            $chosen='parallel'
        }
        $audioRam=0;if($m.PSObject.Properties['ram_audio_min_wsl_gib']){$audioRam=[int]$m.ram_audio_min_wsl_gib}
        if ($RamGiB -lt $audioRam -and $AudioCache -ne 'disk') {
            throw "$($m.label) unter $audioRam GiB WSL benötigt den zusätzlichen Whisper-SSD-Sparmodus."
        }
        $result[$id] = @{ Mode=$chosen; AudioCache=$AudioCache }
    }
    $result
}
function Set-WslMemoryText([string]$Text, [int]$GiB) {
    if ($GiB -notin @(16,24,28,32)) { throw 'Ungültiges WSL-Speicherlimit.' }
    $lines = New-Object 'Collections.Generic.List[string]'
    $inside = $false; $seen = $false; $written = $false
    foreach ($line in ($Text -split '\r?\n')) {
        if ($line -match '^\s*\[([^]]+)\]') {
            if ($inside -and -not $written) { $lines.Add("memory=$($GiB)GB"); $written = $true }
            $inside = $Matches[1] -ieq 'wsl2'; if ($inside) { $seen = $true }
        }
        if ($inside -and $line -match '^\s*memory\s*=') {
            if (-not $written) { $lines.Add("memory=$($GiB)GB"); $written = $true }
        } else { $lines.Add($line) }
    }
    if (-not $seen) { $lines.Add('[wsl2]') }
    if (-not $written) { $lines.Add("memory=$($GiB)GB") }
    ($lines -join "`r`n").Trim() + "`r`n"
}
function Set-PrivateFile([string]$Path) {
    if ($env:OS -ne 'Windows_NT') { return }
    $path = [IO.Path]::GetFullPath($Path)
    $acl = New-Object Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $allowed = @([Security.Principal.WindowsIdentity]::GetCurrent().User, (New-Object Security.Principal.SecurityIdentifier('S-1-5-18')), (New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    foreach ($sid in $allowed) {
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')))
    }
    # Persist only the modified DACL. Set-Acl copies the entire descriptor first,
    # including its audit section, which can demand SeSecurityPrivilege even
    # for a user's own file. Do not change the owner, group or audit policy.
    if ($PSVersionTable.PSEdition -eq 'Desktop') {
        [IO.File]::SetAccessControl($path, $acl)
        $saved = [IO.File]::GetAccessControl($path, [Security.AccessControl.AccessControlSections]::Access)
    } else {
        $file = New-Object IO.FileInfo($path)
        [IO.FileSystemAclExtensions]::SetAccessControl($file, $acl)
        $saved = [IO.FileSystemAclExtensions]::GetAccessControl($file, [Security.AccessControl.AccessControlSections]::Access)
    }
    # Read back access rules only: neither verification nor writes need audit
    # privileges. Refuse a file whose intended privacy could not be established.
    if (-not $saved.AreAccessRulesProtected) { throw 'Dateischutz fehlgeschlagen: Vererbung ist weiterhin aktiv.' }
    $rules = @($saved.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    $expected = @($allowed | ForEach-Object { $_.Value } | Select-Object -Unique)
    if ($rules.Count -ne $expected.Count) { throw 'Dateischutz fehlgeschlagen: unerwartete Zugriffsrechte.' }
    foreach ($rule in $rules) {
        if ($rule.IdentityReference.Value -notin $expected -or $rule.IsInherited -or
            $rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl) {
            throw 'Dateischutz fehlgeschlagen: unerwartete Zugriffsrechte.'
        }
    }
}
function Get-Download([string]$Url, [string]$Destination, [string]$Token='', [long]$ExpectedBytes=0) {
    Add-Type -AssemblyName System.Net.Http
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Destination)) | Out-Null
    $part = $Destination + '.part'
    $handler = New-Object Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $client = New-Object Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromHours(24)
    try {
        for ($attempt=0; $attempt -lt 4; $attempt++) {
            $offset = 0; if (Test-Path -LiteralPath $part) { $offset = (Get-Item -LiteralPath $part).Length }
            if ($ExpectedBytes -and $offset -eq $ExpectedBytes) { Move-Item -LiteralPath $part -Destination $Destination -Force; return }
            if ($ExpectedBytes -and $offset -gt $ExpectedBytes) { Remove-Item -LiteralPath $part -Force; $offset=0 }
            $uri = [Uri]$Url; $response=$null
            try {
                for ($redirect=0; $redirect -lt 12; $redirect++) {
                    if ($uri.Scheme -ne 'https') { throw 'Downloads benötigen HTTPS.' }
                    $request = New-Object Net.Http.HttpRequestMessage([Net.Http.HttpMethod]::Get, $uri)
                    if ($offset) { $request.Headers.Range = New-Object Net.Http.Headers.RangeHeaderValue($offset, $null) }
                    if ($Token -and $uri.Host -eq 'huggingface.co') { $request.Headers.Authorization = New-Object Net.Http.Headers.AuthenticationHeaderValue('Bearer',$Token) }
                    $response = $client.SendAsync($request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
                    $request.Dispose()
                    if ([int]$response.StatusCode -notin @(301,302,303,307,308)) { break }
                    $next = $response.Headers.Location; if (-not $next.IsAbsoluteUri) { $next=New-Object Uri($uri,$next) }
                    $response.Dispose(); $response=$null; $uri=$next
                }
                if (-not $response) { throw 'Zu viele Weiterleitungen.' }
                if ([int]$response.StatusCode -in @(401,403)) { throw 'Hugging-Face-Zugriff verweigert. Token und akzeptierte pyannote-Modellbedingungen prüfen.' }
                $null = $response.EnsureSuccessStatusCode()
                $append = $offset -gt 0 -and [int]$response.StatusCode -eq 206
                if ($append -and $response.Content.Headers.ContentRange.From -ne $offset) { throw 'Ungültige Fortsetzungsposition.' }
                $mode = [IO.FileMode]::Create; if ($append) { $mode=[IO.FileMode]::Append }
                $output = [IO.File]::Open($part,$mode,[IO.FileAccess]::Write,[IO.FileShare]::Read)
                $input = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                try { $input.CopyTo($output, 4*1024*1024) } finally { $input.Dispose(); $output.Dispose() }
                if ($ExpectedBytes -and (Get-Item -LiteralPath $part).Length -ne $ExpectedBytes) { throw 'Download unvollständig.' }
                Move-Item -LiteralPath $part -Destination $Destination -Force
                return
            } catch {
                if ($attempt -eq 3 -or $_.Exception.Message -like '*Zugriff verweigert*') { throw }
                Start-Sleep -Seconds (2 + 2*$attempt)
            } finally { if ($response) { $response.Dispose() } }
        }
    } finally { $client.Dispose(); $handler.Dispose() }
}
function Test-HfAccess([string]$Token, [string]$Root) {
    if (-not $Token -or $Token -notmatch '^hf_[A-Za-z0-9]+$') { throw 'Ein gültiger Hugging-Face-Read-Token wird benötigt.' }
    $file = @(Read-Json (Join-Path $Root 'audio-files.json') | Where-Object { $_.path -eq 'pyannote/config.yaml' })[0]
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-access-' + [Guid]::NewGuid().ToString('N'))
    try {
        Get-Download $file.url $temporary $Token $file.bytes
        if (-not (Test-ModelFile $temporary $file -Full)) { throw 'pyannote-Konfigurationsprüfung fehlgeschlagen.' }
    } finally { Remove-Item -LiteralPath $temporary,($temporary+'.part') -Force -ErrorAction SilentlyContinue }
}
Export-ModuleMember -Function *
