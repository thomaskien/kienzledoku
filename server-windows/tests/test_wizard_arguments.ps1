param([string]$WizardPath='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path -Parent $PSScriptRoot
if(-not $WizardPath){$WizardPath=Join-Path $root 'windows/Wizard.ps1'}
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
$tokens=$null;$errors=$null
$wizard=[Management.Automation.Language.Parser]::ParseFile($WizardPath,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors | Out-String)}
$helpers=@('Label','TextBox','Button','Check','Radio','Combo')
$script:Captured=New-Object 'Collections.Generic.List[object]'
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}

# Retain the real helper parameter declarations and defaults. Replace only the
# Forms construction: evaluating the actual calls must exercise parameter binding,
# which a successful ParseFile alone does not check (smart quotes can split text).
foreach($helper in $helpers){
    $definition=$wizard.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $helper},$true)
    if(-not $definition){throw ('Missing wizard helper: '+$helper)}
    $parameters=($definition.Parameters | ForEach-Object {$_.Extent.Text}) -join ','
    $body=@'
if($args.Count){throw ('Unexpected extra control arguments: '+($args -join ', '))}
$values=@{}
foreach($key in $MyInvocation.MyCommand.Parameters.Keys){$values[$key]=Get-Variable -Name $key -ValueOnly}
$entry=[pscustomobject]@{Helper=$MyInvocation.MyCommand.Name;Values=$values}
$script:Captured.Add($entry)
return $entry
'@
    Set-Item -Path ('Function:'+ $helper) -Value ([scriptblock]::Create('param('+$parameters+")`n"+$body))
}
function Invoke-ControlCall($Call){
    try{& ([scriptblock]::Create($Call.Extent.Text)) | Out-Null}
    catch{throw ('Wizard control argument error, line '+$Call.Extent.StartLineNumber+': '+$_.Exception.Message)}
}
$calls=@($wizard.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -in $helpers},$true))
$catalog=Get-Catalog $root
$p=[pscustomobject]@{Role='page'};$header=[pscustomobject]@{Role='header'};$footer=[pscustomobject]@{Role='footer'}
$script:InstallerVersion=Get-InstallerVersion
$cacheDefault='Z:\Modellarchiv\models';$installDefault='C:\Users\Test\kienzledoku Server'
$m=$catalog.PSObject.Properties['9b-q4'].Value;$checked=$true;$y=59
$savedModelOptions=Get-ModelOptions $null
Case 'All actual wizard control calls bind their original typed parameters without extra arguments' {
    Assert ($calls.Count -ge 60) 'Wizard control calls were not discovered.'
    foreach($call in $calls){Invoke-ControlCall $call}
    Assert ($script:Captured.Count -eq $calls.Count) 'Some control calls were skipped.'
    foreach($entry in $script:Captured){
        foreach($key in @('X','Y','Width','Height')){
            if($entry.Values.ContainsKey($key)){Assert ($entry.Values[$key] -is [int] -and $entry.Values[$key] -ge 0) ('Invalid geometry: '+$entry.Helper+'/'+$key)}
        }
    }
}
Case 'Archive inventory guidance stays one text argument at the intended screen position' {
    $entries=@($script:Captured | Where-Object {$_.Values.ContainsKey('Text') -and $_.Values['Text'].StartsWith('Automatisch wird')})
    Assert ($entries.Count -eq 1) 'Archive guidance missing or duplicated.'
    $values=$entries[0].Values
    Assert ($values.Text.Contains('Archiv prüfen') -and $values.Text.Contains('WSL-Modelle')) 'Archive guidance text was split or truncated.'
    Assert ($values.X -eq 24 -and $values.Y -eq 505 -and $values.Width -eq 860 -and $values.Height -eq 48) 'Archive guidance geometry shifted.'
}
Case 'Actual model checkbox and description calls bind for every catalogue model' {
    $modelCalls=@($calls | Where-Object {$_.Extent.Text.Contains('$m.label') -or $_.Extent.Text.Contains('$m.description')})
    Assert ($modelCalls.Count -eq 2) 'Dynamic model controls were not discovered.'
    foreach($property in $catalog.PSObject.Properties){
        $m=$property.Value;$checked=$property.Name -eq '9b-q4'
        foreach($call in $modelCalls){Invoke-ControlCall $call}
        $box=$script:Captured[$script:Captured.Count-2];$description=$script:Captured[$script:Captured.Count-1]
        Assert ($box.Values.Text.StartsWith($m.label) -and $box.Values.Checked -eq $checked) ('Model checkbox changed: '+$property.Name)
        Assert ($description.Values.Text -ceq $m.description) ('Model description changed: '+$property.Name)
        $y+=87
    }
}
Case 'New checkbox initialization binds null, legacy and explicit saved options with correct booleans' {
    $optionCalls=@($calls | Where-Object {$_.Extent.Text.Contains('$savedModelOptions.')})
    Assert ($optionCalls.Count -eq 2) 'Saved option controls were not discovered.'
    foreach($config in @($null,[pscustomobject]@{Version='1.9'},[pscustomobject]@{VerifyModelFiles=$false;CleanupModelStaging=$true} )){
        $savedModelOptions=Get-ModelOptions $config
        foreach($call in $optionCalls){Invoke-ControlCall $call}
        $verify=$script:Captured[$script:Captured.Count-2];$cleanup=$script:Captured[$script:Captured.Count-1]
        Assert ($verify.Values.Checked -is [bool] -and $verify.Values.Checked -eq $savedModelOptions.VerifyModelFiles) 'File verification choice changed.'
        Assert ($cleanup.Values.Checked -is [bool] -and $cleanup.Values.Checked -eq $savedModelOptions.CleanupModelStaging) 'Staging cleanup choice changed.'
    }
}
Write-Output "All $script:Passed wizard argument cases passed ($($calls.Count) actual control call sites; portable PowerShell, Forms construction simulated)."
