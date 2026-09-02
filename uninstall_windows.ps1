# ============================================================================
# MediaSort - dezinstalator dla systemu Windows.
#
# Usuwa to, co stworzyl install_windows.ps1:
#   1. wpisy rejestru "Otworz za pomoca" zalozone przez instalatora
#      (ProgID "MediaSort.Media", wpisy OpenWithProgids dla obrazow/wideo
#      oraz klucz HKCU\Software\Classes\Applications\MediaSort.exe),
#   2. plik MediaSort.exe (launcher zbudowany przez PyInstaller),
#   3. venv ".venv" (wraz z zainstalowanymi zaleznosciami),
#   4. artefakty budowy, ktore mogl zostawic przerwany instalator.
#
# NIE usuwa: kodu zrodlowego repo ani danych aplikacji (mediasort/settings.json,
# mediasort/tags.db, logi) - chyba ze podasz -DeleteData.
#
# Instalator nigdy nie nadpisuje domyslnych skojarzen innych programow, wiec
# nie ma czego "przywracac": dezinstalator usuwa wylacznie wlasne wpisy.
# Jesli wczesniej wybrano MediaSort jako program domyslny (UserChoice),
# Windows sam zaproponuje wybor programu przy nastepnym otwarciu pliku.
#
# Uruchamianie:   dwuklik na uninstall_windows.cmd
#     albo:       powershell -NoProfile -ExecutionPolicy Bypass -File uninstall_windows.ps1
#     opcje:      -Force      - nie pytaj o zamykanie aplikacji
#                 -DeleteData - usun rowniez dane aplikacji (ustawienia, tagi, logi)
# ============================================================================

param(
    [switch]$Force,
    [switch]$DeleteData
)

$ErrorActionPreference = 'Continue'

# --- sciezki ---------------------------------------------------------------
$RepoRoot  = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$VenvDir   = Join-Path $RepoRoot '.venv'
$ExePath   = Join-Path $RepoRoot 'MediaSort.exe'
$ProgId    = 'MediaSort.Media'
$DataFiles = @(
    (Join-Path $RepoRoot 'mediasort\settings.json'),
    (Join-Path $RepoRoot 'mediasort\tags.db'),
    (Join-Path $RepoRoot 'mediasort\log.txt')
)

# --- male helpery ----------------------------------------------------------
function Write-Step { Write-Host ('==> ' + $args[0]) -ForegroundColor Cyan }
function Write-Ok   { Write-Host ('    ' + $args[0]) -ForegroundColor Green }

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
        Write-Host 'Aplikacja MediaSort jest teraz uruchomiona.' -ForegroundColor Yellow
        $ans = Read-Host 'Zamknac ja, aby kontynuowac odinstalowanie? [t/N]'
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
    return @('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tif', '.tiff',
             '.mp4', '.avi', '.mkv', '.mov', '.webm', '.m4v', '.wmv', '.flv')
}

function Remove-MediaSortAssociations {
    param([string[]]$Extensions)
    Write-Step 'Usuwanie wpisow "Otworz za pomoca" z rejestru (HKCU\Software\Classes) ...'
    $classes = 'HKCU:\Software\Classes'

    # ProgID razem z calym poddrzewem (DefaultIcon, shell\open\command).
    Remove-Item -LiteralPath "$classes\$ProgId" -Recurse -Force -ErrorAction SilentlyContinue

    # Wpis z podmenu "Otworz za pomoca" kazdego rozszerzenia.
    foreach ($ext in $Extensions) {
        $owpKey = "$classes\$ext\OpenWithProgids"
        if (Test-Path -LiteralPath $owpKey) {
            Remove-ItemProperty -LiteralPath $owpKey -Name $ProgId -ErrorAction SilentlyContinue
        }
    }

    # Wpis z listy "Wybierz inna aplikacje".
    Remove-Item -LiteralPath "$classes\Applications\MediaSort.exe" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok 'Wpisy rejestru usuniete.'
}

# --- odinstalowanie ----------------------------------------------------------
Write-Host ''
Write-Host 'MediaSort - dezinstalator (Windows)' -ForegroundColor Cyan
Write-Host ('Katalog projektu: {0}' -f $RepoRoot)
Write-Host ''

if (-not (Stop-MediaSortProcesses -ExePath $ExePath -VenvDir $VenvDir -Force:$Force)) {
    exit 1
}

# 1. Rejestr - najpierw, zeby nie zostawiac "wiszacych" skojarzen.
$Extensions = Get-MediaExtensions
Remove-MediaSortAssociations -Extensions $Extensions

# 2. MediaSort.exe (launcher).
if (Test-Path -LiteralPath $ExePath) {
    Remove-Item -LiteralPath $ExePath -Force -ErrorAction Continue
    Write-Ok ('Usunieto: {0}' -f $ExePath)
} else {
    Write-Ok 'Brak MediaSort.exe - nic do usuniecia.'
}

# 3. venv (.venv) - przy odpalonych procesach bywa zablokowany, wiec z retry.
if (Test-Path -LiteralPath $VenvDir) {
    Write-Step 'Usuwanie venv (.venv) ...'
    $removed = $false
    for ($i = 0; $i -lt 3 -and -not $removed; $i++) {
        try {
            Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction Stop
            $removed = $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if ($removed) { Write-Ok 'venv usuniety.' }
    else { Write-Host 'UWAGA: nie udalo sie w pelni usunac .venv (byc moze zablokowany plik). Usun go recznie.' -ForegroundColor Yellow }
} else {
    Write-Ok 'Brak .venv - nic do usuniecia.'
}

# 4. Artefakty, ktore mogl zostawic przerwany instalator (build/spec + exe w dist).
$stale = @()
if (Test-Path -LiteralPath (Join-Path $RepoRoot 'build\pyinstaller')) { $stale += Join-Path $RepoRoot 'build\pyinstaller' }
if (Test-Path -LiteralPath (Join-Path $RepoRoot 'build\spec'))         { $stale += Join-Path $RepoRoot 'build\spec' }
if (Test-Path -LiteralPath (Join-Path $RepoRoot 'dist\MediaSort.exe')) { $stale += Join-Path $RepoRoot 'dist\MediaSort.exe' }
if (Test-Path -LiteralPath (Join-Path $RepoRoot 'MediaSort.spec'))     { $stale += Join-Path $RepoRoot 'MediaSort.spec' }
foreach ($p in $stale) {
    Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
}
if ($stale.Count -gt 0) { Write-Ok 'Usunieto pozostale artefakty budowy.' }

# 5. Opcjonalnie: dane aplikacji.
if ($DeleteData) {
    if (-not $Force) {
        Write-Host 'Masz zamiar usunac DANE aplikacji (ustawienia, biblioteke tagow, logi):' -ForegroundColor Yellow
        foreach ($f in $DataFiles) { Write-Host ('    - ' + $f) -ForegroundColor Yellow }
        $ans = Read-Host 'Kontynuowac? [t/N]'
        if ($ans -notmatch '^(t|y|tak)$') {
            Write-Host 'Pominieto usuwanie danych.' -ForegroundColor Yellow
            $DeleteData = $false
        } else {
            $DeleteData = $true
        }
    }
    if ($DeleteData) {
        foreach ($f in $DataFiles) {
            if (Test-Path -LiteralPath $f) {
                Remove-Item -LiteralPath $f -Force -ErrorAction Continue
                Write-Ok ('Usunieto: {0}' -f $f)
            }
        }
    }
}

# 6. Odswiezenie cache ikon/skojarzen (best-effort, Win8+).
$ie4uinit = Join-Path $env:WINDIR 'System32\ie4uinit.exe'
if (Test-Path -LiteralPath $ie4uinit) {
    try { & $ie4uinit -show 2>$null | Out-Null } catch { }
}

Write-Host ''
Write-Host 'Odinstalowanie zakonczone.' -ForegroundColor Green
Write-Host '  - usunieto: MediaSort.exe, .venv, wlasne wpisy rejestru.'
Write-Host '  - zostalo: kod zrodlowy projektu (mozesz usunac caly katalog recznie).'
if (-not $DeleteData) {
    Write-Host '  - dane aplikacji (settings.json, tags.db, logi) pozostaly nietkniete.'
}
Write-Host ''
Write-Host ('Jesli MediaSort byl ustawiony jako program domyslny, Windows zaproponuje')
Write-Host 'wybor programu przy nastepnym otwarciu pliku (nie nadpisywalismy wyboru'
Write-Host 'innych programow, wiec nie ma czego przywracac).'
