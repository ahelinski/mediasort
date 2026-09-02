#!/usr/bin/env python3
"""Windows launcher dla MediaSort (budowany przez install_windows.ps1).

Ten plik jest opakowywany przez PyInstaller w plik MediaSort.exe. Jego jedynym
zadaniem jest uruchomienie wlasciwej aplikacji z venv:

    .venv\\Scripts\\pythonw.exe main.py [argumenty...]

Dzieki temu Windows (skojarzenia plikow, menu "Otworz za pomoca") widzi
prawdziwy plik wykonywalny .exe, a cala logika i biblioteki (PySide6) zyja
w venv - dokladnie tak, jak na Linuksie ms.desktop wskazuje na .venv/bin/python3.
"""
import subprocess
import sys
from pathlib import Path


def _repo_root():
    """Katalog z glownym plikiem main.py (tam, gdzie lezy MediaSort.exe)."""
    if getattr(sys, "frozen", False):
        # Uruchomiony jako MediaSort.exe (PyInstaller).
        return Path(sys.executable).resolve().parent
    # Uruchomiony bezposrednio przez Pythona (tryb deweloperski).
    return Path(__file__).resolve().parent.parent.parent


def _show_error(title, text):
    """Natywne okienko bledu (dziala tylko na Windows)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def main():
    root = _repo_root()
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    main_py = root / "main.py"
    if not pythonw.is_file() or not main_py.is_file():
        _show_error(
            "MediaSort",
            "Nie mozna uruchomic MediaSort.\n\n"
            "Brakuje plikow instalacji w katalogu:\n"
            + str(root)
            + "\n\n"
            + ("Brak .venv\\Scripts\\pythonw.exe" if not pythonw.is_file() else "Brak main.py")
            + "\n\nUruchom install_windows.cmd, aby zainstalowac aplikacje.",
        )
        return 1

    cmd = [str(pythonw), str(main_py)] + sys.argv[1:]
    try:
        proc = subprocess.run(cmd, cwd=str(root))
    except OSError as exc:
        _show_error("MediaSort", "Nie udalo sie uruchomic aplikacji:\n" + str(exc))
        return 1
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
