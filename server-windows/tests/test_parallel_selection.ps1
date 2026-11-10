$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
$catalog=Get-Catalog $root
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
Case 'Only the explicitly selected Q6 is parallel while Q4 stays the request default' {
    $plan=Get-ProfilePlan $catalog @('9b-q4','9b-q6','27b-q4') '9b-q4' selected 24576 32 ram '9b-q6'
    Assert ($plan['9b-q6'].Mode -eq 'parallel' -and $plan['9b-q4'].Mode -eq 'serial' -and $plan['27b-q4'].Mode -eq 'serial') 'Selection still coupled to request default.'
}
Case 'An empty parallel selection makes every installed LLM serial' {
    $plan=Get-ProfilePlan $catalog @('9b-q4','9b-q6','27b-q4') '27b-q4' selected 24576 32 ram ''
    Assert (@($plan.Values | Where-Object {$_.Mode -ne 'serial'}).Count -eq 0) 'Unselected model made parallel.'
}
Case 'Only selected models whose GPU parallel profile fits are offered' {
    Assert ((@(Get-ParallelModelChoices $catalog @('9b-q4','9b-q6','27b-q4') 24576) -join ',') -eq '9b-q4,9b-q6') 'Incorrect 24-GiB choices.'
    Assert (@(Get-ParallelModelChoices $catalog @('9b-q6') 16384).Count -eq 0) 'Insufficient GPU accepted.'
}
Case 'Uninstalled, unsupported and GPU-incompatible parallel choices fail explicitly' {
    foreach($parallel in @('9b-q6','27b-q4','missing')){
        $failed=$false
        try{Get-ProfilePlan $catalog @('9b-q4','27b-q4') '9b-q4' selected 24576 32 ram $parallel}catch{$failed=$true}
        Assert $failed ('Invalid choice accepted: '+$parallel)
    }
    $failed=$false;try{Get-ProfilePlan $catalog @('9b-q6') '9b-q6' selected 16384 24 ram '9b-q6'}catch{$failed=$true}
    Assert $failed 'Q6 parallel on 16-GiB GPU accepted.'
}
Case 'A new catalogue entry requires no hard-coded selection list' {
    $extra=$catalog.'9b-q4' | ConvertTo-Json -Depth 24 | ConvertFrom-Json
    $extra.quality='future_14b';$extra.label='Synthetic future model';$extra.parallel_vram_mib=22000
    $catalog | Add-Member -NotePropertyName 'future-14b' -NotePropertyValue $extra
    $plan=Get-ProfilePlan $catalog @('9b-q4','future-14b') '9b-q4' selected 24576 32 ram 'future-14b'
    Assert ($plan['future-14b'].Mode -eq 'parallel' -and $plan['9b-q4'].Mode -eq 'serial') 'New entry ignored.'
    Assert ('future-14b' -in @(Get-ParallelModelChoices $catalog @('future-14b') 24576)) 'New eligible entry absent.'
}
Case 'Duplicate API model IDs are rejected before configuration overwrites a model' {
    $catalog.'future-14b'.quality='basis';$failed=$false
    try{Get-ProfilePlan $catalog @('9b-q4','future-14b') '9b-q4' selected 24576 32 ram 'future-14b'}catch{$failed=$true}
    Assert $failed 'Duplicate quality/model ID accepted.'
    $catalog.'future-14b'.quality='future_14b'
}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Wizard.ps1'),[ref]$tokens,[ref]$errors)
foreach($name in @('Selected-Models','Selected-ParallelModel','Update-ParallelModels')){
    $definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:Catalog=$catalog;$script:ModelOrder=@($catalog.PSObject.Properties | ForEach-Object {$_.Name})
$script:ModelChecks=@{};foreach($id in $script:ModelOrder){$script:ModelChecks[$id]=[pscustomobject]@{Checked=$true}}
$script:Parallel=[pscustomobject]@{Items=(New-Object Collections.ArrayList);SelectedIndex=-1}
$script:ParallelIds=@('');$script:Gpu=[pscustomobject]@{SelectedIndex=0}
$script:Hardware=[pscustomobject]@{Gpus=@([pscustomobject]@{VramMiB=24576})}
Case 'Wizard selector uses the catalogue and preserves an explicit choice' {
    Update-ParallelModels 'future-14b'
    Assert ((Selected-ParallelModel) -eq 'future-14b') 'Wizard lost explicit choice.'
    Assert ($script:Parallel.Items[0] -eq 'Keines — alle LLMs seriell') 'All-serial option missing.'
    Assert ('27b-q4' -notin $script:ParallelIds) 'Unsupported parallel profile offered.'
}
Case 'Removing a selected model or changing to a smaller GPU clears the incompatible selection' {
    $script:ModelChecks['future-14b'].Checked=$false;Update-ParallelModels
    Assert ((Selected-ParallelModel) -eq '') 'Removed model remained selected.'
    Update-ParallelModels '9b-q6';$script:Hardware.Gpus[0].VramMiB=8192;Update-ParallelModels
    Assert ((Selected-ParallelModel) -eq '' -and $script:Parallel.Items.Count -eq 1) 'GPU change retained incompatible profile.'
}
Write-Output "All $script:Passed explicit parallel-selection cases passed (portable PowerShell; selector controls simulated)."
