# Keep the support text identical in the clipboard and installation.log.
function New-WizardDiagnostic($Failure, [string]$Step, [string]$Version, [string[]]$Secrets) {
    $message = [string]$Failure.Exception.Message
    $id = [string]$Failure.FullyQualifiedErrorId
    # PowerShell uses the thrown text itself as the ID for "throw 'text'".
    if ($id -notmatch '^[A-Za-z][A-Za-z0-9_.+,\-]{0,180}$') { $id = $Failure.Exception.GetType().Name }
    $where = $Failure.InvocationInfo
    $file = [IO.Path]::GetFileName([string]$where.ScriptName)
    $location = if ($file) { "$file (Zeile $($where.ScriptLineNumber))" } else { 'Keine Skriptzeile verfügbar' }
    $detail = "kienzledoku Windows-Installer $Version`r`nSchritt: $Step`r`nFehlermeldung: $message`r`nFehlerkennung: $id`r`nAufrufstelle: $location"
    $trace = [string]$Failure.ScriptStackTrace
    foreach ($secret in @($Secrets | Where-Object { $_ } | Sort-Object Length -Descending)) {
        $detail = $detail.Replace($secret,'[ausgelassen]')
        $message = $message.Replace($secret,'[ausgelassen]')
        $trace = $trace.Replace($secret,'[ausgelassen]')
    }
    [pscustomobject]@{ Message=$message; Details=$detail; StackTrace=$trace }
}

function Stop-WizardInput([string]$Message, [int]$Page, $Control) {
    $exception = [ArgumentException]::new($Message)
    $exception.Data['WizardPage'] = $Page
    $exception.Data['WizardControl'] = $Control
    throw $exception
}

function Show-WizardProblem($Failure, [string]$Step, [string]$Heading, $Owner, [string[]]$Secrets, [switch]$BeforeStart) {
    $report = New-WizardDiagnostic $Failure $Step $script:InstallerVersion $Secrets
    try {
        [IO.Directory]::CreateDirectory($script:State) | Out-Null
        Add-Content -LiteralPath (Join-Path $script:State 'installation.log') -Value ("[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date),($report.Details + "`r`n" + $report.StackTrace)) -Encoding UTF8
    } catch { Write-Verbose 'Das Installationsprotokoll konnte nicht geschrieben werden.' }
    $inputError = $Failure.Exception.Data.Contains('WizardPage')
    $form = New-Object Windows.Forms.Form
    try {
        $form.Text = 'kienzledoku Server Installer'
        $form.Font = $Owner.Font
        $form.StartPosition = 'CenterParent'
        $form.AutoScaleMode = 'Dpi'
        $form.ClientSize = New-Object Drawing.Size(590,300)
        $form.MinimizeBox = $false
        $form.MaximizeBox = $false
        $form.FormBorderStyle = 'FixedDialog'
        if ($inputError) { $Heading = 'Bitte prüfen Sie die markierte Eingabe.' }
        $title = Label $form $Heading 18 14 554 44
        $title.Font = New-Object Drawing.Font($form.Font,[Drawing.FontStyle]::Bold)
        $hint = $report.Message
        if (!$inputError) {
            $hint = 'Für eine Fehlermeldung können Sie die technischen Details kopieren.'
            if ($BeforeStart) { $hint = "Die Serverinstallation hat noch nicht begonnen. $hint" }
        }
        $null = Label $form $hint 18 61 554 47
        $details = TextBox $form $report.Details 18 111 554 116 $true
        $details.ReadOnly = $true
        $details.ScrollBars = 'Vertical'
        $copy = Button $form 'Fehlerdetails kopieren' 18 246 210
        $close = Button $form 'Schließen' 444 246 128
        $copy.Add_Click({
            try {
                [Windows.Forms.Clipboard]::SetText($details.Text)
                $copy.Text = 'Kopiert'
            } catch {
                $null = $details.Focus()
                $details.SelectAll()
                $copy.Text = 'Mit Strg+C kopieren'
            }
        })
        $close.DialogResult = 'OK'
        $form.AcceptButton = $close
        $form.CancelButton = $close
        $null = $form.ShowDialog($Owner)
    } finally { $form.Dispose() }
    if ($inputError) {
        Show-Page $Failure.Exception.Data['WizardPage']
        $control = $Failure.Exception.Data['WizardControl']
        if ($control) {
            $script:InputErrors.SetError($control,$report.Message)
            $null = $control.Focus()
        }
    }
}
