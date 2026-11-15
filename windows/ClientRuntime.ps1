# Local CPU VAD only: no configuration, tokens, microphone or server requests.
function Get-ClientVadResult([string]$ClientDirectory, [int]$TimeoutMilliseconds=120000) {
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=Join-Path $ClientDirectory 'runtime/python.exe'
    $info.Arguments='-B -X utf8 "'+(Join-Path $ClientDirectory 'kienzledoku_vad.py')+'"'
    $info.UseShellExecute=$false;$info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $info.StandardOutputEncoding=New-Object Text.UTF8Encoding($false)
    $info.StandardErrorEncoding=New-Object Text.UTF8Encoding($false)
    $process=[Diagnostics.Process]::Start($info)
    try {
        # Drain both streams concurrently; warnings on stderr need not be errors.
        $stdout=$process.StandardOutput.ReadToEndAsync()
        $stderr=$process.StandardError.ReadToEndAsync()
        if(!$process.WaitForExit($TimeoutMilliseconds)){
            $process.Kill();$process.WaitForExit()
            throw 'Der lokale VAD-Selbsttest antwortet nicht. Client-Installation prüfen.'
        }
        $details=($stderr.Result+"`n"+$stdout.Result).Trim()
        if($details.Length -gt 6000){$details=$details.Substring($details.Length-6000)}
        return [pscustomobject]@{ExitCode=$process.ExitCode;Details=$details}
    } finally {$process.Dispose()}
}

function Assert-ClientVad([string]$ClientDirectory) {
    $result=Get-ClientVadResult $ClientDirectory
    if($result.ExitCode -ne 0){
        throw "Die lokale VAD-Laufzeit hat ihren Selbsttest nicht bestanden (Exitcode $($result.ExitCode)).`n$($result.Details)"
    }
}

function Get-MissingClientCppLibraries([string]$ClientDirectory) {
    # Imports of the pinned ONNX Runtime 1.19.2 x64 binary. Python itself ships
    # vcruntime140*.dll, but not the two required MSVCP libraries.
    foreach($name in @('msvcp140.dll','msvcp140_1.dll','vcruntime140.dll','vcruntime140_1.dll')){
        if(!(Test-Path -LiteralPath (Join-Path $ClientDirectory ('runtime/'+$name))) -and
           !(Test-Path -LiteralPath (Join-Path $env:SystemRoot ('System32/'+$name)))){$name}
    }
}

function Install-ClientCppRuntime([scriptblock]$Progress) {
    $directory=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-vcruntime-'+[guid]::NewGuid().ToString('N'))
    $null=[IO.Directory]::CreateDirectory($directory)
    try {
        & $Progress 'Microsoft Visual C++ x64 fehlt. Laufzeit von Microsoft herunterladen …'
        $installer=Join-Path $directory 'vc_redist.x64.exe'
        [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest 'https://aka.ms/vc14/vc_redist.x64.exe' -UseBasicParsing -OutFile $installer
        $signature=Get-AuthenticodeSignature -LiteralPath $installer
        if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|,\s*)CN=Microsoft Corporation(,|$)'){
            throw 'Die Microsoft-Signatur der Visual-C++-Laufzeit ist ungültig.'
        }
        & $Progress 'Microsoft Visual C++ x64 einrichten. Bitte die Windows-Administratorabfrage bestätigen.'
        $process=Start-Process -FilePath $installer -ArgumentList '/install /passive /norestart' -Verb RunAs -PassThru
        try {
            # Retain the native handle before waiting (Windows PowerShell 5.1).
            $null=$process.Handle
            $process.WaitForExit()
            $code=$process.ExitCode
        } finally {$process.Dispose()}
        if($null -eq $code){throw 'Microsoft Visual C++ hat keinen auswertbaren Abschlusscode geliefert.'}
        if($code -eq 3010){throw 'Microsoft Visual C++ wurde eingerichtet. Windows bitte neu starten und den Kienzledoku-Installer erneut öffnen.'}
        # 1638: a newer redistributable is installed. The real VAD test still decides.
        if($code -notin @(0,1638)){throw "Microsoft Visual C++ konnte nicht eingerichtet werden (Exitcode $code)."}
    } finally {Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue}
}

function Initialize-ClientRuntime([string]$ClientDirectory, [scriptblock]$Progress={param($Message) Write-Host $Message}) {
    & $Progress 'Lokale Sprachaktivitätserkennung und Microsoft-C++-Laufzeit prüfen …'
    if(@(Get-MissingClientCppLibraries $ClientDirectory).Count){Install-ClientCppRuntime $Progress}
    & $Progress 'Lokale Sprachaktivitätserkennung testen …'
    Assert-ClientVad $ClientDirectory
}
