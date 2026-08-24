"""Rutas del stack OCR instalado en esta máquina (Windows 11).

Tesseract se instaló con `winget install UB-Mannheim.TesseractOCR` y poppler con
`winget install oschwartz10612.Poppler`. El idioma español (`spa.traineddata`,
variante *tessdata_best*) NO pudo copiarse a `C:\\Program Files\\Tesseract-OCR\\tessdata`
por falta de permisos de administrador, así que vive en un tessdata propio del
usuario al que apuntamos con `--tessdata-dir`.

Todas las rutas admiten override por variable de entorno para que el pipeline sea
portable a otra máquina sin tocar código.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

TESSERACT_EXE = os.environ.get(
    "OPE_TESSERACT_EXE", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# Sin comillas y con barras normales: pytesseract NO hace shell-quoting del
# parámetro `config`, así que unas comillas aquí llegarían literales a tesseract
# y rompen la apertura del .traineddata.
TESSDATA_DIR = os.environ.get("OPE_TESSDATA_DIR", "C:/Users/User/tessdata")

POPPLER_BIN = os.environ.get(
    "OPE_POPPLER_BIN",
    r"C:\Users\User\AppData\Local\Microsoft\WinGet\Packages"
    r"\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\poppler-25.07.0\Library\bin",
)

IDIOMA = "spa"
DPI = 300
# psm 6 = "un bloque uniforme de texto". Medido contra psm 3 y 4 sobre la página 2
# del cuadernillo de Asturias: psm 6 recupera las 24 opciones y 5 de 6 enunciados,
# psm 3 solo 2 enunciados y 19 opciones.
PSM = 6

RAIZ = Path(__file__).resolve().parent
FUENTES = RAIZ / "fuentes"
CORPUS = RAIZ / "corpus"
CACHE_OCR = RAIZ / "ocr_cache"


def config_tesseract() -> str:
    """Cadena `config` para pytesseract."""
    return f"--tessdata-dir {TESSDATA_DIR} --psm {PSM}"


def comprobar_entorno() -> list[str]:
    """Devuelve la lista de problemas encontrados; vacía si todo está listo."""
    problemas: list[str] = []

    if not Path(TESSERACT_EXE).is_file():
        problemas.append(f"no encuentro tesseract en {TESSERACT_EXE}")

    traineddata = Path(TESSDATA_DIR) / f"{IDIOMA}.traineddata"
    if not traineddata.is_file():
        problemas.append(f"falta {traineddata} (idioma '{IDIOMA}')")

    if not (Path(POPPLER_BIN) / "pdftoppm.exe").is_file() and not shutil.which("pdftoppm"):
        problemas.append(f"no encuentro pdftoppm (poppler) en {POPPLER_BIN}")

    return problemas
