$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Import-Module (Join-Path $root 'server-windows/windows/Core.psm1') -Force
Import-Module (Join-Path $root 'windows/WizardConfig.psm1') -Force
function Assert($ok,$message){if(!$ok){throw $message}}
$ui=[pscustomobject]@{selected_models=@('qwen4-q4','gemma12-q8','27b-q4');default_model='gemma12-q8';wsl_ram_gib=28;memory_mode='parallel';parallel_model='gemma12-q8';audio_cache='ram';gpu_index=0;cache_directory='/tmp/models';install_directory='/tmp/server';sources="/tmp/old`n/tmp/extra";network='lan';listen_host='10.0.83.50';autostart=$true;verify=$true;verify_models=$true;cleanup_staging=$false;recheck_models=$false;auth_enabled=$false;asr_on_demand=$true;diarization_mode='with_asr';remote_llm_url='http://other:8185';fields=@('anamnese','befund','ekg','sonografie','therapie','prozedere','notiz');quality_models=[pscustomobject]@{basis='qwen4-q4';gruendlich='gemma12-q8';sehr_gruendlich='27b-q4'};prompt='Äußere Befunde: Übelkeit, Größe – vollständig dokumentieren.'}
$hw=[pscustomobject]@{Gpus=@([pscustomobject]@{Index=0;VramMiB=24576})}
$old=[pscustomobject]@{AdditionalExistingPreference='retain';AuthEnabled=$true}
$cfg=New-WizardServerConfig $ui $old $hw '/tmp/state' '1.7.6' (Get-Catalog (Join-Path $root 'server-windows'))
Assert ($cfg.AdditionalExistingPreference -eq 'retain') 'Existing config lost'
Assert ($cfg.AuthEnabled -eq $false) 'Optional auth not disabled'
Assert ($cfg.Profiles['gemma12-q8'].Mode -eq 'parallel') 'Resident choice lost'
Assert ($cfg.Profiles['qwen4-q4'].Mode -eq 'serial') 'Other models not serial'
Assert ($cfg.AsrOnDemand -eq $false) 'Cold mode must only apply to serial ASR'
Assert ($cfg.QualityModels.gruendlich -eq 'gemma12-q8') 'Quality assignment lost'
Assert ($cfg.PromptText -eq 'Äußere Befunde: Übelkeit, Größe – vollständig dokumentieren.') 'Prompt lost'
Assert ($cfg.DiarizationMode -eq 'with_asr') 'Diarization mode lost'
Assert ($cfg.Sources.Count -eq 2) 'Source paths lost'
Assert ($cfg.RemoteLlmUrl -eq 'http://other:8185') 'Remote Commander lost'
$ui.memory_mode='serial';$ui.diarization_mode='serial'
$cfg=New-WizardServerConfig $ui $old $hw '/tmp/state' '1.7.6' (Get-Catalog (Join-Path $root 'server-windows'))
Assert ($cfg.AsrOnDemand -and !$cfg.ParallelModel) 'Strict serial mode wrong'
foreach($p in $cfg.Profiles.Values){Assert ($p.Mode -eq 'serial') 'Serial model accidentally resident'}
foreach($file in @('Setup.ps1','WizardBridge.ps1','WizardConfig.psm1','UninstallUI.ps1','SetupUninstall.ps1')){
 $tokens=$null;$errors=$null
 $null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root ('windows/'+$file)),[ref]$tokens,[ref]$errors)
 Assert ($errors.Count -eq 0) ($file+': '+($errors -join ', '))
}
Write-Output 'PASS: shared Windows wizard config, upgrade preservation and PowerShell syntax'

$script:SeenDownload=$null
Set-DownloadProgressHandler {param($name,$current,$total) $script:SeenDownload=@($name,$current,$total)}
$inputStream=New-Object IO.MemoryStream(,[byte[]](1,2,3,4,5))
$outputStream=New-Object IO.MemoryStream
Copy-DownloadStream $inputStream $outputStream 'synthetic.gguf' 10 15
Assert ($outputStream.Length -eq 5) 'Download stream truncated'
Assert ($script:SeenDownload[1] -eq 15 -and $script:SeenDownload[2] -eq 15) 'Download progress did not preserve resumed offset'
$inputStream.Dispose();$outputStream.Dispose()
Write-Output 'PASS: resumed download byte progress'

$promptRoundTrip=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-prompt-'+[guid]::NewGuid().ToString('N')+'.json')
try {
 Write-Json $promptRoundTrip $cfg
 $decoded=Read-Json $promptRoundTrip
 Assert ($decoded.PromptText -ceq $ui.prompt) 'Prompt changed in UTF-8 config roundtrip'
 $raw=[IO.File]::ReadAllBytes($promptRoundTrip)
 $strictUtf8=New-Object Text.UTF8Encoding($false,$true)
 Assert ($strictUtf8.GetString($raw).Contains('Übelkeit')) 'Saved prompt is not intact UTF-8'
} finally {Remove-Item -LiteralPath $promptRoundTrip -ErrorAction SilentlyContinue}
Write-Output 'PASS: custom prompt umlauts through actual Windows config writer/reader'
