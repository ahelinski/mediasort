param(
    [switch]$WithFFmpeg
)

$ErrorActionPreference = 'Stop'
# W PowerShell 7.3+ ta opcja powoduje, ze KAZDE wywolanie programu zewnetrznego
# (py, python, pip, PyInstaller...) z niezerowym kodem wyjscia natychmiast rzuca
# wyjatek terminujacy - z pominieciem logiki "sprawdz $LASTEXITCODE i kontynuuj",
# ktora ten skrypt wykorzystuje np. przy szukaniu odpowiedniej wersji Pythona.
# Wylaczamy to, zeby skrypt sam decydowal, kiedy blad jest fatalny.
if (Test-Path Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

# --- sciezki ---------------------------------------------------------------
$RepoRoot  = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$VenvDir   = Join-Path $RepoRoot '.venv'
$VenvPy    = Join-Path $VenvDir 'Scripts\python.exe'
$MainPy    = Join-Path $RepoRoot 'main.py'
$Launcher  = Join-Path $RepoRoot 'packaging\windows\launcher.py'
$ExePath   = Join-Path $RepoRoot 'MediaSort.exe'
$Requirements = Join-Path $RepoRoot 'requirements.txt'
$ProgId    = 'MediaSort.Media'

# --- male helpery ----------------------------------------------------------
function Write-Step { Write-Host ('==> ' + $args[0]) -ForegroundColor Cyan }
function Write-Ok   { Write-Host ('    ' + $args[0]) -ForegroundColor Green }
function Write-Warn { Write-Host ('UWAGA: ' + $args[0]) -ForegroundColor Yellow }

function Stop-MediaSortProcesses {
    # Zamyka MediaSort.exe (bootloader PyInstaller) oraz uruchomiona przez
    # niego aplikacje (pythonw.exe z .venv). Zwraca $true, gdy nic nie blokuje.
    param([string]$ExePath, [string]$VenvDir, [switch]$Force)
    $targets = @()
    try {
        $targets = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            ($_.Name -ieq 'MediaSort.exe' -and $_.ExecutablePath -and $_.ExecutablePath -ieq $ExePath) -or
            ($_.Name -ieq 'pythonw.exe' -and $_.ExecutablePath -and
             $_.ExecutablePath -like ($VenvDir + '\*') -and $_.CommandLine -like '*main.py*')
        })
    } catch { }
    if ($targets.Count -eq 0) { return $true }
    if (-not $Force) {
        Write-Warn 'Aplikacja MediaSort jest teraz uruchomiona.'
        $ans = Read-Host 'Zamknac ja, aby kontynuowac? [t/N]'
        if ($ans -notmatch '^(t|y|tak)$') {
            Write-Host 'Anulowano.' -ForegroundColor Yellow
            return $false
        }
    }
    foreach ($p in $targets) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { }
    }
    Start-Sleep -Milliseconds 600
    return $true
}

function Get-MediaExtensions {
    # Lista rozszerzen brana wprost z mediasort/config.py (obrazow + wideo).
    $cfg = Join-Path $RepoRoot 'mediasort\config.py'
    if (Test-Path -LiteralPath $cfg) {
        $txt = Get-Content -LiteralPath $cfg -Raw
        $mImg = [regex]::Match($txt, '"image_extensions":\s*\[(.*?)\]')
        $mVid = [regex]::Match($txt, '"video_extensions":\s*\[(.*?)\]')
        $joined = $mImg.Groups[1].Value + ',' + $mVid.Groups[1].Value
        $exts = @([regex]::Matches($joined, '"\.[A-Za-z0-9]+"') | ForEach-Object { $_.Value.Trim('"') })
        if ($exts.Count -gt 0) { return @($exts | Sort-Object -Unique) }
    }
    # Fallback, gdyby config.py nie dalo sie odczytac:
    return @('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tif', '.tiff',
             '.mp4', '.avi', '.mkv', '.mov', '.webm', '.m4v', '.wmv', '.flv')
}

function Find-SystemPython {
    # Szuka Pythona 3.9+ przez launcher 'py' (python.org) lub 'python' z PATH.
    $candidates = @()
    foreach ($name in @('py', 'python')) {
        if (Get-Command $name -ErrorAction SilentlyContinue) { $candidates += $name }
    }
    if ($candidates.Count -eq 0) {
        throw 'Nie znaleziono Pythona. Zainstaluj Pythona 3.9+ z https://www.python.org/downloads/ (zaznacz "py launcher" i "Add python.exe to PATH") i uruchom ponownie.'
    }
    # Uzywamy tymczasowego pliku .py zamiast "-c '...'", bo przekazywanie
    # cudzyslowow przez launcher py.exe do python.exe bywa zawodne w Windows/PowerShell.
    $probeScript = Join-Path $env:TEMP 'mediasort_probe_pyver.py'
    'import sys; print("%d.%d" % sys.version_info[:2])' | Set-Content -LiteralPath $probeScript -Encoding ASCII
    foreach ($name in $candidates) {
        $probeArgs = @($probeScript)
        if ($name -eq 'py') { $probeArgs = @('-3') + $probeArgs }
        $out = & $name @probeArgs 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
        $verLine = ($out | Select-Object -Last 1)
        if ($verLine -match '^(\d+)\.(\d+)') {
            $vMajor = [int]$Matches[1]
            $vMinor = [int]$Matches[2]
            if ($vMajor -eq 3 -and $vMinor -ge 9) {
                Write-Ok ('Znaleziono Pythona {0}.{1} (komenda: {2}).' -f $vMajor, $vMinor, $name)
                Remove-Item -LiteralPath $probeScript -Force -ErrorAction SilentlyContinue
                return $name
            }
        }
    }
    Remove-Item -LiteralPath $probeScript -Force -ErrorAction SilentlyContinue
    throw 'Brak odpowiedniego Pythona (wymagany 3.9+). Zainstaluj z https://www.python.org/downloads/ i uruchom ponownie.'
}

function Ensure-Venv {
    param([string]$VenvDir, [string]$SystemPython)
    if (Test-Path -LiteralPath $VenvDir) {
        if (-not (Test-Path -LiteralPath (Join-Path $VenvDir 'Scripts\python.exe'))) {
            Write-Warn ('Katalog {0} istnieje, ale nie zawiera venv Windows (brak Scripts\python.exe). Usuwam i tworze od nowa.' -f $VenvDir)
            Remove-Item -LiteralPath $VenvDir -Recurse -Force
        } else {
            Write-Ok 'venv .venv juz istnieje - uzyje go.'
            return
        }
    }
    Write-Step 'Tworzenie venv (.venv) ...'
    & $SystemPython -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie utworzyc venv.' }
    Write-Ok 'venv gotowy.'
}

function Install-Dependencies {
    param([string]$VenvPy, [string]$Requirements)
    Write-Step 'Instalowanie zaleznosci z requirements.txt (PySide6 - moze potrwac) ...'
    & $VenvPy -m pip install --disable-pip-version-check -r $Requirements
    if ($LASTEXITCODE -ne 0) { throw 'pip install zakonczyl sie bledem. Sprawdz polaczenie z internetem.' }
    Write-Ok 'Zaleznosci zainstalowane.'
}

function Ensure-PyInstaller {
    param([string]$VenvPy)
    $probeScript = Join-Path $env:TEMP 'mediasort_probe_pyinstaller.py'
    "import importlib.util, sys`nsys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)" |
        Set-Content -LiteralPath $probeScript -Encoding ASCII
    & $VenvPy $probeScript 2>$null
    $found = ($LASTEXITCODE -eq 0)
    Remove-Item -LiteralPath $probeScript -Force -ErrorAction SilentlyContinue
    if (-not $found) {
        Write-Step 'Instalowanie PyInstaller (do budowy MediaSort.exe) ...'
        & $VenvPy -m pip install --disable-pip-version-check pyinstaller
        if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zainstalowac PyInstaller.' }
    } else {
        Write-Ok 'PyInstaller dostepny w venv.'
    }
}

function Build-Launcher {
    param([string]$VenvPy, [string]$Launcher, [string]$ExePath, [string]$VenvDir)
    # Buduj tylko, gdy exe nie istnieje albo launcher.py jest nowszy.
    if (Test-Path -LiteralPath $ExePath) {
        $exeTime = (Get-Item -LiteralPath $ExePath).LastWriteTimeUtc
        $srcTime = (Get-Item -LiteralPath $Launcher).LastWriteTimeUtc
        if ($exeTime -ge $srcTime) {
            Write-Ok 'MediaSort.exe jest aktualny - pomijam budowe.'
            return
        }
    }
    Write-Step 'Budowa MediaSort.exe (PyInstaller) ...'
    $distDir = Join-Path $RepoRoot 'dist'
    $workDir = Join-Path $RepoRoot 'build\pyinstaller'
    $specDir = Join-Path $RepoRoot 'build\spec'
    New-Item -ItemType Directory -Force -Path $distDir, $workDir, $specDir | Out-Null
    $piArgs = @('--noconfirm', '--clean', '--onefile', '--windowed',
                '--name', 'MediaSort',
                '--distpath', $distDir,
                '--workpath', $workDir,
                '--specpath', $specDir,
                $Launcher)
    & $VenvPy -m PyInstaller @piArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Budowa MediaSort.exe nie powiodla sie (artefakty zostaly w build/ i dist/ do diagnozy).'
    }
    # Zamiana starego exe (moze byc zablokowany przez dzialajaca aplikacje).
    if (Test-Path -LiteralPath $ExePath) {
        try {
            Remove-Item -LiteralPath $ExePath -Force
        } catch {
            if (-not (Stop-MediaSortProcesses -ExePath $ExePath -VenvDir $VenvDir)) {
                throw 'Instalacja anulowana - MediaSort.exe jest w uzyciu.'
            }
            Start-Sleep -Milliseconds 400
            Remove-Item -LiteralPath $ExePath -Force -ErrorAction Stop
        }
    }
    Copy-Item -LiteralPath (Join-Path $distDir 'MediaSort.exe') -Destination $ExePath -Force
    Write-Ok ('Utworzono: {0}' -f $ExePath)
}

function Add-MediaSortAssociations {
    param([string]$ExePath, [string[]]$Extensions)
    Write-Step 'Rejestrowanie MediaSort w menu "Otworz za pomoca" (HKCU\Software\Classes) ...'
    $classes = 'HKCU:\Software\Classes'

    # ProgID: opis + ikona + komenda otwierania.
    $progKey = "$classes\$ProgId"
    New-Item -Path $progKey -Force | Out-Null
    Set-Item -Path $progKey -Value 'MediaSort'
    $iconKey = "$progKey\DefaultIcon"
    New-Item -Path $iconKey -Force | Out-Null
    Set-Item -Path $iconKey -Value ('"{0}",0' -f $ExePath)
    $cmdKey = "$progKey\shell\open\command"
    New-Item -Path $cmdKey -Force | Out-Null
    Set-Item -Path $cmdKey -Value ('"{0}" "%1"' -f $ExePath)

    # Widocznosc w pelnej liscie "Otworz za pomoca -> Wybierz inna aplikacje".
    $appKey = "$classes\Applications\MediaSort.exe"
    New-Item -Path "$appKey\shell\open\command" -Force | Out-Null
    Set-Item -Path "$appKey\shell\open\command" -Value ('"{0}" "%1"' -f $ExePath)
    Set-Item -Path $appKey -Value 'MediaSort'
    New-ItemProperty -Path $appKey -Name 'FriendlyAppName' -PropertyType String -Value 'MediaSort' -Force | Out-Null

    # Podmenu "Otworz za pomoca" dla kazdego zarejestrowanego rozszerzenia.
    foreach ($ext in $Extensions) {
        $owpKey = "$classes\$ext\OpenWithProgids"
        New-Item -Path $owpKey -Force | Out-Null
        New-ItemProperty -Path $owpKey -Name $ProgId -PropertyType String -Value '' -Force | Out-Null
    }
    Write-Ok ('Zarejestrowano dla {0} rozszerzen.' -f $Extensions.Count)
}

# --- ffmpeg (opcjonalnie, -WithFFmpeg) --------------------------------------
$ToolsDir = Join-Path $RepoRoot 'tools'
$SettingsJson = Join-Path $RepoRoot 'mediasort\settings.json'

function Set-SettingsToolPaths {
    # Wpisuje sciezki tools\ffmpeg.exe / ffprobe.exe do mediasort/settings.json
    # (aplikacja laczy ten plik z domyslnymi ustawieniami przy starcie).
    param([string]$FfmpegPath, [string]$FfprobePath)
    $data = @{ }
    if (Test-Path -LiteralPath $SettingsJson) {
        try {
            $data = Get-Content -LiteralPath $SettingsJson -Raw | ConvertFrom-Json -ErrorAction Stop
        } catch {
            $data = @{ }
        }
    }
    $data.ffmpeg_path = $FfmpegPath
    $data.ffprobe_path = $FfprobePath
    $json = $data | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($SettingsJson, $json, (New-Object System.Text.UTF8Encoding($false)))
    Write-Ok ('Wpisano sciezki ffmpeg do: {0}' -f $SettingsJson)
}

function Install-FFmpegTools {
    param([string]$ToolsDir)
    $ffmpegExe = Join-Path $ToolsDir 'ffmpeg.exe'
    $ffprobeExe = Join-Path $ToolsDir 'ffprobe.exe'
    if ((Test-Path -LiteralPath $ffmpegExe) -and (Test-Path -LiteralPath $ffprobeExe)) {
        Write-Ok 'ffmpeg/ffprobe juz sa w tools/ - pominieto pobieranie.'
    } else {
        New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
        $zip = Join-Path $env:TEMP 'mediasort_ffmpeg.zip'
        $extract = Join-Path $ToolsDir '_ffmpeg_extract'
        $url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
        Write-Step 'Pobieranie ffmpeg (statyczny build, ~90 MB) ...'
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        if (Test-Path -LiteralPath $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
        Write-Step 'Rozpakowywanie ...'
        Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
        $foundFfmpeg = Get-ChildItem -LiteralPath $extract -Recurse -Filter 'ffmpeg.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $foundFfmpeg) {
            throw 'Nie znaleziono ffmpeg.exe w pobranym archiwum.'
        }
        Copy-Item -LiteralPath $foundFfmpeg.FullName -Destination $ffmpegExe -Force
        $foundFfprobe = Join-Path $foundFfmpeg.DirectoryName 'ffprobe.exe'
        if (-not (Test-Path -LiteralPath $foundFfprobe)) {
            throw 'Nie znaleziono ffprobe.exe obok ffmpeg.exe.'
        }
        Copy-Item -LiteralPath $foundFfprobe -Destination $ffprobeExe -Force
        Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        Write-Ok 'ffmpeg/ffprobe zainstalowane w tools/.'
    }
    Set-SettingsToolPaths -FfmpegPath $ffmpegExe -FfprobePath $ffprobeExe
}

# --- wlasciwa instalacja ----------------------------------------------------
Write-Host ''
Write-Host 'MediaSort - instalator dla Windows' -ForegroundColor Cyan
Write-Host ('Katalog projektu: {0}' -f $RepoRoot)
Write-Host ''

try {
    foreach ($required in @($MainPy, $Launcher, $Requirements)) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw ('Nie znaleziono wymaganego pliku: {0}. Skrypt musi byc uruchamiany z katalogu projektu.' -f $required)
        }
    }

    $PythonCmd = Find-SystemPython

    Ensure-Venv -VenvDir $VenvDir -SystemPython $PythonCmd
    Install-Dependencies -VenvPy $VenvPy -Requirements $Requirements
    Ensure-PyInstaller -VenvPy $VenvPy
    Build-Launcher -VenvPy $VenvPy -Launcher $Launcher -ExePath $ExePath -VenvDir $VenvDir

    if ($WithFFmpeg) {
        Install-FFmpegTools -ToolsDir $ToolsDir
    }

    $Extensions = Get-MediaExtensions
    Add-MediaSortAssociations -ExePath $ExePath -Extensions $Extensions

    Write-Host ''
    Write-Host 'Instalacja zakonczona pomyslnie.' -ForegroundColor Green
    Write-Host ('  - MediaSort.exe : {0}' -f $ExePath)
    Write-Host ('  - venv          : {0}' -f $VenvDir)
    Write-Host ('  - typy plikow   : {0}' -f ($Extensions -join ' '))
    if ($WithFFmpeg) {
        Write-Host ('  - ffmpeg        : {0}' -f (Join-Path $ToolsDir 'ffmpeg.exe'))
    } else {
        Write-Host ''
        Write-Host ('Wycinanie wideo (klawisz X): bez -WithFFmpeg funkcja wymaga ffmpeg.')
        Write-Host ('  - uruchom ponownie:  powershell -NoProfile -ExecutionPolicy Bypass')
        Write-Host ('       -File install_windows.ps1 -WithFFmpeg')
        Write-Host '  - albo zainstaluj ffmpeg systemowo / wpisz sciezki w mediasort/settings.json.'
    }
    Write-Host ''
    Write-Host 'Dwuklik na obrazek/wideo albo prawy przycisk -> Otworz za pomoca -> MediaSort.'
    Write-Host ''
    Write-Host 'Aby MediaSort byl DOMYSLNA aplikacja dla danego typu (opcjonalnie):' -ForegroundColor Yellow
    Write-Host '  prawy przycisk na plik -> Otworz za pomoca -> Wybierz inna aplikacje ->'
    Write-Host '  MediaSort -> zaznacz "Zawsze". Windows chroni domyslne skojarzenia,'
    Write-Host '  wiec instalator swiadomie ich nie nadpisuje.'
    Write-Host ''
    Write-Host 'Aktualizacja kodu po "git pull" nie wymaga reinstalacji (exe uruchamia kod z repo).'
    Write-Host 'Aktualizacja pakietow:  .venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt'
    Write-Host 'Odinstalowanie:          uninstall_windows.cmd'
} catch {
    Write-Host ''
    Write-Host 'BLAD:' -ForegroundColor Red
    ($_.Exception.Message -split "`r?`n") | ForEach-Object { Write-Host ('  ' + $_) -ForegroundColor Red }
    Write-Host ('  (zrodlo: ' + $_.InvocationInfo.ScriptLineNumber + ')') -ForegroundColor DarkGray
    Write-Host 'Jesli problem dotyczy budowy exe, artefakty do diagnozy zostaly w: build/ i dist/.'
    exit 1
}