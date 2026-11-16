# Execute the real Install-App function and subsequent completion in an isolated
# engine scope. Mock only Windows registrations/COM; use real staging and cleanup.
$ErrorActionPreference='Stop'
$testRepository=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sourceFile=Join-Path $testRepository 'server-windows/windows/Engine.ps1'
if($env:KIENZLEDOKU_ENGINE_UNDER_TEST){$sourceFile=$env:KIENZLEDOKU_ENGINE_UNDER_TEST}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($sourceFile,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$top=@($ast.EndBlock.Statements)
$install=@($top|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst] -and $_.Name -eq 'Install-App'})
if($install.Count -ne 1){throw 'Install-App fehlt.'}
$loaders=@($top|Where-Object {$_.Extent.Text -match '^\. \(Join-Path .*windows/Update\.ps1.*\)$'})
$base=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-engine-scope-'+[guid]::NewGuid().ToString('N'))
try {
    $script:Root=Join-Path $base 'source';$script:InstallerVersion='synthetic-test'
    $destination=Join-Path $base 'installed'
    $null=[IO.Directory]::CreateDirectory((Join-Path $script:Root 'windows'))
    Copy-Item (Join-Path $testRepository 'server-windows/windows/Update.ps1') (Join-Path $script:Root 'windows/Update.ps1')
    foreach($name in @('VERSION','models.json','audio-files.json','audio-turbo-files.json','ubuntu.json','linux-payload.tar','README.txt')){Set-Content (Join-Path $script:Root $name) 'synthetic payload'}
    $null=[IO.Directory]::CreateDirectory((Join-Path $destination 'app'))
    Set-Content (Join-Path $destination 'app/VERSION') 'old version'
    Set-Content (Join-Path $destination 'app/obsolete.txt') 'old code'
    $configPath=Join-Path $destination 'config.json'
    $script:Cfg=[pscustomobject]@{InstallDirectory=$destination;StateDirectory=(Join-Path $base 'state');Models=@('synthetic-model');PromptText='Angepasster Prompt mit Umlauten: äöüß'}
    $script:CodeUpdate=$null
    # Mock actual Windows COM/registry effects; no helpers are preloaded by this test.
    function New-Object {
        param([string]$ComObject)
        if($ComObject -ne 'WScript.Shell'){throw 'Unexpected COM object'}
        $shell=[pscustomobject]@{}
        $shell|Add-Member ScriptMethod CreateShortcut {
            param($Path)
            $shortcut=[pscustomobject]@{TargetPath='';Arguments='';WorkingDirectory='';Path=$Path}
            $shortcut|Add-Member ScriptMethod Save {}
            return $shortcut
        }
        return $shell
    }
    function Join-Path {
        param([AllowEmptyString()][string]$Path,[string]$ChildPath)
        if(!$Path -or $Path -eq [Environment]::GetFolderPath('Programs')){$Path=[IO.Path]::Combine($base,'start-menu')}
        [IO.Path]::Combine($Path,$ChildPath)
    }
    function New-Item {
        param([string]$Path,[switch]$Force)
        if($Path -notlike 'HKCU:*'){throw 'Unexpected mutation'}
    }
    function Set-ItemProperty {param($Path,$Name,$Value,$Type)}
    function Set-PrivateFile {param($Path)}
    function Write-Json {param($Path,$Value) $Value|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $Path -Encoding UTF8}
    # Same script-level helper loading and Install-App body as the production engine.
    foreach($loader in $loaders){. ([scriptblock]::Create($loader.Extent.Text))}
    . ([scriptblock]::Create($install[0].Extent.Text))
    Install-App
    if(!$script:CodeUpdate){throw 'No real staged replacement happened'}
    if(Test-Path (Join-Path $destination 'app/obsolete.txt')){throw 'Old code survived replacement'}
    if(!(Test-Path (Join-Path $script:CodeUpdate.Work 'previous/obsolete.txt'))){throw 'Old tree was not retained until validation'}
    # This is the command that failed after returning from Install-App on Windows.
    Complete-CodeUpdate $script:CodeUpdate
    if(Test-Path $script:CodeUpdate.Work){throw 'Backup survived completion'}
    if((Get-Content $configPath -Raw|ConvertFrom-Json).PromptText -ne $script:Cfg.PromptText){throw 'Configuration changed'}
    Write-Output 'PASS: real Install-App returns, completion remains in scope, old code removed, configured prompt preserved. Windows effects mocked.'
} finally {if(Test-Path $base){Microsoft.PowerShell.Management\Remove-Item -LiteralPath $base -Recurse -Force}}
