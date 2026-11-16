# Pure configuration mapping, shared by the bridge and portable regression tests.
function New-WizardServerConfig($InputConfig,$Previous,$Hardware,[string]$State,[string]$Version,$Catalog) {
    $ui=$InputConfig
    $cfg=[ordered]@{}
    if($Previous){foreach($p in $Previous.PSObject.Properties){$cfg[$p.Name]=$p.Value}}
    $cfg.Version=$Version;$cfg.Models=@($ui.selected_models);$cfg.DefaultModel=[string]$ui.default_model
    $cfg.WslRamGiB=[int]$ui.wsl_ram_gib;$cfg.Mode='selected'
    $cfg.ParallelModel=if($ui.memory_mode -eq 'parallel'){[string]$ui.parallel_model}else{''}
    $cfg.AudioCache=[string]$ui.audio_cache;$cfg.GpuIndex=[int]$ui.gpu_index
    $cfg.CacheDirectory=[IO.Path]::GetFullPath($ui.cache_directory)
    $cfg.InstallDirectory=[IO.Path]::GetFullPath($ui.install_directory)
    $cfg.Sources=@($ui.sources -split '\r?\n'|ForEach-Object{$_.Trim()}|Where-Object{$_})
    $cfg.StateDirectory=$State;$cfg.TokenFile=Join-Path $State 'hf.token'
    $cfg.NetworkMode=[string]$ui.network;$cfg.NetworkAddress=if($ui.network -eq 'lan'){[string]$ui.listen_host}else{''}
    $cfg.NetworkRemove=$false;$cfg.Autostart=[bool]$ui.autostart;$cfg.StartAfterInstall=$true
    $cfg.Verify=[bool]$ui.verify;$cfg.VerifyModelFiles=[bool]$ui.verify_models
    $cfg.CleanupModelStaging=[bool]$ui.cleanup_staging;$cfg.ForceModelVerification=($ui.verify_models -and $ui.recheck_models)
    $cfg.AuthEnabled=[bool]$ui.auth_enabled;$cfg.AsrOnDemand=([bool]$ui.asr_on_demand -and $ui.memory_mode -eq 'serial')
    $cfg.DiarizationMode=[string]$ui.diarization_mode;$cfg.RemoteLlmUrl=[string]$ui.remote_llm_url
    $cfg.ServerRole=if($ui.server_role){[string]$ui.server_role}else{'full'};$cfg.AsrModel=if($ui.asr_model){[string]$ui.asr_model}else{'large-v3'};$cfg.Diarization=if($null -ne $ui.diarization){[bool]$ui.diarization}else{$true}
    $cfg.RemoteDiarUrl=[string]$ui.remote_diar_url;$cfg.RemoteDiarTokenFile=Join-Path $State 'remote-diar.token'
    if($ui.server_role -in @('asr','diar') -or $ui.remote_llm_url){$cfg.Models=@();$cfg.DefaultModel='';$cfg.ParallelModel=''}
    $cfg.RemoteLlmTokenFile=Join-Path $State 'remote-llm.token'
    $cfg.CommanderTokenFile=Join-Path $State 'installer-commander.token'
    $cfg.EnabledFields=@($ui.fields);$cfg.QualityModels=$ui.quality_models;$cfg.PromptText=[string]$ui.prompt
    $cfg.AdminRetryId=[guid]::NewGuid().ToString('N')
    $gpu=@($Hardware.Gpus|Where-Object{$_.Index -eq $cfg.GpuIndex})
    if($gpu.Count -ne 1){throw 'Ausgewählte NVIDIA-GPU fehlt.'}
    $cfg.Profiles=Get-ProfilePlan $Catalog $cfg.Models $cfg.DefaultModel $cfg.Mode $gpu[0].VramMiB $cfg.WslRamGiB $cfg.AudioCache $cfg.ParallelModel
    return [pscustomobject]$cfg
}
Export-ModuleMember -Function New-WizardServerConfig
