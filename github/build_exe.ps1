param(
    [switch]$SkipInstall,
    [switch]$SkipInstaller,
    [switch]$BootstrapPython38,
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Get-PythonVersionText([string]$Exe) {
    try {
        return (& $Exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    } catch {
        return $null
    }
}

function Resolve-Python38([string]$Preferred) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Preferred) {
        $candidates.Add($Preferred)
    }
    $localPython = Join-Path $Root ".build\python38-x64\python.exe"
    if (Test-Path $localPython) {
        $candidates.Add($localPython)
    }
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $py38Path = (& py -3.8 -c "import sys; print(sys.executable)" 2>$null).Trim()
            if ($py38Path) {
                $candidates.Add($py38Path)
            }
        } catch {
        }
    }
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates.Add($pythonCommand.Source)
    }

    foreach ($candidate in $candidates) {
        if (-not $candidate) {
            continue
        }
        $version = Get-PythonVersionText $candidate
        if ($version -eq "3.8") {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

function Install-LocalPython38() {
    $targetDir = Join-Path $Root ".build\python38-x64"
    $pythonPath = Join-Path $targetDir "python.exe"
    if (Test-Path $pythonPath) {
        return $pythonPath
    }

    $downloadDir = Join-Path $Root ".build\downloads"
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    $installerPath = Join-Path $downloadDir "python-3.8.10-amd64.exe"
    if (-not (Test-Path $installerPath)) {
        Write-Host "Downloading Python 3.8.10 x64 for Win7-compatible packaging..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe" -OutFile $installerPath
    }

    Write-Host "Installing local Python 3.8.10 to $targetDir ..."
    $args = @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=`"$targetDir`"",
        "Include_launcher=0",
        "PrependPath=0",
        "Include_pip=1",
        "Include_tcltk=1",
        "Include_test=0",
        "Include_doc=0"
    )
    $process = Start-Process -FilePath $installerPath -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Python 3.8 installer failed with exit code $($process.ExitCode)."
    }
    if (-not (Test-Path $pythonPath)) {
        throw "Python 3.8 install completed but python.exe was not found at $pythonPath."
    }
    return $pythonPath
}

$Python = Resolve-Python38 $PythonExe
if (-not $Python -and $BootstrapPython38) {
    $Python = Install-LocalPython38
}
if (-not $Python) {
    throw "Python 3.8 is required for Win7-compatible packaging. Install Python 3.8 x64, pass -PythonExe, or run with -BootstrapPython38."
}

$pyVersion = Get-PythonVersionText $Python
Write-Host "Using Python ${pyVersion}: $Python"

if (-not $SkipInstall) {
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements.txt
    Push-Location web
    npm install
    npm run build
    Pop-Location
}

if (-not (Test-Path "web/dist/index.html")) {
    throw "web/dist/index.html not found. Build the frontend first."
}

& $Python -m PyInstaller .\EcoInvoiceRecon.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE."
}

if (-not $SkipInstaller) {
    $isccPath = $null
    $isccCommand = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($isccCommand) {
        $isccPath = $isccCommand.Source
    }
    if (-not $isccPath) {
        $candidate = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        if (Test-Path $candidate) {
            $isccPath = $candidate
        }
    }
    if ($isccPath) {
        & $isccPath ".\installer\EcoInvoiceRecon.iss"
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup build failed with exit code $LASTEXITCODE."
        }
    } else {
        Write-Warning "Inno Setup ISCC.exe not found. Exe folder was built; installer was skipped."
    }
}

Write-Host "Build complete: dist\EcoInvoiceRecon\EcoInvoiceRecon.exe"
