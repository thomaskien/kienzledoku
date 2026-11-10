$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path -Parent $PSScriptRoot
$module=Import-Module (Join-Path $root 'windows/Core.psm1') -Force -PassThru -DisableNameChecking
. (Join-Path $root 'windows/Models.ps1')
$script:Root=$root;$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-options-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary)|Out-Null
& $module {
    $script:HashCalls=0;$script:ForbidHash=$false
    function script:Get-FileHash {
        param($LiteralPath,$Algorithm)
        $script:HashCalls++
        if($script:ForbidHash){throw 'Unexpected model hash'}
        Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $LiteralPath -Algorithm $Algorithm
    }
}
function HashCalls {& $module {$script:HashCalls}}
function Reset {
    $script:Cfg=[pscustomobject]@{InstallDirectory=(Join-Path $temporary ([guid]::NewGuid().ToString('N')));StateDirectory=(Join-Path $temporary 'state');CacheDirectory=(Join-Path $temporary 'network');Sources=@();Models=@('synthetic');ModelImportId='current-run'}
    $script:ModelOptions=Get-ModelOptions $null;$script:forceModels=$false;$script:Token=''
    $script:Files=@([pscustomobject]@{path='a/model.gguf';filename='a.gguf';bytes=5;sha256='2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824';gated=$false;url='https://invalid.example/synthetic'})
    $script:Probe=[pscustomobject]@{AdditionalBytes=5;ReusedBytes=0;ReusedFiles=0;RuntimeReady=$true;RequiredPaths=@('a/model.gguf');FreeBytes=100GB;Validated=$true}
    $script:RemoteReads=0;$script:Downloads=0;$script:WslCalls=0;$script:Logs=@();$script:ForbidRemote=$false
    Remove-Item -LiteralPath $script:Cfg.StateDirectory -Recurse -Force -ErrorAction SilentlyContinue
    Initialize-ModelVerificationCache (Join-Path $script:Cfg.StateDirectory 'proofs.json')
    Set-ModelVerificationMode $true
    & $module {$script:HashCalls=0;$script:ForbidHash=$false}
}
function Write-Weight($Path,[string]$Text='hello'){
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path))|Out-Null
    [IO.File]::WriteAllText($Path,$Text)
}
function Get-RequiredFiles {param($Root,$Models) return $script:Files}
function Read-WslModelState {param($Files,[switch]$Validate) return $script:Probe}
function Test-NetworkPath {param([string]$Path) return $Path.StartsWith((Join-Path $temporary 'network'))}
function Find-ModelFile {
    param($Roots,$File,[switch]$Full)
    foreach($path in $Roots){if(Test-NetworkPath $path){$script:RemoteReads++;if($script:ForbidRemote){throw 'Unexpected store access'}}}
    Core\Find-ModelFile $Roots $File -Full:$Full
}
function Progress {param($Phase,$Message,$Percent) $script:Logs+=$Message}
function Log {param($Message) $script:Logs+=$Message}
function Test-HfAccess {throw 'Unexpected gated access check'}
function Get-Download {param($Url,$Destination,$Token,$ExpectedBytes) $script:Downloads++;Write-Weight $Destination}
function Wsl {
    param($Arguments,[switch]$Capture)
    $script:WslCalls++
    if($Arguments[0] -eq 'cat'){return (@{run_id=$script:ReceiptId;verify_model_files=$script:ModelOptions.VerifyModelFiles;files=@($script:Files | Select-Object path,bytes)} | ConvertTo-Json -Depth 8)}
    $paths=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Arguments[3])) | ConvertFrom-Json
    $map=@{};foreach($p in $paths.PSObject.Properties){$map[$p.Name]='/mnt/synthetic/'+$p.Name}
    return 'KIENZLEDOKU_SOURCES='+($map | ConvertTo-Json -Compress)
}
try{
    Reset
    Case 'Old configurations default to checked hashes and retained staging; explicit false survives JSON' {
        $options=Get-ModelOptions ([pscustomobject]@{Version='1.9'})
        Assert ($options.VerifyModelFiles -and -not $options.CleanupModelStaging) 'Legacy defaults changed.'
        $path=Join-Path $temporary 'options.json'
        Write-Json $path @{VerifyModelFiles=$false;CleanupModelStaging=$true}
        $options=Get-ModelOptions (Read-Json $path)
        Assert (-not $options.VerifyModelFiles -and $options.CleanupModelStaging) 'Explicit choices lost.'
    }
    Case 'Disabled hashes never invoke Get-FileHash or create a false proof, including renamed copies' {
        Set-ModelVerificationMode $false;& $module {$script:ForbidHash=$true}
        $source=Join-Path $temporary 'unchecked.part';Write-Weight $source 'other'
        $dest=Join-Path $temporary 'unchecked.gguf'
        Assert (Test-ModelFile $source $script:Files[0] -Full) 'Size-only option ignored.'
        Move-VerifiedModelFile $source $dest $script:Files[0]
        Assert ((HashCalls) -eq 0) 'Hash disabled but invoked.'
        Assert (-not(Test-Path -LiteralPath (Join-Path $script:Cfg.StateDirectory 'proofs.json'))) 'False verification proof saved.'
        Set-ModelVerificationMode $true;& $module {$script:ForbidHash=$false}
        Assert (-not(Test-ModelFile $dest $script:Files[0] -Full)) 'Reenabled hashes accepted unchecked corrupt data.'
    }
    Case 'Engine-style hash progress callback works across the module boundary' {
        $script:Logs=@()
        Set-ModelVerificationMode $true {param($message) Progress 'models' $message 12}
        $path=Join-Path $temporary 'progress.gguf';Write-Weight $path
        Assert (Test-ModelFile $path $script:Files[0] -Full) 'Hash with reporting failed.'
        Assert (@($script:Logs | Where-Object {$_.StartsWith('Prüfsumme:')}).Count -eq 1) 'Hash progress not reported.'
    }
    Reset
    Case 'All models valid in WSL avoid store access, downloads and unnecessary local source conversion' {
        $script:Probe.RequiredPaths=@();$script:Probe.ReusedFiles=1;$script:Probe.AdditionalBytes=0;$script:ForbidRemote=$true
        Initialize-ModelPlan;Ensure-InstallModels;Set-LinuxModelSources
        Assert ($script:RemoteReads -eq 0 -and $script:Downloads -eq 0 -and $script:WslCalls -eq 0) 'Existing WSL model caused source work.'
        Assert ($script:ModelPlan['a/model.gguf'].Kind -eq 'wsl') 'Existing model ignored.'
    }
    Reset
    Case 'Retained local staging wins over an unavailable network store' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path;Write-Weight $source
        $script:ForbidRemote=$true
        Initialize-ModelPlan;Ensure-InstallModels;Set-LinuxModelSources
        Assert ($script:ModelPlan['a/model.gguf'].Source -eq $source) 'Retained staging ignored.'
        Assert ($script:RemoteReads -eq 0 -and $script:Downloads -eq 0) 'Retained file fetched again.'
        Assert ($script:Cfg.LinuxModelSources.PSObject.Properties['a/model.gguf'].Value -eq '/mnt/synthetic/a/model.gguf') 'Per-file Linux source missing.'
    }
    Reset
    Case 'A local archive is used directly without creating another staging copy' {
        $script:Cfg.CacheDirectory=Join-Path $temporary 'archive'
        $source=Get-ContainedPath $script:Cfg.CacheDirectory $script:Files[0].path;Write-Weight $source
        Initialize-ModelPlan;Ensure-InstallModels
        Assert ($script:ModelPlan['a/model.gguf'].Source -eq $source) 'Local archive ignored.'
        Assert (-not(Test-Path -LiteralPath (Get-StageDirectory))) 'Unnecessary local staging copy created.'
    }
    Reset
    Case 'Only the missing model is read from the store and copied; the store is not rewritten' {
        $second=$script:Files[0] | ConvertTo-Json | ConvertFrom-Json;$second.path='b/model.gguf';$script:Files+=,$second
        $script:Probe.RequiredPaths=@('b/model.gguf');$script:Probe.ReusedFiles=1
        $source=Get-ContainedPath $script:Cfg.CacheDirectory $second.path;Write-Weight $source
        Initialize-ModelPlan;Ensure-InstallModels
        Assert ($script:RemoteReads -eq 1 -and $script:Downloads -eq 0) 'Unneeded store reads or download.'
        Assert (Test-Path -LiteralPath (Get-ContainedPath (Get-StageDirectory) $second.path)) 'Required copy missing.'
        Assert (-not(Test-Path -LiteralPath (Join-Path $script:Cfg.CacheDirectory 'verified-manifest.json'))) 'Install rewrote source store.'
        Assert (@(Get-ModelStageRecords).Count -eq 1) 'Staging ownership missing.'
    }
    Reset
    Case 'Missing ungated download works with hashes disabled and records ownership, not a checksum proof' {
        $script:ModelOptions.VerifyModelFiles=$false;Set-ModelVerificationMode $false
        & $module {$script:ForbidHash=$true}
        $script:Cfg.CacheDirectory=Join-Path $temporary 'network-empty'
        Initialize-ModelPlan;Ensure-InstallModels
        Assert ($script:Downloads -eq 1 -and (HashCalls) -eq 0) 'Disabled download rehashed.'
        Assert (@(Get-ModelStageRecords).Count -eq 1) 'Downloaded stage not tracked.'
    }
    Reset
    Case 'Keep option leaves owned staging untouched and requests no import receipt' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path;Write-Weight $source
        Register-ModelStage $source $script:Files[0];Complete-ModelStaging
        Assert ((Test-Path -LiteralPath $source) -and $script:WslCalls -eq 0) 'Keep option deleted staging or queried WSL.'
    }
    Case 'Opt-in cleanup removes only unchanged owned files covered by this run receipt' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path
        $script:ModelOptions.CleanupModelStaging=$true;$script:ReceiptId=$script:Cfg.ModelImportId
        $unknown=Join-Path (Get-StageDirectory) 'personal.txt';Write-Weight $unknown
        Complete-ModelStaging
        Assert (-not(Test-Path -LiteralPath $source)) 'Owned completed copy retained.'
        Assert ((Test-Path -LiteralPath $unknown) -and (Test-Path -LiteralPath $script:Cfg.CacheDirectory)) 'Unrelated file or archive removed.'
    }
    Reset
    Case 'Failed or stale run receipt cannot authorize cleanup' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path;Write-Weight $source;Register-ModelStage $source $script:Files[0]
        $script:ModelOptions.CleanupModelStaging=$true;$script:ReceiptId='older-run'
        $failed=$false;try{Complete-ModelStaging}catch{$failed=$true}
        Assert ($failed -and (Test-Path -LiteralPath $source)) 'Stale receipt deleted file.'
    }
    Case 'Changed owned file is retained even with a current import receipt' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path
        $script:ReceiptId=$script:Cfg.ModelImportId;Write-Weight $source 'other-data'
        Complete-ModelStaging
        Assert (Test-Path -LiteralPath $source) 'Changed staging deleted.'
    }
    Reset
    Case 'Explicit archive sharing the staging directory is protected' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path;Write-Weight $source;Register-ModelStage $source $script:Files[0]
        $script:Cfg.CacheDirectory=Get-StageDirectory;$script:ModelOptions.CleanupModelStaging=$true
        Complete-ModelStaging
        Assert ((Test-Path -LiteralPath $source) -and $script:WslCalls -eq 0) 'Archive mistaken for temporary staging.'
    }
    Reset
    Case 'A local archive alias pointing into staging prevents cleanup' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path;Write-Weight $source;Register-ModelStage $source $script:Files[0]
        $alias=Join-Path $script:Cfg.InstallDirectory 'archive-alias'
        New-Item -ItemType SymbolicLink -Path $alias -Target (Get-StageDirectory)|Out-Null
        $script:Cfg.CacheDirectory=$alias;$script:ModelOptions.CleanupModelStaging=$true
        Complete-ModelStaging
        Assert (Test-Path -LiteralPath $source) 'Archive alias deleted.'
    }
    Reset
    Case 'Legacy network staging is adopted only from the prior matching installation layout' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path;Write-Weight $source
        Write-Json (Join-Path $script:Cfg.InstallDirectory 'config.json') @{Version='1.9';InstallDirectory=$script:Cfg.InstallDirectory;CacheDirectory=$script:Cfg.CacheDirectory}
        $script:ModelOptions.CleanupModelStaging=$true;$script:Probe.RequiredPaths=@();$script:ReceiptId=$script:Cfg.ModelImportId
        Initialize-ModelPlan;Complete-ModelStaging
        Assert (-not(Test-Path -LiteralPath $source)) 'Known legacy staging not cleaned.'
    }
    Reset
    Case 'Mapped share resolving to the staging archive prevents deletion' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path;Write-Weight $source;Register-ModelStage $source $script:Files[0]
        $script:ModelOptions.CleanupModelStaging=$true
        $originalResolver=(Get-Command Resolve-ModelProtectedPath).ScriptBlock
        function Resolve-ModelProtectedPath {param($Path) return (Get-StageDirectory)}
        Complete-ModelStaging
        Assert (Test-Path -LiteralPath $source) 'Mapped archive was deleted.'
        Set-Item Function:Resolve-ModelProtectedPath -Value $originalResolver
    }
    Case 'Unresolved share identity conservatively retains staging' {
        $source=Get-ContainedPath (Get-StageDirectory) $script:Files[0].path
        $originalResolver=(Get-Command Resolve-ModelProtectedPath).ScriptBlock
        function Resolve-ModelProtectedPath {param($Path) return $null}
        Complete-ModelStaging
        Assert (Test-Path -LiteralPath $source) 'Unresolved archive guard deleted staging.'
        Set-Item Function:Resolve-ModelProtectedPath -Value $originalResolver
    }
    $tokens=$null;$errors=$null
    $wizard=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Wizard.ps1'),[ref]$tokens,[ref]$errors)
    foreach($name in @('Build-Config','Refresh-Inventory')){
        $definition=$wizard.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
        . ([scriptblock]::Create($definition.Extent.Text))
    }
    Case 'Wizard saves file-check and cleanup choices without enabling force when checks are off' {
        function Selected-Models {return '9b-q4'}
        function Selected-ParallelModel {return ''}
        function Source-Roots {return @($script:Cache.Text)}
        $script:InstallerVersion='1.10';$script:State=$temporary
        $script:HfToken=[pscustomobject]@{Text='synthetic-token'};$script:Cache=[pscustomobject]@{Text=(Join-Path $temporary 'chosen-archive')}
        $script:Default=[pscustomobject]@{SelectedItem='9b-q4'};$script:Ram=[pscustomobject]@{SelectedIndex=1}
        $script:Lan=[pscustomobject]@{Checked=$false};$script:DiskCache=[pscustomobject]@{Checked=$false}
        $script:InstallPath=[pscustomobject]@{Text=(Join-Path $temporary 'app')}
        $script:Autostart=[pscustomobject]@{Checked=$false};$script:StartAfter=[pscustomobject]@{Checked=$false}
        $script:Verify=[pscustomobject]@{Checked=$true};$script:VerifyFiles=[pscustomobject]@{Checked=$false}
        $script:CleanupStages=[pscustomobject]@{Checked=$true};$script:RecheckModels=[pscustomobject]@{Checked=$true;Enabled=$true}
        $script:InstallRadio=[pscustomobject]@{Checked=$false}
        $cfg=Build-Config
        Assert (-not $cfg.VerifyModelFiles -and $cfg.CleanupModelStaging -and -not $cfg.ForceModelVerification -and $cfg.Verify) 'GUI choices conflated.'
    }
    Case 'Checkbox event disables and clears force checking while preserving independent server verification' {
        $handler=$wizard.Find({param($n)$n -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $n.Extent.Text.StartsWith('$script:VerifyFiles.Add_CheckedChanged')},$true)
        $callback=$handler.Arguments[0].ScriptBlock.GetScriptBlock()
        & $callback
        Assert (-not $script:RecheckModels.Enabled -and -not $script:RecheckModels.Checked -and $script:Verify.Checked) 'Disabled model checks left forced hashing on.'
        $script:VerifyFiles.Checked=$true;& $callback
        Assert ($script:RecheckModels.Enabled -and -not $script:RecheckModels.Checked) 'Checkbox enable behaviour incorrect.'
    }
    Case 'Startup inventory avoids network roots until the user explicitly checks the archive' {
        function Source-Roots {return @((Join-Path $temporary 'network'),(Join-Path $temporary 'local'))}
        function Get-Inventory {param($Root,$Sources) $script:InventoryRoots=@($Sources);return @()}
        $script:Inventory=[pscustomobject]@{Items=(New-Object Collections.ArrayList)}
        Refresh-Inventory
        Assert (@($script:InventoryRoots | Where-Object {Test-NetworkPath $_}).Count -eq 0) 'Automatic inventory touched network store.'
        Refresh-Inventory -IncludeNetwork
        Assert (@($script:InventoryRoots | Where-Object {Test-NetworkPath $_}).Count -eq 1) 'Explicit archive check ignored.'
    }
    Write-Output "All $script:Passed model-option/source/cleanup cases passed (portable PowerShell; synthetic files and WSL responses)."
}finally{Set-ModelVerificationMode $true;Remove-Item -LiteralPath $temporary -Recurse -Force}
