$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Engine.ps1'),[ref]$tokens,[ref]$errors)
foreach($name in @('Invoke-Native','Get-WslVersion','Initialize-WslFeatures')){
    $definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
function Log([string]$Message){$script:Log+=$Message}
function Reset {
    $script:Log=@();$script:Calls=@();$script:Enabled=@();$script:State='Enabled';$script:Restart=$false
    $script:Replies=New-Object 'Collections.Generic.Queue[object]'
}
function Reply([int]$Code,[string]$Output){$script:Replies.Enqueue([pscustomobject]@{ExitCode=$Code;Output=$Output})}
function Get-WindowsOptionalFeature {param([switch]$Online,[string]$FeatureName) [pscustomobject]@{State=$script:State}}
function Enable-WindowsOptionalFeature {param([switch]$Online,[string]$FeatureName,[switch]$All,[switch]$NoRestart) $script:Enabled+=$FeatureName;[pscustomobject]@{RestartNeeded=$script:Restart}}
function Invoke-WslManagement {param([string[]]$Arguments,[switch]$Result) $script:Calls+=($Arguments -join ' ');if(-not $Result){throw 'Expected a structured result.'};return $script:Replies.Dequeue()}

Case 'Existing WSL 3.0.3 after reboot skips reinstallation and feature activation' {
    Reset;Reply 0 "WSL-Version: 3.0.3.0`nKernelversion: 6.6.0"
    Assert ((Initialize-WslFeatures) -eq 0) 'Ready WSL rejected.'
    Assert ($script:Calls.Count -eq 1 -and $script:Calls[0] -eq '--version' -and $script:Enabled.Count -eq 0) 'Already enabled components/WSL were reinstalled.'
}
Case 'Reported bootstrap exit -1 is accepted only after successful version probe' {
    Reset;Reply 1 'WSL not installed';Reply -1 'Windows-Subsystem fuer Linux 3.0.3 wurde installiert.';Reply 0 'WSL-Version: 3.0.3'
    Assert ((Initialize-WslFeatures) -eq 0) 'Reported bootstrap flow rejected.'
    Assert ($script:Calls[1] -eq '--install --no-distribution --web-download' -and $script:Calls[2] -eq '--version') 'Installed WSL was not checked.'
}
Case 'Success text cannot hide a failed bootstrap without a working version command' {
    Reset;Reply 1 'missing';Reply -1 'wurde installiert';Reply 1 'still unavailable'
    $failed=$false;try{Initialize-WslFeatures}catch{$failed=$true}
    Assert $failed 'Real failure was hidden.'
}
Case 'Feature restart is returned as 3010 without attempting WSL bootstrap' {
    Reset;$script:State='Disabled';$script:Restart=$true
    Assert ((Initialize-WslFeatures) -eq 3010) 'Restart not propagated.'
    Assert ($script:Enabled.Count -eq 2 -and $script:Calls.Count -eq 0) 'Bootstrap ran before required reboot.'
}
Case 'Pending Windows feature state requests restart without enabling it again' {
    Reset;$script:State='EnablePending'
    Assert ((Initialize-WslFeatures) -eq 3010 -and $script:Enabled.Count -eq 0) 'Pending feature state mishandled.'
}
Case 'Old WSL is updated instead of a new distribution being installed' {
    Reset;Reply 0 'WSL version: 1.2.5';Reply 0 'updated';Reply 0 'WSL version: 3.0.3'
    Assert ((Initialize-WslFeatures) -eq 0 -and $script:Calls[1] -eq '--update --web-download') 'Old WSL update flow incorrect.'
}
Case 'WSL installer reboot exit is preserved rather than treated as failure' {
    Reset;Reply 1 'missing';Reply 3010 'Restart required'
    Assert ((Initialize-WslFeatures) -eq 3010 -and $script:Calls.Count -eq 2) 'Installer reboot exit lost.'
}
Case 'Help or no-distribution text is not proof of installed modern WSL' {
    Assert ($null -eq (Get-WslVersion ([pscustomobject]@{ExitCode=0;Output='Usage: wsl.exe --version'}))) 'Help mistaken for version.'
    Assert ($null -eq (Get-WslVersion ([pscustomobject]@{ExitCode=1;Output='WSL version: 3.0.3'}))) 'Failed probe accepted.'
}
Case 'Native UTF-16LE management output retains German text and structured exit code' {
    Reset;$python=(Get-Command python3).Source
    $code='import sys; sys.stdout.buffer.write("WSL-Version: 3.0.3\nVorgang erfolgreich; f\u00fcr Linux\n".encode("utf-16-le")); sys.exit(7)'
    $result=Invoke-Native $python @('-c',$code) -Result -OutputEncoding ([Text.Encoding]::Unicode)
    Assert ($result.ExitCode -eq 7 -and $result.Output.Contains('für Linux') -and -not $result.Output.Contains([char]0)) 'UTF-16LE output corrupted.'
}
Write-Output "All $script:Passed WSL bootstrap regression cases passed (Windows feature/WSL responses simulated; child-process encoding tested)."
