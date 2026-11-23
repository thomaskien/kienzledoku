# Commander-owned document fields, model assignments and prompt.
function Show-CommanderOptions($Models, $Previous) {
    $dialog=New-Object Windows.Forms.Form
    $dialog.Text='Commander einrichten';$dialog.ClientSize=New-Object Drawing.Size(850,875)
    $dialog.StartPosition='CenterParent';$dialog.Font=New-Object Drawing.Font('Segoe UI',10)
    $dialog.AutoScaleMode=[Windows.Forms.AutoScaleMode]::Dpi
    $dialog.AutoScroll=$true
    $dialog.Add_Shown({$limit=[Windows.Forms.Screen]::FromControl($dialog).WorkingArea.Height-60;if($dialog.Height -gt $limit){$dialog.Height=$limit}})
    $fields=[ordered]@{anamnese='Anamnese';befund='Befund';ekg='EKG';sonografie='Sonografie';therapie='Therapie';prozedere='Prozedere';notiz='Notiz (NOT)'}
    $selected=@('anamnese','befund','therapie','prozedere')
    if($Previous -and $Previous.PSObject.Properties['EnabledFields']){$selected=@($Previous.EnabledFields)}
    $null=Label $dialog 'Welche Dokumentationsfelder sollen verwendet werden?' 20 12 800
    $fieldControls=@{};$i=0
    foreach($key in $fields.Keys){
        $c=New-Object Windows.Forms.CheckBox;$c.Text=$fields[$key];$c.Checked=$key -in $selected
        $c.Location=New-Object Drawing.Point((20+($i%4)*200),(45+[math]::Floor($i/4)*30));$c.Size=New-Object Drawing.Size(195,28)
        $dialog.Controls.Add($c);$fieldControls[$key]=$c;$i++
    }
    $null=Label $dialog 'Aktives Modell je Stufe (weitere installierte Modelle bleiben verfügbar)' 20 112 800
    $gradeControls=@{};$i=0
    foreach($grade in @('basis','gruendlich','sehr_gruendlich')){
        $title=@{basis='Basis';gruendlich='Gründlich';sehr_gruendlich='Sehr gründlich'}[$grade]
        $null=Label $dialog $title 20 (148+$i*36) 165
        $combo=Combo $dialog 190 (145+$i*36) 635
        foreach($id in $Models){$m=$script:Catalog.PSObject.Properties[$id].Value;if($m.grade -eq $grade){$null=$combo.Items.Add($id)}}
        if($combo.Items.Count){$combo.SelectedIndex=0}
        $preferred=@{basis='qwen4-q4';gruendlich='gemma12-q8';sehr_gruendlich='27b-q4'}[$grade]
        if($combo.Items.Contains($preferred)){$combo.SelectedItem=$preferred}
        if($Previous -and $Previous.PSObject.Properties['QualityModels'] -and $Previous.QualityModels){
            $prop=$Previous.QualityModels.PSObject.Properties[$grade]
            if($prop -and $combo.Items.Contains([string]$prop.Value)){$combo.SelectedItem=[string]$prop.Value}
        }
        $combo.Enabled=$combo.Items.Count -gt 1;$gradeControls[$grade]=$combo;$i++
    }
    $auth=Check $dialog 'Commander-Zugang mit Token schützen (standardmäßig aus)' 260 $false
    if($Previous -and $Previous.PSObject.Properties['AuthEnabled']){$auth.Checked=[bool]$Previous.AuthEnabled}
    $cold=Check $dialog 'Whisper erst beim ersten Audioblock laden; nach LLM nicht erneut vorladen' 296 $true
    if($Previous -and $Previous.PSObject.Properties['AsrOnDemand']){$cold.Checked=[bool]$Previous.AsrOnDemand}
    $null=Label $dialog 'Sprechertrennung: Speichernutzung' 20 335 350
    $diarMode=Combo $dialog 380 332 445
    $diarKeys=@('resident','with_asr','serial')
    foreach($label in @('Immer geladen','Zusammen mit Whisper','Seriell – nach Whisper, vor dem LLM')){$null=$diarMode.Items.Add($label)}
    $diarMode.SelectedIndex=2
    if($Previous -and $Previous.PSObject.Properties['DiarizationMode']){
        $index=[array]::IndexOf($diarKeys,[string]$Previous.DiarizationMode)
        if($index -ge 0){$diarMode.SelectedIndex=$index}
    }elseif($Previous -and $Previous.PSObject.Properties['ParallelModel'] -and $Previous.ParallelModel){$diarMode.SelectedIndex=0}
    $null=Label $dialog 'Immer geladen benötigt auch neben dem LLM GPU-Speicher; seriell gibt ihn frei.' 20 370 805
    $null=Label $dialog 'Anderer Commander für LLM (optional, http(s)://Host:Port)' 20 410 790
    $remote=TextBox $dialog '' 20 438 805
    if($Previous -and $Previous.PSObject.Properties['RemoteLlmUrl']){$remote.Text=[string]$Previous.RemoteLlmUrl}
    $null=Label $dialog 'Token für den anderen LLM-Commander (optional)' 20 478 790
    $remoteSecret=TextBox $dialog '' 20 506 805;$remoteSecret.UseSystemPasswordChar=$true
    $remoteSecretPath=Join-Path $script:State 'remote-llm.token'
    if(Test-Path -LiteralPath $remoteSecretPath){$remoteSecret.Text=([string](Get-Content -LiteralPath $remoteSecretPath -Raw)).Trim()}
    # A saved credential must never silently follow an edited remote host.
    $remote.Add_TextChanged({$remoteSecret.Clear()})
    $null=Label $dialog 'Aktiver Prompt — hier anpassbar' 20 570 500
    $prompt=TextBox $dialog '' 20 604 805 200 $true;$prompt.ScrollBars='Vertical';$prompt.AcceptsReturn=$true
    $standard=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'prompt_documentation.txt') -Raw -Encoding UTF8
    $prompt.Text=$standard
    if($Previous -and $Previous.PSObject.Properties['PromptText'] -and $Previous.PromptText){$prompt.Text=[string]$Previous.PromptText}
    $reset=Button $dialog 'Prompt auf Standard' 600 566 225
    $reset.Add_Click({$prompt.Text=$standard})
    $ok=Button $dialog 'Übernehmen' 655 826 170
    $cancel=Button $dialog 'Abbrechen' 470 826 170;$cancel.DialogResult='Cancel'
    $fieldErrors=New-Object Windows.Forms.ErrorProvider
    $fieldErrors.ContainerControl=$dialog
    $fieldErrors.BlinkStyle='NeverBlink'
    function Select-InvalidField($Control,[string]$Message) {
        $fieldErrors.SetError($Control,$Message)
        $dialog.ScrollControlIntoView($Control)
        $null=$Control.Focus()
        [Windows.Forms.MessageBox]::Show($dialog,$Message,'Eingabe prüfen','OK','Warning') | Out-Null
    }
    $ok.Add_Click({
        try {
            $fieldErrors.Clear()
            if(-not ([string]$prompt.Text).Trim()){Select-InvalidField $prompt 'Der Prompt darf nicht leer sein.';return}
            if(-not @($fieldControls.Keys|Where-Object{$fieldControls[$_].Checked}).Count){Select-InvalidField $fieldControls['anamnese'] 'Mindestens ein Dokumentationsfeld auswählen.';return}
            if(([string]$remote.Text).Trim()){
                $u=$null
                if(-not [Uri]::TryCreate(([string]$remote.Text).Trim(),[UriKind]::Absolute,[ref]$u) -or $u.Scheme -notin @('http','https') -or $u.UserInfo -or $u.Query -or $u.Fragment -or $u.AbsolutePath -ne '/'){
                    Select-InvalidField $remote 'Vollständige Commander-Adresse ohne Zugangsdaten oder Pfad eingeben.';return
                }
            }
            if($remoteSecret.Text -match '\s' -or $remoteSecret.Text.Length -gt 4096){Select-InvalidField $remoteSecret 'Der Token darf höchstens 4096 Zeichen und keine Leerzeichen enthalten.';return}
            $dialog.DialogResult='OK';$dialog.Close()
        } catch {
            Show-WizardProblem $_ 'Commander-Einstellungen übernehmen' 'Die Commander-Einstellungen konnten nicht übernommen werden.' $dialog @($script:HfToken.Text,$remoteSecret.Text) -BeforeStart
        }
    })
    try{
        if($dialog.ShowDialog($script:Form) -ne 'OK'){return $null}
        try {
            $mapping=[ordered]@{}
            foreach($grade in @('basis','gruendlich','sehr_gruendlich')){if($gradeControls[$grade].SelectedItem){$mapping[$grade]=[string]$gradeControls[$grade].SelectedItem}}
            [IO.Directory]::CreateDirectory($script:State)|Out-Null
            [IO.File]::WriteAllText($remoteSecretPath,$remoteSecret.Text,(New-Object Text.UTF8Encoding($false)));Set-PrivateFile $remoteSecretPath
            return [pscustomobject]@{RemoteLlmTokenFile=$remoteSecretPath;EnabledFields=@($fields.Keys|Where-Object{$fieldControls[$_].Checked});QualityModels=$mapping;AuthEnabled=$auth.Checked;AsrOnDemand=$cold.Checked;DiarizationMode=$diarKeys[$diarMode.SelectedIndex];RemoteLlmUrl=([string]$remote.Text).Trim();PromptText=$prompt.Text}
        } catch {
            Show-WizardProblem $_ 'Commander-Einstellungen übernehmen' 'Die Commander-Einstellungen konnten nicht übernommen werden.' $script:Form @($script:HfToken.Text,$remoteSecret.Text) -BeforeStart
            return $null
        }
    }finally{$fieldErrors.Dispose();$dialog.Dispose()}
}
