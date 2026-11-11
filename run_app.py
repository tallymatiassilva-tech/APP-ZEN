"""Ponto de entrada do executável (PyInstaller) e atalho para rodar o app."""
import os
import sys

if getattr(sys, "frozen", False):
    # Layouts, ícone e Tesseract são procurados na pasta atual: usa a pasta do .exe.
    os.chdir(os.path.dirname(sys.executable))

from src.app import main  # noqa: E402

if __name__ == "__main__":
    main()
