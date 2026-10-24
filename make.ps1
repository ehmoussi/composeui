<#
.SYNOPSIS
    The Makefile's targets for PowerShell: .\make.ps1 <target> [<target> ...]

.EXAMPLE
    .\make.ps1 check test
    .\make.ps1 screenshots -Examples pipeform, batman
    .\make.ps1 css -TailwindPlatform windows-x64
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [ValidateSet('format', 'check', 'check_fix', 'lint', 'mypy', 'translations', 'test',
        'browser-test', 'docs', 'screenshots', 'css', 'clean', 'all')]
    [string[]] $Targets = @('all'),
    # the examples to take screenshots of (all of them when empty)
    [string[]] $Examples = @(),
    # Tailwind's release name for this machine, detected when empty
    [string] $TailwindPlatform = ''
)

$ErrorActionPreference = 'Stop'
# Invoke-WebRequest is much slower with its progress bar
$ProgressPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

# the main views of the apps with catalogs, as module:Class
$TranslatedMainViews = @(
    'examples.pipeform:PipeMainView'
    'examples.pipesweep:PipeSweepMainView'
    'examples.taskview:TaskMainView'
)

$TailwindVersion = '4.3.3'
$DaisyuiVersion = '5.7.47'
$CssVendor = 'css/vendor'
$TailwindPlatforms = @('linux-x64', 'linux-arm64', 'macos-x64', 'macos-arm64',
    'linux-x64-musl', 'linux-arm64-musl', 'windows-x64')
# Runs a native command and stops on a non-zero exit code, as make does.
function Invoke-Native {
    param([string] $Command, [string[]] $Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Command $($Arguments -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

# Runs a script block with QT_QPA_PLATFORM=offscreen, then restores the variable.
function Invoke-Offscreen {
    param([scriptblock] $Block)
    $previous = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = 'offscreen'
    try { & $Block } finally { $env:QT_QPA_PLATFORM = $previous }
}

function Invoke-Download {
    param([string] $Url, [string] $Path)
    if (Test-Path $Path) { return }
    New-Item -ItemType Directory -Force $CssVendor | Out-Null
    # Windows PowerShell 5.1 may default to TLS 1.0, which GitHub refuses
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing
}

function Get-TailwindPlatform {
    if ($TailwindPlatform) { return $TailwindPlatform }
    # $IsLinux and $IsMacOS exist only in PowerShell 6+, which also runs off Windows
    if ($IsLinux) { $os = 'linux' } elseif ($IsMacOS) { $os = 'macos' } else { $os = 'windows' }
    $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    switch ($arch) {
        'X64' { $cpu = 'x64' }
        'Arm64' { $cpu = 'arm64' }
        default { $cpu = $arch.ToLower() }
    }
    return "$os-$cpu"
}

function Invoke-Format { Invoke-Native uv @('run', 'ruff', 'format') }

function Invoke-CheckFix { Invoke-Native uv @('run', 'ruff', 'check', '--fix') }

function Invoke-Lint {
    Invoke-Format
    Invoke-CheckFix
}

function Invoke-Mypy {
    Invoke-Native uv @(
        'run', 'mypy',
        '--config-file', 'pyproject.toml',
        '--package', 'composeui',
        '--package', 'examples',
        '--always-false=PYQT5',
        '--always-false=PYSIDE2',
        '--always-false=PYQT6',
        '--always-true=PYSIDE6',
        '--show-traceback'
    )
}

# every catalog against the text its app translates; each app reported before failing
function Invoke-Translations {
    $failed = $false
    foreach ($mainView in $TranslatedMainViews) {
        & uv run python -m composeui.core.translationcheck $mainView
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    }
    if ($failed) { throw 'translations: some catalogs are out of date' }
}

function Invoke-Check {
    Invoke-Lint
    Invoke-Mypy
    Invoke-Translations
}

function Invoke-Test {
    Invoke-Offscreen {
        Invoke-Native uv @('run', 'pytest', 'tests', '-m', 'not browser', '--cov=src',
            '--cov-report=term-missing:skip-covered')
    }
}

# the web backend in headless Chromium; skipped unless Chromium is installed:
# uv run --group browser playwright install chromium
# No pytest-qt: it refuses to start without a Qt binding, which these tests don't need.
function Invoke-BrowserTest {
    Invoke-Native uv @('run', '--group', 'browser', 'pytest', 'tests/test_browser.py',
        '-m', 'browser', '-p', 'no:pytest-qt')
}

# the documentation site in docs/_build/html; any warning fails it. Run
# `uv sync --group docs --all-extras` first.
function Invoke-Docs {
    Invoke-Native uv @('run', '--group', 'docs', 'sphinx-build', '-W', '--keep-going',
        '-b', 'html', 'docs', 'docs/_build/html')
}

# the screenshots of the examples guide, on every backend, into docs/images/; needs the
# browser group's Chromium (see browser-test)
function Invoke-Screenshots {
    Invoke-Offscreen {
        Invoke-Native uv (@('run', '--group', 'browser', 'python', 'docs/screenshots.py') +
            $Examples)
    }
}

# Tailwind's standalone CLI and daisyUI's plugin files, downloaded once into css/vendor/
function Invoke-Css {
    $platform = Get-TailwindPlatform
    if ($TailwindPlatforms -notcontains $platform) {
        throw ("No Tailwind binary for '$platform': pass one of " +
            "$($TailwindPlatforms -join ' ') as -TailwindPlatform")
    }
    $suffix = if ($platform -like 'windows-*') { '.exe' } else { '' }
    # the platform in the name: a checkout shared between machines keeps one binary for each
    $tailwind = "$CssVendor/tailwindcss-$TailwindVersion-$platform$suffix"
    $tailwindUrl = 'https://github.com/tailwindlabs/tailwindcss/releases/download/' +
        "v$TailwindVersion/tailwindcss-$platform$suffix"
    $daisyuiUrl = "https://github.com/saadeghi/daisyui/releases/download/v$DaisyuiVersion"
    Invoke-Download $tailwindUrl $tailwind
    if ($suffix -eq '') { Invoke-Native chmod @('+x', $tailwind) }
    Invoke-Download "$daisyuiUrl/daisyui.mjs" "$CssVendor/daisyui.mjs"
    Invoke-Download "$daisyuiUrl/daisyui-theme.mjs" "$CssVendor/daisyui-theme.mjs"
    Invoke-Native (Resolve-Path $tailwind).Path @('-i', 'css/app.css',
        '-o', 'src/composeui/webcore/static/app.css', '--minify')
}

function Invoke-Clean {
    Get-ChildItem -Recurse -Force -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force
    Get-ChildItem -Recurse -Force -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '\.py[co]$' -or $_.Name -like '*~' } |
        Remove-Item -Force
    $paths = @('.cache', '.pytest_cache', '.ruff_cache', 'htmlcov', '*.egg-info', '.coverage',
        '.coverage.*', 'build', 'dist', 'site', 'docs/_build', 'coverage.xml')
    foreach ($path in $paths) {
        if (Test-Path $path) { Remove-Item $path -Recurse -Force }
    }
}

function Invoke-All {
    Invoke-Clean
    Invoke-Check
    Invoke-Test
}

$actions = @{
    'format'       = { Invoke-Format }
    'check'        = { Invoke-Check }
    'check_fix'    = { Invoke-CheckFix }
    'lint'         = { Invoke-Lint }
    'mypy'         = { Invoke-Mypy }
    'translations' = { Invoke-Translations }
    'test'         = { Invoke-Test }
    'browser-test' = { Invoke-BrowserTest }
    'docs'         = { Invoke-Docs }
    'screenshots'  = { Invoke-Screenshots }
    'css'          = { Invoke-Css }
    'clean'        = { Invoke-Clean }
    'all'          = { Invoke-All }
}

foreach ($target in $Targets) {
    Write-Host "==> $target" -ForegroundColor Cyan
    & $actions[$target]
}
