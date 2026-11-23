$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path $PSScriptRoot -Parent
. (Join-Path $root 'windows/WizardError.ps1')
function Assert($Value,[string]$Why){if(-not $Value){throw $Why}}
$tokens=$null;$errors=$null
$wizard=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Wizard.ps1'),[ref]$tokens,[ref]$errors)
Assert (!$errors) 'Invalid wizard syntax'
$next=$wizard.Find({param($node) $node -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $node.Extent.Text.StartsWith('$script:Next.Add_Click')},$true).Arguments[0].ScriptBlock.GetScriptBlock()
foreach($fn in @('Source-Roots','Build-Config')){
    $definition=$wizard.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $fn},$true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:Cache=[pscustomobject]@{Text='Models'}
$script:Sources=[pscustomobject]@{Lines=@($null,'','  folder  ')}
Assert ((@(Source-Roots) -join '|') -eq 'Models|folder') 'Optional empty sources must be ignored'
$script:Page=3;$script:Previous=$null;$script:CommanderOptions=$null
$script:InputErrors=@{};$script:HfToken=[pscustomobject]@{Text=$null}
$script:Form=$null;$script:problem=$null
function Selected-Models { 'test-model' }
function Show-Page($Index){$script:Page=$Index}
function Show-CommanderOptions {if($script:mode -eq 'open'){$null.Trim()};if($script:mode -ne 'cancel'){[pscustomobject]@{EnabledFields=@('befund')}}}
function Show-WizardProblem($Failure,$Step,$Heading,$Owner,$Secrets,[switch]$BeforeStart) {
    $script:problem=New-WizardDiagnostic $Failure $Step '1.8.3' $Secrets
    $script:inputPage=$Failure.Exception.Data['WizardPage']
    $script:field=$Failure.Exception.Data['WizardControl']
    Assert $BeforeStart 'The installer engine should not have started'
}
$script:mode='open'
& $next
Assert ($script:problem.Details -match 'Commander-Einstellungen öffnen' -and $script:problem.Details -match 'InvokeMethodOnNull' -and $script:problem.Details -match 'test_wizard_failures.ps1 \(Zeile \d+\)') 'Original opening failure, file and line must be preserved'
$script:problem=$null;$script:mode='cancel'
& $next
Assert ($null -eq $script:problem -and $script:Page -eq 3) 'Cancelling Commander must return silently'
$script:mode='apply'
& $next
Assert ($script:inputPage -eq 1 -and $script:field -eq $script:HfToken -and $script:problem.Message -match 'Hugging-Face-Token eingeben') 'Missing token must focus the model page field'
function Build-Config { @{Models=@('test-model')} }
function Prepare-Summary { throw 'synthetic summary failure' }
& $next
Assert ($script:problem.Details -match 'Zusammenfassung anzeigen') 'Summary failure misattributed'
try { throw 'synthetic_long and synthetic' } catch {
    $r=New-WizardDiagnostic $_ 'Test' '1.8.3' @('synthetic','synthetic_long',$null)
    Assert ($r.Details -notmatch 'synthetic|_long' -and $r.Message -notmatch 'synthetic|_long') 'Support report leaked a test credential'
}
function Prepare-Summary {}
& $next
Assert ($script:Page -eq 4) 'Successful flow must reach the summary'
Write-Output 'PASS actual Next handler: open, cancel, input focus, summary, retry, safe report and optional sources'

# Exercise the actual post-OK path, including the private file write and its error boundary.
$commander=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/CommanderOptions.ps1'),[ref]$tokens,[ref]$errors)
Assert (!$errors) 'Invalid Commander syntax'
$postModal=$commander.Find({param($n) $n -is [Management.Automation.Language.TryStatementAst] -and $n.Body.Extent.Text.Contains('$dialog.ShowDialog')},$true)
$finishDialog=[scriptblock]::Create($postModal.Extent.Text)
$script:State=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
$script:HfToken.Text='synthetic-hf'
$remoteSecret=[pscustomobject]@{Text='synthetic-remote'}
$remoteSecretPath=Join-Path $script:State 'remote-llm.token'
$dialog=[pscustomobject]@{}
$dialog | Add-Member ScriptMethod ShowDialog { 'OK' }
$dialog | Add-Member ScriptMethod Dispose {}
$fieldErrors=[pscustomobject]@{}
$fieldErrors | Add-Member ScriptMethod Dispose {}
$gradeControls=@{}
foreach($name in @('basis','gruendlich','sehr_gruendlich')){$gradeControls[$name]=[pscustomobject]@{SelectedItem=$null}}
$fields=@{befund='Befund'};$fieldControls=@{befund=[pscustomobject]@{Checked=$true}}
$auth=$cold=[pscustomobject]@{Checked=$true}
$diarKeys=@('serial');$diarMode=[pscustomobject]@{SelectedIndex=0}
$remote=[pscustomobject]@{Text=$null};$prompt=[pscustomobject]@{Text='synthetic prompt'}
function Set-PrivateFile { throw 'synthetic-remote write failure' }
try {
    $script:problem=$null
    $result=& $finishDialog
    Assert ($null -eq $result -and $script:problem.Details.Contains('Commander-Einstellungen übernehmen')) 'Post-OK failure misattributed'
    Assert (!$script:problem.Details.Contains($remoteSecret.Text)) 'Remote token leaked in actual save handler'
    function Set-PrivateFile {}
    $result=& $finishDialog
    Assert ($result.RemoteLlmUrl -ceq '' -and $result.EnabledFields -contains 'befund') 'Empty remote URL or normal Commander acceptance failed'
} finally {
    if([IO.File]::Exists($remoteSecretPath)){[IO.File]::Delete($remoteSecretPath)}
    if([IO.Directory]::Exists($script:State)){[IO.Directory]::Delete($script:State)}
}
Write-Output 'PASS actual Commander acceptance, private-file failure and optional remote value'
