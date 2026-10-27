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
    [ValidateSet('format', 'check', 'check_fix', 'lint', 'mypy', 'typecheck',
        'pyright', 'pyrefly', 'ty', 'zuban', 'translations', 'test',
        'browser-test', 'docs', 'screenshots', 'css', 'web-deps', 'clean', 'all')]
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
# the SHA-256 of each download, from Tailwind's sha256sums.txt and the digests of daisyUI's
# release assets: change them with the versions
$Sha256 = @{
    'tailwindcss-linux-x64'        = 'dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a'
    'tailwindcss-linux-arm64'      = '55fd0b241214eff3de1e8ee4f22796662f2d2e7a49bcfca7477cfd0bac398195'
    'tailwindcss-macos-x64'        = '7922e0953f2110c05976e3bf58f14e643d90427575e766b7d433f5f80cbee7e1'
    'tailwindcss-macos-arm64'      = 'cdf646702987a743464dff4d9c60fd4480d1c1e73dd819a9a67f1078815dce9d'
    'tailwindcss-linux-x64-musl'   = 'a04d34ceacc8f52cbe8920ad846cdeb61d3d0021dba32db0d1f77c9d9fad7a6c'
    'tailwindcss-linux-arm64-musl' = '71ea4be79c9de9827545682df3e040053fb535d37c71ed2cfdedf9385a0868e0'
    'tailwindcss-windows-x64.exe'  = 'e0e260ce048014e9268f6237ff18f8ccf02cef521cbd0ae04e82c2cdf7aa3955'
    'daisyui.mjs'                  = '85819d3fe86a852237b439b13f481481aac58e562ac47694cd11c3038e994f2a'
    'daisyui-theme.mjs'            = 'd92d2f488933dab757f046e81ebd4986e51e9423307798dc3545d09a15542c89'
}

# the web page's scripts from npm, through unpkg, and uPlot's stylesheet, which app.css
# imports: committed, so the package needs no download. Change a version and its SHA-256,
# run `.\make.ps1 web-deps css`, and commit the files.
$Static = 'src/composeui/webcore/static'
$HtmxVersion = '2.0.10'
$UplotVersion = '1.6.32'
$CallyVersion = '0.9.2'
$DeckglVersion = '9.2.6'
$WebDeps = @(
    @{
        Url    = "https://unpkg.com/deck.gl@$DeckglVersion/dist.min.js"
        Path   = "$Static/deckgl.min.js"
        Sha256 = '234e0af97a691b8e5aea6c6ca9e703a7ba5206fd1f53daa9f670e41db089de2d'
    }
    @{
        Url    = "https://unpkg.com/deck.gl@$DeckglVersion/LICENSE"
        Path   = "$Static/deckgl.LICENSE"
        Sha256 = 'e499a2c2ba3b9faabe91fdfddf43e329439263264b7148e5548d0ec605cce9f2'
    }
    @{
        Url    = "https://unpkg.com/htmx.org@$HtmxVersion/dist/htmx.min.js"
        Path   = "$Static/htmx.min.js"
        Sha256 = '71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de'
    }
    @{
        Url    = "https://unpkg.com/uplot@$UplotVersion/dist/uPlot.iife.min.js"
        Path   = "$Static/uPlot.iife.min.js"
        Sha256 = '19c8d4c6ad88929a79f4ae49d6f7161566dfd0ba3d15cc495e974f787eb78f1f'
    }
    @{
        Url    = "https://unpkg.com/uplot@$UplotVersion/LICENSE"
        Path   = "$Static/uPlot.LICENSE"
        Sha256 = '8f989229699b4fe2f1a0432d0e9edc338a8a911e250e2d1b01ecd770a5f5b1bd'
    }
    @{
        Url    = "https://unpkg.com/uplot@$UplotVersion/dist/uPlot.min.css"
        Path   = 'css/uPlot.min.css'
        Sha256 = 'df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04'
    }
    # daisyUI's classes are built into app.css (css); its license ships beside it
    @{
        Url    = "https://unpkg.com/daisyui@$DaisyuiVersion/LICENSE"
        Path   = "$Static/daisyui.LICENSE"
        Sha256 = '8709e3ac65c84637c422dc8082b893d9997fce093751c77b2f1983bf29dbf9ea'
    }
    @{
        Url    = "https://unpkg.com/cally@$CallyVersion/dist/cally.js"
        Path   = "$Static/cally.dist.js"
        Sha256 = '4dcba6a3b8ec63b66ff2fbfc6cf47b7dee1eb4896eac89fe7487d82e28e15870'
    }
    @{
        Url    = "https://unpkg.com/cally@$CallyVersion/LICENSE"
        Path   = "$Static/cally.LICENSE"
        Sha256 = 'c48fd407090d6d752b0370d39db55bd750e6dfc678ee252d4c906bddf54132eb'
    }
)

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

function Test-Sha256 {
    param([string] $Path, [string] $Expected)
    return (Get-FileHash -Algorithm SHA256 $Path).Hash -eq $Expected
}

# Downloads a file, kept only when its SHA-256 is the expected one.
function Save-Verified {
    param([string] $Url, [string] $Path, [string] $Expected)
    New-Item -ItemType Directory -Force (Split-Path $Path) | Out-Null
    # Windows PowerShell 5.1 may default to TLS 1.0, which GitHub refuses
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $download = "$Path.tmp"
    Invoke-WebRequest -Uri $Url -OutFile $download -UseBasicParsing
    if (-not (Test-Sha256 $download $Expected)) {
        Remove-Item $download -Force
        throw "The SHA-256 of $Url is not ${Expected}: the file was not kept"
    }
    Move-Item -Force $download $Path
}

# Downloads a file once. A file already there is checked too: it can be from an older
# version, or have changed since.
function Invoke-Download {
    param([string] $Url, [string] $Path, [string] $Expected)
    if (-not (Test-Path $Path)) {
        Save-Verified $Url $Path $Expected
    }
    elseif (-not (Test-Sha256 $Path $Expected)) {
        throw "The SHA-256 of $Path is not ${Expected}: delete $CssVendor/ to download it again"
    }
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
        'run', '--locked', '--group', 'browser', '--all-extras', 'mypy',
        '--config-file', 'pyproject.toml',
        '--package', 'composeui',
        '--package', 'examples',
        '--package', 'tests',
        '--always-false=PYQT5',
        '--always-false=PYSIDE2',
        '--always-false=PYQT6',
        '--always-true=PYSIDE6',
        '--show-traceback'
    )
}

# Tests import every backend and Playwright; static checks do not need Chromium.
function Invoke-TypeChecker {
    param([string[]] $Arguments)
    Invoke-Native uv (@('run', '--locked', '--group', 'typecheck', '--group', 'browser',
        '--all-extras') + $Arguments)
}

function Invoke-Typecheck {
    Invoke-Mypy
    Invoke-TypeChecker -Arguments @('pyright')
    Invoke-TypeChecker -Arguments @('pyrefly', 'check')
    Invoke-TypeChecker -Arguments @('ty', 'check')
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
    # the lines only POSIX runs, e.g. a process ignoring its termination: left out here
    $previous = $env:COMPOSEUI_POSIX_ONLY
    $env:COMPOSEUI_POSIX_ONLY = '# posix only'
    try {
        Invoke-Offscreen {
            # in parallel, a worker per CPU (pytest-xdist)
            Invoke-Native uv @('run', 'pytest', 'tests', '-m', 'not browser', '-n', 'auto',
                '--cov=src', '--cov-report=term-missing:skip-covered')
        }
    }
    finally { $env:COMPOSEUI_POSIX_ONLY = $previous }
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
    Invoke-Download $tailwindUrl $tailwind $Sha256["tailwindcss-$platform$suffix"]
    if ($suffix -eq '') { Invoke-Native chmod @('+x', $tailwind) }
    foreach ($name in @('daisyui.mjs', 'daisyui-theme.mjs')) {
        Invoke-Download "$daisyuiUrl/$name" "$CssVendor/$name" $Sha256[$name]
    }
    Invoke-Native (Resolve-Path $tailwind).Path @('-i', 'css/app.css',
        '-o', 'src/composeui/webcore/static/app.css', '--minify')
}

# Cally's file has no license comment: it gets Cally's LICENSE as one; uPlot's has only its
# address, and its LICENSE goes beside it
function Invoke-WebDeps {
    foreach ($dependency in $WebDeps) {
        Save-Verified $dependency.Url $dependency.Path $dependency.Sha256
    }
    $license = [IO.File]::ReadAllText("$PSScriptRoot/$Static/cally.LICENSE").TrimEnd("`n")
    $lines = @("/*! https://github.com/WickyNilliams/cally (v$CallyVersion), its dependency " +
        'atomico bundled in')
    foreach ($line in $license -split "`n") { $lines += (' * ' + $line).TrimEnd(' ') }
    $lines += ' */'
    $body = [IO.File]::ReadAllText("$PSScriptRoot/$Static/cally.dist.js")
    # UTF-8 without a BOM and LF line endings, as the Makefile writes it
    [IO.File]::WriteAllText("$PSScriptRoot/$Static/cally.js", ($lines -join "`n") + "`n" + $body,
        (New-Object System.Text.UTF8Encoding $false))
    Remove-Item "$Static/cally.dist.js", "$Static/cally.LICENSE" -Force
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
    'typecheck'    = { Invoke-Typecheck }
    'pyright'      = { Invoke-TypeChecker -Arguments @('pyright') }
    'pyrefly'      = { Invoke-TypeChecker -Arguments @('pyrefly', 'check') }
    'ty'           = { Invoke-TypeChecker -Arguments @('ty', 'check') }
    'zuban'        = { Invoke-TypeChecker -Arguments @('zuban', 'mypy', 'tests') }
    'translations' = { Invoke-Translations }
    'test'         = { Invoke-Test }
    'browser-test' = { Invoke-BrowserTest }
    'docs'         = { Invoke-Docs }
    'screenshots'  = { Invoke-Screenshots }
    'css'          = { Invoke-Css }
    'web-deps'     = { Invoke-WebDeps }
    'clean'        = { Invoke-Clean }
    'all'          = { Invoke-All }
}

foreach ($target in $Targets) {
    Write-Host "==> $target" -ForegroundColor Cyan
    & $actions[$target]
}
