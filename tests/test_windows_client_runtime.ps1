# Portable process/installer regression. Native Microsoft installation is mocked.
$ErrorActionPreference='Stop'
$repository=Split-Path -Parent $PSScriptRoot
. (Join-Path $repository 'windows/ClientRuntime.ps1')
function Assert($Condition,[string]$Message){if(!$Condition){throw $Message}}
$testDirectory=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-client-runtime-test-'+[guid]::NewGuid().ToString('N'))
$oldSystemRoot=$env:SystemRoot
try {
    $client=Join-Path $testDirectory 'client with spaces'
    $null=[IO.Directory]::CreateDirectory((Join-Path $client 'runtime'))
    $env:SystemRoot=Join-Path $testDirectory 'synthetic-windows'
    $null=[IO.Directory]::CreateDirectory((Join-Path $env:SystemRoot 'System32'))
    foreach($name in @('vcruntime140.dll','vcruntime140_1.dll')){
        [IO.File]::WriteAllText((Join-Path $client ('runtime/'+$name)),'synthetic')
    }
    $missing=@(Get-MissingClientCppLibraries $client)
    Assert ($missing.Count -eq 2 -and $missing -contains 'msvcp140.dll' -and $missing -contains 'msvcp140_1.dll') 'MSVCP dependencies were not detected'
    foreach($name in $missing){[IO.File]::WriteAllText((Join-Path $env:SystemRoot ('System32/'+$name)),'synthetic')}
    Assert (@(Get-MissingClientCppLibraries $client).Count -eq 0) 'Existing C++ runtime not recognised'

    # Run real child processes on the cross-build host. Windows native VAD is a
    # separate platform test, not simulated by these fixtures.
    if([Environment]::OSVersion.Platform -eq [PlatformID]::Unix){
        $python=(Get-Command python3).Source
        $null=New-Item -ItemType SymbolicLink -Path (Join-Path $client 'runtime/python.exe') -Target $python
        $scriptFile=Join-Path $client 'kienzledoku_vad.py'
        [IO.File]::WriteAllText($scriptFile,"import sys`nprint('synthetic warning: Größe', file=sys.stderr)`nprint('VAD OK')",(New-Object Text.UTF8Encoding($false)))
        $result=Get-ClientVadResult $client
        Assert ($result.ExitCode -eq 0 -and $result.Details.Contains('Größe')) 'Warning/UTF-8 capture failed'
        Assert-ClientVad $client
        [IO.File]::WriteAllText($scriptFile,"raise ImportError('DLL load failed: synthetic MSVCP140_1.dll')")
        $failure='';try{Assert-ClientVad $client}catch{$failure=$_.Exception.Message}
        Assert ($failure.Contains('Exitcode 1') -and $failure.Contains('ImportError: DLL load failed') -and $failure.Contains('MSVCP140_1.dll')) 'Original Python failure was hidden'
        [IO.File]::WriteAllText($scriptFile,"import time`ntime.sleep(10)")
        $failure='';try{Get-ClientVadResult $client 100}catch{$failure=$_.Exception.Message}
        Assert ($failure.Contains('antwortet nicht')) 'Stuck VAD test was not bounded'
        Write-Output 'PASS: actual child exit code, stderr warning, UTF-8, exception details, timeout and paths with spaces'
    }

    $script:SignatureStatus='Valid';$script:Signer='CN=Microsoft Corporation, O=Microsoft Corporation'
    $script:Started=0;$script:ExitCode=0;$script:Downloaded=$null
    function Invoke-WebRequest {
        param($Uri,[switch]$UseBasicParsing,$OutFile)
        Assert ($Uri -eq 'https://aka.ms/vc14/vc_redist.x64.exe') 'Unexpected download source'
        $script:Downloaded=$OutFile
        [IO.File]::WriteAllText($OutFile,'synthetic redistributable, never executed')
    }
    function Get-AuthenticodeSignature {
        param($LiteralPath)
        Assert ($LiteralPath -eq $script:Downloaded) 'Signature checked for a different file'
        return [pscustomobject]@{Status=$script:SignatureStatus;SignerCertificate=[pscustomobject]@{Subject=$script:Signer}}
    }
    function Start-Process {
        param($FilePath,$ArgumentList,$Verb,[switch]$Wait,[switch]$PassThru)
        Assert ($script:SignatureStatus -eq 'Valid' -and $script:Signer -like 'CN=Microsoft Corporation,*') 'Untrusted executable started'
        Assert ($FilePath -eq $script:Downloaded -and $Verb -eq 'RunAs' -and $ArgumentList -eq '/install /passive /norestart' -and !$Wait -and $PassThru) 'Unsafe or incorrect runtime invocation'
        $script:Started++
        $fake=[pscustomobject]@{ExitCode=$null;Handle=42;WantedExitCode=$script:ExitCode}
        $fake|Add-Member ScriptMethod WaitForExit {$this.ExitCode=$this.WantedExitCode}
        $fake|Add-Member ScriptMethod Dispose {}
        return $fake
    }
    $script:Messages=@()
    $progress={param($Message) $script:Messages+=,$Message}
    Install-ClientCppRuntime $progress
    Assert ($script:Started -eq 1 -and !(Test-Path (Split-Path $script:Downloaded -Parent))) 'Installer not cleaned up'
    Assert (($script:Messages -join ' ').Contains('Administratorabfrage')) 'Elevation was not explained'
    foreach($case in @('bad-signature','wrong-publisher')){
        $script:SignatureStatus=if($case -eq 'bad-signature'){'NotSigned'}else{'Valid'}
        $script:Signer=if($case -eq 'wrong-publisher'){'CN=Not Microsoft Corporation, O=Microsoft Corporation'}else{'CN=Microsoft Corporation, O=Microsoft Corporation'}
        $failure='';try{Install-ClientCppRuntime $progress}catch{$failure=$_.Exception.Message}
        Assert ($failure.Contains('Signatur') -and $script:Started -eq 1 -and !(Test-Path (Split-Path $script:Downloaded -Parent))) 'Untrusted runtime accepted or retained'
    }
    $script:SignatureStatus='Valid';$script:Signer='CN=Microsoft Corporation, O=Microsoft Corporation'
    foreach($code in @(3010,1603)){
        $script:ExitCode=$code
        $failure='';try{Install-ClientCppRuntime $progress}catch{$failure=$_.Exception.Message}
        Assert ($failure -ne '') 'Failed/restart-required installation was accepted'
        if($code -eq 3010){Assert ($failure.Contains('neu starten')) 'Required restart hidden'}
        else{Assert ($failure.Contains('1603')) 'Native failure code hidden'}
        Assert (!(Test-Path (Split-Path $script:Downloaded -Parent))) 'Failed runtime download not removed'
    }
    Write-Output 'PASS: signed Microsoft-only download, explicit elevation, exit/restart handling and temporary cleanup (Windows effects mocked)'

    $script:Missing=$false;$script:Calls=@();$script:VadFailure=$false
    function Get-MissingClientCppLibraries {param($ClientDirectory) if($script:Missing){'msvcp140_1.dll'}}
    function Install-ClientCppRuntime {param($Progress) $script:Calls+='install'}
    function Assert-ClientVad {param($ClientDirectory) $script:Calls+='vad';if($script:VadFailure){throw 'synthetic Python exception retained'}}
    Initialize-ClientRuntime $client $progress
    Assert (($script:Calls -join ',') -eq 'vad') 'Existing runtime caused an unnecessary install'
    $script:Calls=@();$script:Missing=$true
    Initialize-ClientRuntime $client $progress
    Assert (($script:Calls -join ',') -eq 'install,vad') 'Real VAD verification must follow prerequisite installation'
    $script:VadFailure=$true
    $failure='';try{Initialize-ClientRuntime $client $progress}catch{$failure=$_.Exception.Message}
    Assert ($failure -eq 'synthetic Python exception retained') 'Remaining VAD failure was swallowed'
    Write-Output 'PASS: prerequisites only if missing, mandatory VAD check and propagated diagnostic'
} finally {
    $env:SystemRoot=$oldSystemRoot
    if(Test-Path $testDirectory){Remove-Item -LiteralPath $testDirectory -Recurse -Force}
}
