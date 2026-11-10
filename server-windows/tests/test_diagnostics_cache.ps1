$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path -Parent $PSScriptRoot
$module=Import-Module (Join-Path $root 'windows/Core.psm1') -Force -PassThru -DisableNameChecking
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-cache-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary)|Out-Null
try{
    $cache=Join-Path $temporary 'checks.json';$path=Join-Path $temporary 'model.gguf'
    [IO.File]::WriteAllText($path,'hello')
    $file=[pscustomobject]@{bytes=5;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash}
    & $module {
        $script:HashCalls=0
        function script:Get-FileHash {
            param([string]$LiteralPath,[string]$Algorithm)
            $script:HashCalls++
            Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $LiteralPath -Algorithm $Algorithm
        }
    }
    function HashCalls { & $module {$script:HashCalls} }
    Case 'Unchanged verified file survives a fresh cache load without another hash' {
        Initialize-ModelVerificationCache $cache -Force
        Assert (Test-ModelFile $path $file -Full) 'Initial hash failed.'
        Initialize-ModelVerificationCache $cache
        Assert (Test-ModelFile $path $file -Full) 'Persisted proof missing.'
        Assert ((HashCalls) -eq 1) 'Unchanged model was read again.'
    }
    Case 'Changed expected checksum and same-sized corruption invalidate proofs' {
        $wrong=[pscustomobject]@{bytes=5;sha256=('0'*64)}
        Assert (-not(Test-ModelFile $path $wrong -Full)) 'Changed checksum ignored.'
        Assert (Test-ModelFile $path $file -Full) 'Correct file not reverified.'
        [IO.File]::WriteAllText($path,'other');[IO.File]::SetLastWriteTimeUtc($path,[DateTime]::UtcNow.AddSeconds(2))
        Assert (-not(Test-ModelFile $path $file -Full)) 'Same-sized changed file accepted.'
        Initialize-ModelVerificationCache $cache
        Assert (-not(Test-ModelFile $path $file -Full)) 'Failed validation was cached as success.'
    }
    Case 'Explicit full recheck ignores disk proofs but deduplicates within that run' {
        [IO.File]::WriteAllText($path,'hello');Assert (Test-ModelFile $path $file -Full) 'Restore failed.'
        $before=HashCalls
        Initialize-ModelVerificationCache $cache -Force
        Assert (Test-ModelFile $path $file -Full) 'Forced validation failed.'
        Assert (Test-ModelFile $path $file -Full) 'Same-run validation failed.'
        Assert ((HashCalls) -eq $before+1) 'Force or same-run deduplication failed.'
    }
    Case 'Copy needs a separate hash while a checked atomic rename preserves the proof' {
        $stage=Join-Path $temporary 'new.part';$target=Join-Path $temporary 'new.gguf'
        Copy-Item -LiteralPath $path -Destination $stage
        $before=HashCalls
        Assert (Test-ModelFile $stage $file -Full) 'New copy invalid.'
        Assert ((HashCalls) -eq $before+1) 'New copy trusted the source proof.'
        Move-VerifiedModelFile $stage $target $file
        Assert (Test-ModelFile $target $file -Full) 'Renamed proof lost.'
        Assert ((HashCalls) -eq $before+1) 'Rename caused redundant hashing.'
    }
    Case 'Corrupt cache is rebuilt instead of blocking installation' {
        [IO.File]::WriteAllText($cache,'{invalid')
        Initialize-ModelVerificationCache $cache
        Assert (Test-ModelFile $path $file -Full) 'Bad cache blocked validation.'
    }
    Case 'Unexpected process death reports phase, signed and hexadecimal exit code and stderr' {
        $stderr=Join-Path $temporary 'stderr.log';[IO.File]::WriteAllText($stderr,'fatal: synthetic failure SECRET')
        $progress=[pscustomobject]@{Phase='server';Message='Serverlaufzeiten installieren';Finished=$false}
        $result=Get-OperationResult $progress -1073741819 $stderr '' 'SECRET'
        Assert ($result.UnexpectedExit -and -not $result.Success -and $result.Finished) 'Abrupt exit hidden.'
        Assert ($result.Message.Contains('0xC0000005') -and $result.Message.Contains('server') -and $result.Message.Contains('synthetic failure')) 'Useful details missing.'
        Assert (-not $result.Message.Contains('SECRET')) 'HF token leaked.'
    }
    Case 'Zero exit without final status and success status with nonzero exit are failures' {
        Assert ((Get-OperationResult $null 0).UnexpectedExit) 'Missing completion treated as success.'
        $progress=[pscustomobject]@{Phase='complete';Message='ok';Finished=$true;Success=$true}
        Assert (-not(Get-OperationResult $progress 4).Success) 'Nonzero exit hidden.'
        Assert ((Get-OperationResult $progress 0).Success) 'Valid completion rejected.'
    }
    Case 'Expected restart remains distinct from an unexpected process crash' {
        $progress=[pscustomobject]@{Phase='restart';Message='Windows neu starten';Finished=$true;Success=$false}
        $result=Get-OperationResult $progress 3010
        Assert ($result.RestartRequired -and -not $result.UnexpectedExit) 'Expected reboot became crash.'
    }
    Case 'Real child stderr and exit code are retained by the result resolver' {
        $stdout=Join-Path $temporary 'child.stdout';$stderr=Join-Path $temporary 'child.stderr'
        $python=(Get-Command python3).Source
        $arguments=ConvertTo-NativeArguments @('-c','import sys; print("synthetic checkout failure",file=sys.stderr); sys.exit(17)')
        $child=Start-Process -FilePath $python -ArgumentList $arguments -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -Wait
        $result=Get-OperationResult $null $child.ExitCode $stderr $stdout
        Assert ($result.ExitCode -eq 17 -and $result.Message.Contains('synthetic checkout failure')) 'Child details lost.'
    }
    Case 'Native failure includes command, exit code, stderr and the last program output' {
        $tokens=$null;$errors=$null
        $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Engine.ps1'),[ref]$tokens,[ref]$errors)
        $definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-Native'},$true)
        . ([scriptblock]::Create($definition.Extent.Text))
        $script:Token='';$script:CurrentPhase='server';$script:Cfg=[pscustomobject]@{StateDirectory=$temporary}
        function Log([string]$Message){}
        $failure=''
        try{Invoke-Native (Get-Command python3).Source @('-c','import sys; print("synthetic build stage"); print("synthetic fatal detail",file=sys.stderr); sys.exit(17)')}
        catch{$failure=$_.Exception.Message}
        Assert ($failure.Contains('Exitcode 17') -and $failure.Contains('synthetic fatal detail') -and $failure.Contains('synthetic build stage')) 'Native failure lacks diagnostic context.'
        $native=Read-Json (Join-Path $temporary 'native-process.json')
        Assert ($native.Phase -eq 'server' -and $native.Command.Contains('python')) 'Last process record missing.'
    }
    Write-Output "All $script:Passed diagnostics/cache regression cases passed (portable PowerShell; no Windows GUI executed)."
}finally{Remove-Item -LiteralPath $temporary -Recurse -Force}
