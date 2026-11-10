$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path -Parent $PSScriptRoot
$module=Import-Module (Join-Path $root 'windows/Core.psm1') -Force -PassThru -DisableNameChecking
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-space-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary)|Out-Null
$oldWindir=$env:windir
try{
    Case 'Verified Windows archive requires no new allocation; corrupt same-size target needs a copy' {
        $target=Join-Path $temporary 'model.gguf';[IO.File]::WriteAllText($target,'hello')
        $file=[pscustomobject]@{path='model.gguf';bytes=5;sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash}
        Initialize-ModelVerificationCache (Join-Path $temporary 'cache.json')
        $space=Get-ModelTargetSpace $temporary @($file)
        Assert ($space.AdditionalBytes -eq 0 -and $space.ReusedFiles -eq 1) 'Existing verified file counted twice.'
        [IO.File]::WriteAllText($target,'other')
        Assert ((Get-ModelTargetSpace $temporary @($file)).AdditionalBytes -eq 5) 'Corrupt target not reserved.'
        [IO.File]::WriteAllText(($target+'.part'),'he')
        Assert ((Get-ModelTargetSpace $temporary @($file)).AdditionalBytes -eq 3) 'Partial allocation not considered.'
    }
    & $module {
        $script:CFree=10GB;$script:DFree=100GB
        function script:Get-LocalVolumeInfo([string]$Path){
            if($Path.StartsWith('/volume-d/')){return [pscustomobject]@{Root='D:';AvailableBytes=$script:DFree}}
            return [pscustomobject]@{Root='C:';AvailableBytes=$script:CFree}
        }
    }
    Case 'Requirements on one volume are summed; separate volumes retain separate budgets' {
        $plan=@(Get-VolumeSpacePlan @(@{Path='/cache';Bytes=6GB;Reason='archive'},@{Path='/wsl';Bytes=6GB;Reason='wsl'}))
        Assert ($plan.Count -eq 1 -and $plan[0].RequiredBytes -eq 12GB) 'Shared disk requirement undercounted.'
        $failed=$false;try{Assert-VolumeSpace $plan}catch{$failed=$_.Exception.Message.Contains('frei') -and $_.Exception.Message.Contains('fehlen')}
        Assert $failed 'Insufficient shared disk accepted or missing detail.'
        $plan=@(Get-VolumeSpacePlan @(@{Path='/cache';Bytes=6GB;Reason='archive'},@{Path='/volume-d/wsl';Bytes=6GB;Reason='wsl'}))
        Assert ($plan.Count -eq 2) 'Different volumes merged.';Assert-VolumeSpace $plan
    }
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Engine.ps1'),[ref]$tokens,[ref]$errors)
    foreach($name in @('Assert-InstallationSpace','Elevated','Assert-AdminRetryNotCancelled','Wait-AdminRetry','Get-OwnDistroDirectory','Invoke-Native')){
        $definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
        . ([scriptblock]::Create($definition.Extent.Text))
    }
    $directoryDefinition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-OwnDistroDirectory'},$true)
    . ([scriptblock]::Create($directoryDefinition.Extent.Text.Replace('function Get-OwnDistroDirectory','function Get-RegisteredDirectory')))
    function Get-ChildItem {param($LiteralPath,$ErrorAction) [pscustomobject]@{PSPath='synthetic-registry-key'}}
    function Get-ItemProperty {param($LiteralPath) [pscustomobject]@{DistributionName='kienzledoku-server';BasePath=$script:RegistryPath}}
    Case 'Actual registry paths preserve the WSL volume and remove Windows NT path prefixes' {
        foreach($prefix in @('','\\?\','\??\')){
            $script:RegistryPath=$prefix+'D:\WSL\kienzledoku-server'
            Assert ((Get-RegisteredDirectory) -eq 'D:\WSL\kienzledoku-server') 'Registered WSL directory changed.'
        }
    }
    Remove-Item Function:Get-ChildItem,Function:Get-ItemProperty
    $script:Root=$root;$script:forceModels=$false
    $script:Cfg=[pscustomobject]@{InstallDirectory=(Join-Path $temporary 'install');StateDirectory=(Join-Path $temporary 'state');CacheDirectory='network';Models=@('synthetic')}
    $script:DistroPath='existing';$script:Network=$true
    $script:Files=@([pscustomobject]@{path='model/a.gguf';bytes=45GB;sha256=('a'*64)},[pscustomobject]@{path='model/b.gguf';bytes=45GB;sha256=('b'*64)})
    $script:Probe=[pscustomobject]@{AdditionalBytes=0;ReusedBytes=90GB;ReusedFiles=2;RequiredPaths=@();RuntimeReady=$true;FreeBytes=100GB}
    $script:TargetNeed=0;$script:StagePaths=@();$script:Logs=@()
    function Get-RequiredFiles {param($Root,$Models) return $script:Files}
    function Get-OwnDistroDirectory {return $script:DistroPath}
    function Test-NetworkPath {param($Path) return $script:Network}
    function Get-ModelTargetSpace {param($Root,$Files) $script:StagePaths=@($Files | ForEach-Object {$_.path});return [pscustomobject]@{AdditionalBytes=$script:TargetNeed}}
    function Wsl {
        param($Arguments,[switch]$Capture)
        Assert ($Arguments[0] -eq 'python3' -and $Arguments[1] -eq '-c') 'Wrong probe transport.'
        $request=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Arguments[3])) | ConvertFrom-Json
        Assert ($request.Files.Count -eq 2) 'Probe manifest lost files.'
        return "WSL startup notice`nKIENZLEDOKU_STORAGE="+($script:Probe | ConvertTo-Json -Depth 8 -Compress)
    }
    function Progress {param($Phase,$Message,$Percent)}
    function Log {param($Message) $script:Logs+=$Message}
    Case 'Existing 90-GiB installation resumes with 10 GiB free and no second network staging copy' {
        Assert-InstallationSpace
        $saved=Read-Json (Join-Path $script:Cfg.StateDirectory 'disk-space.json')
        Assert ($saved.RuntimeReserveBytes -eq 5GB) 'Fresh-install reserve reused on repair.'
        Assert ($saved.Volumes[0].RequiredBytes -lt 6GB) 'Already installed weights counted again.'
        Assert ($script:StagePaths.Count -eq 0) 'Existing WSL files staged from network again.'
        Assert (90GB+35GB -gt 10GB) 'Fixture no longer reproduces old rejection.'
    }
    Case 'New missing model is included in both WSL growth and its necessary network staging copy' {
        $script:Probe.AdditionalBytes=4GB;$script:Probe.RequiredPaths=@('model/b.gguf');$script:TargetNeed=4GB
        $failed=$false;try{Assert-InstallationSpace}catch{$failed=$_.Exception.Message.Contains('Zu wenig zusätzlicher Speicher')}
        Assert $failed 'Additional model copies were omitted.'
        Assert (($script:StagePaths -join ',') -eq 'model/b.gguf') 'Unneeded models staged.'
        $script:Probe.AdditionalBytes=0;$script:Probe.RequiredPaths=@();$script:TargetNeed=0
    }
    Case 'Actual WSL data volume is checked even when the Windows app lives on another volume' {
        $script:DistroPath='/volume-d/wsl'; & $module {$script:DFree=3GB}
        $failed=$false;try{Assert-InstallationSpace}catch{$failed=$_.Exception.Message.Contains('D:')}
        Assert $failed 'Actual WSL volume was not checked.'
        & $module {$script:DFree=100GB};$script:DistroPath='existing'
    }
    Case 'WSL filesystem exhaustion is checked independently of host free space' {
        $script:Probe.FreeBytes=1GB;$failed=$false
        try{Assert-InstallationSpace}catch{$failed=$_.Exception.Message.Contains('innerhalb der WSL')}
        Assert $failed 'Guest filesystem exhaustion ignored.';$script:Probe.FreeBytes=100GB
    }
    Case 'Fresh install still reserves all weights, bootstrap space and 35 GiB runtime space' {
        $script:DistroPath='';$script:Network=$false;$script:TargetNeed=90GB
        $failed=$false;try{Assert-InstallationSpace}catch{$failed=$_.Exception.Message.Contains('Zu wenig zusätzlicher Speicher')}
        Assert $failed 'Fresh installation was under-reserved.'
        $saved=Read-Json (Join-Path $script:Cfg.StateDirectory 'disk-space.json')
        Assert ($saved.RuntimeReserveBytes -eq 35GB -and $saved.Volumes[0].RequiredBytes -gt 215GB) 'Fresh-install allocations incomplete.'
    }
    Case 'Real multiline probe source and manifest survive native argument transport with Unicode paths' {
        $script:Token='';$script:CurrentPhase='space'
        $source="__name__='capacity_probe'`n"+[IO.File]::ReadAllText((Join-Path $root 'windows/storage_probe.py'))+"`nrequest=json.loads(base64.b64decode(sys.argv[1]).decode())`nprint(json.dumps(probe(request['Files'],Path(sys.argv[2]),Path(sys.argv[3]))))"
        $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((@{Files=$script:Files} | ConvertTo-Json -Depth 24 -Compress)))
        $result=Invoke-Native (Get-Command python3).Source @('-c',$source,$encoded,(Join-Path $temporary 'WSL Prüfung ä'),(Join-Path $temporary 'Linux-Zustand')) -Capture | ConvertFrom-Json
        Assert ($result.AdditionalBytes -eq 90GB -and $result.RequiredPaths.Count -eq 2) 'Native probe transport changed source or manifest.'
    }
    Case 'A reported finished error remains an explicit error with zero or unavailable exit code' {
        $progress=[pscustomobject]@{Phase='error';Message='Zu wenig Platz';Finished=$true;Success=$false}
        foreach($code in @(0,$null)){
            $result=Get-OperationResult $progress $code
            Assert (-not $result.Success -and -not $result.UnexpectedExit) 'Finished error mislabelled as unexpected termination.'
            Assert ($result.Message.StartsWith('Zu wenig Platz')) 'Specific failure replaced.'
        }
        $result=Get-OperationResult $progress $null
        Assert ($null -eq $result.ExitCode -and $result.Message.Contains('nicht verfügbar')) 'Missing exit code invented as zero.'
        $success=[pscustomobject]@{Phase='complete';Message='ok';Finished=$true;Success=$true}
        Assert (-not(Get-OperationResult $success $null).Success) 'Unknown process result accepted as success.'
    }
    Case 'Asynchronous real child exit is synchronized and retained' {
        $child=Start-Process -FilePath (Get-Command python3).Source -ArgumentList '-c "import sys; sys.exit(17)"' -PassThru
        $null=$child.Handle
        while(-not $child.HasExited){Start-Sleep -Milliseconds 10}
        Assert ((Get-FinishedProcessExitCode $child) -eq 17) 'Asynchronous exit code lost.'
        $child.Dispose()
    }
    $env:windir=$temporary;$ConfigPath='synthetic-config.json'
    $script:UacCode=1223;$script:UacCalls=0;$script:RetrySeconds=0
    function Start-Sleep {param([int]$Seconds) $script:RetrySeconds+=$Seconds}
    function Invoke-AdminProcess {
        $script:UacCalls++
        if($script:UacCode -eq 1223 -and $script:UacCalls -gt 1){return 0}
        throw [ComponentModel.Win32Exception]::new($script:UacCode,'synthetic Win32 failure')
    }
    Case 'Unconfirmed UAC for network and WSL is retried after 30 seconds without repeating installation' {
        foreach($operation in @('Network','Features')){
            $script:UacCalls=0;$script:RetrySeconds=0
            $code=Elevated $operation
            Assert ($code -eq 0 -and $script:UacCalls -eq 2 -and $script:RetrySeconds -eq 30) 'UAC retry sequence incorrect.'
            Assert ($script:CurrentCommand.Contains($operation)) 'Stale WSL command retained as failed command.'
        }
    }
    Case 'Other elevation failures retain their error instead of being called a cancellation' {
        $script:UacCode=5;$message=''
        try{Elevated Network}catch{$message=$_.Exception.Message}
        Assert ($message.Contains('synthetic Win32 failure') -and -not $message.Contains('nicht bestätigt')) 'Unrelated Win32 error relabelled.'
    }
    Write-Output "All $script:Passed repair-space/result cases passed (portable PowerShell, Windows/WSL responses simulated)."
}finally{
    $env:windir=$oldWindir
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
