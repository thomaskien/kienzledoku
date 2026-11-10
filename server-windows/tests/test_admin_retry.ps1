$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Engine.ps1'),[ref]$tokens,[ref]$errors)
foreach($name in @('Elevated','Assert-AdminRetryNotCancelled','Wait-AdminRetry')){
    $definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){Reset;& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-uac-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary)|Out-Null
$oldWindir=$env:windir;$env:windir=$temporary;$ConfigPath='synthetic-config.json'
function Reset {
    $script:Cfg=[pscustomobject]@{StateDirectory=$temporary;AdminRetryId=[guid]::NewGuid().ToString('N')}
    $script:Replies=New-Object 'Collections.Generic.Queue[object]'
    $script:Calls=@();$script:Progress=@();$script:SleepSeconds=0;$script:CancelAt=0
}
function Reply($Code,[switch]$Wrapped,[switch]$Child){$script:Replies.Enqueue([pscustomobject]@{Code=$Code;Wrapped=[bool]$Wrapped;Child=[bool]$Child})}
function Progress {param($Phase,$Message,$Percent) $script:Progress+=@{Phase=$Phase;Message=$Message;Percent=$Percent}}
function Start-Sleep {
    param([int]$Seconds)
    $script:SleepSeconds+=$Seconds
    if($script:CancelAt -and $script:SleepSeconds -ge $script:CancelAt){[IO.File]::WriteAllText((Get-AdminRetryCancelPath $script:Cfg),'cancel')}
}
function Invoke-AdminProcess {
    param($FilePath,$Arguments)
    $script:Calls+=@{File=$FilePath;Args=$Arguments}
    if(-not $script:Replies.Count){throw 'Unexpected extra elevation attempt'}
    $reply=$script:Replies.Dequeue()
    if($reply.Child){return $reply.Code}
    $failure=[ComponentModel.Win32Exception]::new($reply.Code,'synthetic launch failure')
    if($reply.Wrapped){throw [InvalidOperationException]::new('outer launch failure',$failure)}
    throw $failure
}
try{
    Case 'Accepted network elevation proceeds immediately with the same admin-only helper' {
        Reply 0 -Child
        Assert ((Elevated Network) -eq 0) 'Successful network helper failed.'
        Assert ($script:Calls.Count -eq 1 -and $script:SleepSeconds -eq 0) 'Accepted request retried or delayed.'
        Assert ($script:Calls[0].Args.Contains('-Action Network')) 'Helper invocation changed.'
        Assert ($script:Progress[-1].Phase -eq 'network') 'Normal phase not restored.'
    }
    Case 'WSL restart result 3010 remains a restart rather than a retry condition' {
        Reply 3010 -Child
        Assert ((Elevated Features) -eq 3010 -and $script:SleepSeconds -eq 0) 'Restart was retried.'
        Assert ($script:Progress[-1].Phase -eq 'wsl') 'WSL phase not restored.'
    }
    Case 'Two unconfirmed requests each log the required message and wait exactly 30 seconds' {
        Reply 1223;Reply 1223;Reply 0 -Child
        Assert ((Elevated Network) -eq 0) 'Retry did not recover.'
        $waiting=@($script:Progress | Where-Object {$_.Phase -eq 'admin_wait'})
        Assert ($waiting.Count -eq 2 -and $script:Calls.Count -eq 3 -and $script:SleepSeconds -eq 60) 'Wrong attempts or pause.'
        foreach($message in $waiting){Assert ($message.Message.Contains('Administrator nicht bestätigt; neuer Versuch in 30 Sekunden.')) 'Required log message missing.'}
    }
    Case 'Repeated refusal or timeout has no fixed attempt limit' {
        foreach($n in 1..20){Reply 1223};Reply 0 -Child
        Assert ((Elevated Features) -eq 0) 'Retry stopped at a fixed limit.'
        Assert ($script:Calls.Count -eq 21 -and $script:SleepSeconds -eq 600) 'Retry count or pause changed.'
    }
    Case 'Wrapped Win32 cancellation uses the same retry handling' {
        Reply 1223 -Wrapped;Reply 0 -Child
        Assert ((Elevated Features) -eq 0 -and $script:SleepSeconds -eq 30) 'Inner cancellation not recognized.'
    }
    Case 'Access denied launch failure is preserved and never retried' {
        Reply 5;$message=''
        try{Elevated Network}catch{$message=$_.Exception.Message}
        Assert ($message.Contains('synthetic launch failure') -and $script:Calls.Count -eq 1 -and $script:SleepSeconds -eq 0) 'Real launch failure retried or hidden.'
    }
    Case 'An already approved helper with a real error does not restart the administrator prompt' {
        Reply 1 -Child;$message=''
        try{Elevated Features}catch{$message=$_.Exception.Message}
        Assert ($message.Contains('Administrativer Schritt fehlgeschlagen') -and $script:Calls.Count -eq 1 -and $script:SleepSeconds -eq 0) 'Helper failure became an elevation retry.'
    }
    Case 'Explicit installer cancellation before the next prompt prevents any elevation' {
        [IO.File]::WriteAllText((Get-AdminRetryCancelPath $script:Cfg),'cancel');$cancelled=$false
        try{Elevated Network}catch{$cancelled=$_.Exception -is [OperationCanceledException]}
        Assert ($cancelled -and $script:Calls.Count -eq 0 -and $script:SleepSeconds -eq 0) 'Cancelled install requested elevation.'
    }
    Case 'Cancellation during the 30-second pause stops promptly and prevents the next prompt' {
        Reply 1223;Reply 0 -Child;$script:CancelAt=5;$cancelled=$false
        try{Elevated Features}catch{$cancelled=$_.Exception -is [OperationCanceledException]}
        Assert ($cancelled -and $script:Calls.Count -eq 1 -and $script:SleepSeconds -eq 5) 'Pause cancellation ignored.'
    }
    Case 'Cancel marker is restricted to the current validated run ID and state directory' {
        $first=Get-AdminRetryCancelPath $script:Cfg
        $script:Cfg.AdminRetryId=[guid]::NewGuid().ToString('N')
        Assert ((Get-AdminRetryCancelPath $script:Cfg) -ne $first) 'Different run reused cancellation marker.'
        foreach($bad in @('../escape','',('a'*33))){$script:Cfg.AdminRetryId=$bad;Assert ((Get-AdminRetryCancelPath $script:Cfg) -eq '') 'Unsafe run ID accepted.'}
        Assert ((Get-AdminRetryCancelPath ([pscustomobject]@{StateDirectory=$temporary})) -eq '') 'Legacy config unexpectedly acquired a marker.'
    }
    $launcher=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-AdminProcess'},$true)
    . ([scriptblock]::Create($launcher.Extent.Text.Replace('function Invoke-AdminProcess','function Invoke-RealAdminProcess')))
    Case 'Shell helper preserves native cancellation instead of matching localized error text' {
        $script:FakeNativeError=1223
        $script:FakeInfo=[pscustomobject]@{FileName='';Arguments='';UseShellExecute=$false;Verb=''}
        $script:FakeProcess=[pscustomobject]@{StartInfo=$null;ExitCode=0;Disposed=$false;Waited=$false}
        $script:FakeProcess | Add-Member ScriptMethod Start {if($script:FakeNativeError){throw [ComponentModel.Win32Exception]::new($script:FakeNativeError,'localized prompt failure')};return $true}
        $script:FakeProcess | Add-Member ScriptMethod WaitForExit {$this.Waited=$true}
        $script:FakeProcess | Add-Member ScriptMethod Dispose {$this.Disposed=$true}
        function New-Object {
            param($TypeName)
            if($TypeName -eq 'Diagnostics.ProcessStartInfo'){return $script:FakeInfo}
            if($TypeName -eq 'Diagnostics.Process'){return $script:FakeProcess}
            throw 'Unexpected object factory'
        }
        $native=0
        try{Invoke-RealAdminProcess 'powershell.exe' 'synthetic args'}catch{
            $cause=$_.Exception
            while($cause){if($cause -is [ComponentModel.Win32Exception]){$native=$cause.NativeErrorCode};$cause=$cause.InnerException}
        }
        Assert ($native -eq 1223 -and $script:FakeProcess.Disposed) 'Native code was lost or process was not disposed.'
        Assert ($script:FakeInfo.UseShellExecute -and $script:FakeInfo.Verb -eq 'runas') 'Shell/UAC approval bypassed.'
        $script:FakeNativeError=0;$script:FakeProcess.Disposed=$false
        Assert ((Invoke-RealAdminProcess 'powershell.exe' 'synthetic args') -eq 0 -and $script:FakeProcess.Waited -and $script:FakeProcess.Disposed) 'Accepted helper was not awaited/disposed.'
    }
    $wizard=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Wizard.ps1'),[ref]$tokens,[ref]$errors)
    foreach($name in @('Update-AdminRetryCancelControl','Request-AdminRetryCancellation')){
        $definition=$wizard.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
        . ([scriptblock]::Create($definition.Extent.Text))
    }
    Case 'Wizard exposes cancellation only in the retry pause and sends a run-specific request' {
        $script:Busy=$true;$script:AdminCancelSent=$false
        $script:Cancel=[pscustomobject]@{Text='Schließen';Enabled=$true}
        $script:ProgressLabel=[pscustomobject]@{Text=''}
        Update-AdminRetryCancelControl admin_prompt
        Assert (-not $script:CanCancelAdminRetry) 'Secure-desktop prompt incorrectly treated as a pause.'
        Update-AdminRetryCancelControl admin_wait
        Assert ($script:CanCancelAdminRetry -and $script:Cancel.Text -eq 'Abbrechen') 'Cancel button missing during pause.'
        Request-AdminRetryCancellation
        Assert ((Test-Path -LiteralPath (Get-AdminRetryCancelPath $script:Cfg)) -and $script:AdminCancelSent -and -not $script:Cancel.Enabled) 'Cancel request not sent.'
        Assert (-not $script:CanCancelAdminRetry) 'Repeated cancel remained enabled.'
    }
    Write-Output "All $script:Passed administrator retry cases passed (portable PowerShell; UAC and delays simulated)."
}finally{
    $env:windir=$oldWindir
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
