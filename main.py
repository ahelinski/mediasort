#!/usr/bin/env python3
"""MediaSort - pelnoekranowa przegladarka i sorter zdjec/wideo.

Uzycie:
    python main.py [sciezka/do/folderu_lub_pliku] [--settings sciezka/do/settings.json]

Mozna podac:
  * sciezke do FOLDERU - aplikacja otworzy pierwszy plik multimedialny w nim,
  * sciezke do KONKRETNEGO PLIKU (zdjecia lub wideo) - aplikacja otworzy folder,
    w ktorym plik sie znajduje, i od razu przeskoczy do tego pliku.

Jesli nic nie zostanie podane, uzyty zostanie biezacy katalog.
"""
import sys
import argparse
from pathlib import Path

from PySide6.QtWidgets import QApplication

from mediasort.config import Settings
from mediasort.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="MediaSort - przegladarka i sorter mediow")
    parser.add_argument(
        "path", nargs="?", default=".",
        help="Folder z plikami multimedialnymi, albo sciezka do konkretnego zdjecia/wideo"
    )
    parser.add_argument("--settings", default=None, help="Sciezka do pliku settings.json")
    args = parser.parse_args()

    target = Path(args.path).resolve()
    initial_file = None

    if target.is_file():
        folder = target.parent
        initial_file = str(target)
    elif target.is_dir():
        folder = target
    else:
        print(f"Blad: '{target}' nie jest prawidlowym plikiem ani folderem.")
        sys.exit(1)

    app = QApplication(sys.argv)
    settings = Settings(path=args.settings)
    window = MainWindow(str(folder), settings, initial_file=initial_file)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
