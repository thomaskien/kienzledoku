$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
$catalog=Get-Catalog $root
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
$models=@($catalog.PSObject.Properties | ForEach-Object {$_.Name})
$gemma=@('gemma12-qat-q4','gemma12-q8','gemma26-qat-q4')
Case 'Six catalogue models retain the original Qwen models and add three Gemma models' {
    Assert ($models.Count -eq 6) 'Incorrect catalogue size.'
    foreach($id in @('9b-q4','9b-q6','27b-q4')+$gemma){Assert ($id -in $models) ('Missing '+$id)}
}
Case '16-GiB GPU offers the QAT 12B parallel selection only among the Gemma entries' {
    $choices=@(Get-ParallelModelChoices $catalog $gemma 16384)
    Assert (($choices -join ',') -eq 'gemma12-qat-q4') 'Incorrect 16-GiB Gemma choices.'
    $plan=Get-ProfilePlan $catalog @('9b-q4','gemma12-qat-q4') '9b-q4' selected 16384 24 ram 'gemma12-qat-q4'
    Assert ($plan['gemma12-qat-q4'].Mode -eq 'parallel' -and $plan['9b-q4'].Mode -eq 'serial') 'Incorrect resident.'
}
Case '24-GiB GPU offers all three Gemma entries with exactly one explicit resident' {
    $choices=@(Get-ParallelModelChoices $catalog $gemma 24576)
    Assert (($choices -join ',') -eq ($gemma -join ',')) 'Incorrect 24-GiB Gemma choices.'
    foreach($id in $gemma){
        $plan=Get-ProfilePlan $catalog $models '27b-q4' selected 24576 32 ram $id
        Assert ($plan[$id].Mode -eq 'parallel') ('Missing parallel mode: '+$id)
        Assert (@($plan.Values | Where-Object {$_.Mode -eq 'parallel'}).Count -eq 1) 'Multiple resident models.'
    }
}
Case 'All six models can be configured serially on a 24-GiB GPU' {
    $plan=Get-ProfilePlan $catalog $models 'gemma12-q8' selected 24576 32 ram ''
    Assert (@($plan.Values | Where-Object {$_.Mode -eq 'serial'}).Count -eq 6) 'Serial model omitted.'
}
Case 'Download preparation includes only selected Gemma weights and shared audio' {
    $files=@(Get-RequiredFiles $root $gemma)
    foreach($id in $gemma){Assert (@($files | Where-Object {$_.path.StartsWith($id+'/')}).Count -eq 1) ('Missing weight: '+$id)}
    Assert (@($files | Where-Object {$_.path -like '9b-*/*' -or $_.path -like '27b-*/*'}).Count -eq 0) 'Unselected Qwen download.'
    Assert (@($files | Where-Object {$_.path -eq 'whisper/large-v3.pt'}).Count -eq 1) 'Whisper omitted.'
    Assert (@($files | Where-Object {$_.path -eq 'pyannote/config.yaml'}).Count -eq 1) 'pyannote omitted.'
}
Write-Output "All $script:Passed Gemma catalogue cases passed (portable PowerShell, no GPU/Windows execution)."
