[CmdletBinding()]
param([string]$Python, [string]$Go = 'go', [switch]$SkipInstaller)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Build = Join-Path $Root 'build/windows'
$Package = Join-Path $Build 'kienzledoku-record-1.3.3'
New-Item -ItemType Directory -Force $Build, $Package | Out-Null
function Run-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE)" }
}
if (!$Python) {
    if (Get-Command 'py.exe' -ErrorAction SilentlyContinue) {
        $Python = (& py.exe -3.12 -c 'import sys;print(sys.executable)').Trim()
        if ($LASTEXITCODE -ne 0) { throw 'CPython 3.12 x64 fehlt. Siehe windows/README.md.' }
    } else { $Python = 'python' }
}
foreach ($Tool in @($Go, 'cmake')) {
    if (!(Get-Command $Tool -ErrorAction SilentlyContinue)) { throw "$Tool fehlt im PATH. Siehe windows/README.md." }
}
# CPython 3.12 has a complete embeddable distribution; same version supplies wheels.
Run-Checked $Python @('-c', "import sys; assert sys.version_info[:2] == (3,12), 'Use CPython 3.12 x64'; assert sys.maxsize > 2**32")
$PythonVersion = (& $Python -c 'import platform; print(platform.python_version())').Trim()
$RuntimeArchive = Join-Path $Build "python-$PythonVersion-embed-amd64.zip"
if (!(Test-Path $RuntimeArchive)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -UseBasicParsing -OutFile $RuntimeArchive
}
$Runtime = Join-Path $Package 'runtime'
Expand-Archive $RuntimeArchive -DestinationPath $Runtime -Force
# Only the selected bundled interpreter, application and bundled packages are importable.
@('python312.zip', '.', '..', 'Lib/site-packages', 'import site') | Set-Content (Join-Path $Runtime 'python312._pth') -Encoding Ascii
Run-Checked $Python @('-m', 'pip', 'install', '--only-binary=:all:', '--upgrade', '--target', (Join-Path $Runtime 'Lib/site-packages'), '-r', (Join-Path $Root 'requirements-asr-client.txt'))
Get-ChildItem $Root -Filter 'kienzledoku*.py' | Copy-Item -Destination $Package -Force
Copy-Item (Join-Path $Root 'prompt_documentation.txt') $Package
Copy-Item (Join-Path $Root 'assets') $Package -Recurse -Force
Copy-Item (Join-Path $PSScriptRoot 'install.ps1'), (Join-Path $PSScriptRoot 'install.cmd'), (Join-Path $PSScriptRoot 'uninstall.ps1') $Package
$env:CGO_ENABLED = '0'; $env:GOOS = 'windows'; $env:GOARCH = 'amd64'
Push-Location (Join-Path $Root 'connect')
try { Run-Checked $Go @('test', './...'); Run-Checked $Go @('build', '-trimpath', '-ldflags=-H=windowsgui', '-o', (Join-Path $Package 'kienzleconnect.exe'), '.') } finally { Pop-Location }
$SdkVersion = '1.0.3537.50'
$Sdk = Join-Path $Build "webview2-$SdkVersion"
if (!(Test-Path (Join-Path $Sdk 'build/native/include/WebView2.h'))) {
    $Archive = Join-Path $Build "webview2-$SdkVersion.zip"
    Invoke-WebRequest "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$SdkVersion/microsoft.web.webview2.$SdkVersion.nupkg" -UseBasicParsing -OutFile $Archive
    Expand-Archive $Archive -DestinationPath $Sdk -Force
}
Run-Checked 'cmake' @('-S', $PSScriptRoot, '-B', (Join-Path $Build 'native'), '-A', 'x64', "-DWEBVIEW2_SDK=$Sdk")
Run-Checked 'cmake' @('--build', (Join-Path $Build 'native'), '--config', 'Release')
Copy-Item (Join-Path $Build 'native/Release/kienzledoku_window.exe') $Package
$PreviousConfig = $env:KIENZLEDOKU_CONFIG_DIR
$PreviousConnect = $env:KIENZLEDOKU_TEST_CONNECT
$env:KIENZLEDOKU_CONFIG_DIR = Join-Path $Build 'test-config'
$env:KIENZLEDOKU_TEST_CONNECT = Join-Path $Package 'kienzleconnect.exe'
Push-Location $Root
try {
    # Embeddable Python deliberately excludes cwd; add the source for repository tests.
    Run-Checked (Join-Path $Runtime 'python.exe') @('-c', "import sys,unittest;sys.path.insert(0,sys.argv[1]);r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(sys.argv[1]+'/tests'));sys.exit(not r.wasSuccessful())", $Root)
    Run-Checked (Join-Path $Runtime 'python.exe') @((Join-Path $Package 'kienzledoku.py'), '--self-test')
} finally { Pop-Location; $env:KIENZLEDOKU_CONFIG_DIR = $PreviousConfig; $env:KIENZLEDOKU_TEST_CONNECT = $PreviousConnect }
Compress-Archive -Path $Package -DestinationPath (Join-Path $Build 'kienzledoku-record-1.3.3-windows-x64.zip') -Force
if (!$SkipInstaller) {
    $Iscc = (Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue).Source
    if (!$Iscc) {
        $Candidate = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        if (Test-Path $Candidate) { $Iscc = $Candidate }
    }
    if (!$Iscc) { throw 'Inno Setup 6 fehlt. Installieren oder -SkipInstaller fuer ZIP verwenden.' }
    Run-Checked $Iscc @("/DPackageDir=$Package", "/DOutputDir=$Build", (Join-Path $PSScriptRoot 'installer.iss'))
}
Write-Host "Build fertig: $Build"
Write-Host "Programm-ZIP: $(Join-Path $Build 'kienzledoku-record-1.3.3-windows-x64.zip')"
if (!$SkipInstaller) {
    Write-Host "Installer: $(Join-Path $Build 'kienzledoku-record-1.3.3-windows-x64-setup.exe')"
    Write-Host 'Zur Installation die oben genannte setup.exe starten.'
}
