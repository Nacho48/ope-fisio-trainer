"""OCR de los cuadernillos y plantillas del SESPA 2025, que vienen escaneados.

Ninguno de los cinco cuadernillos trae capa de texto, ni cuatro de las ocho
plantillas: son fotocopias publicadas por el sindicato y por astursalud. Se
reutiliza el mismo stack que el cuadernillo de Asturias 2019 (tesseract en
español a 300 dpi), y se cachea el texto para no repetir el OCR en cada prueba
del parser.

    python ocr_sespa2025.py
    python ocr_sespa2025.py --solo tcae
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import ocr_config as cfg
from ocr_asturias import ocr_paginas

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "raw" / "texto"


def ocr_dos_columnas(pdf: Path) -> str:
    """OCR de un cuadernillo maquetado a dos columnas.

    Leída la página entera, tesseract cose las dos columnas línea a línea y sale
    un texto intercalado inservible ("2. Los servicios de salud de las comunidades
    c) Quienes desempeñan funciones"). Partiendo la página por la mitad, cada
    columna es un bloque de texto normal y se lee entera y en orden.
    """
    from pdf2image import convert_from_path
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = cfg.TESSERACT_EXE
    config = cfg.config_tesseract()
    trozos = []
    for n, img in enumerate(convert_from_path(str(pdf), dpi=cfg.DPI,
                                              poppler_path=cfg.POPPLER_BIN), start=1):
        ancho, alto = img.size
        trozos.append(f"\n===== PAGINA {n} =====")
        for recorte in (img.crop((0, 0, ancho // 2, alto)),
                        img.crop((ancho // 2, 0, ancho, alto))):
            trozos.append(pytesseract.image_to_string(recorte, lang=cfg.IDIOMA,
                                                      config=config))
    return "\n".join(trozos)


def procesar(pdf: Path, destino: Path, columnas: bool = False) -> tuple[int, float]:
    salida = destino / f"{pdf.stem}.txt"
    if salida.is_file() and salida.stat().st_size > 200:
        texto = salida.read_text(encoding="utf-8")
        return len(texto), -1.0        # ya estaba en caché

    if columnas:
        texto = ocr_dos_columnas(pdf)
        salida.write_text(texto, encoding="utf-8")
        return len(texto), 0.0

    paginas = ocr_paginas(pdf, cache=None)
    trozos, confs = [], []
    for n, lineas in enumerate(paginas, start=1):
        trozos.append(f"\n===== PAGINA {n} =====")
        for l in lineas:
            trozos.append(l.texto)
            confs.append(l.conf)
    texto = "\n".join(trozos)
    salida.write_text(texto, encoding="utf-8")
    return len(texto), (sum(confs) / len(confs) if confs else 0.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--solo", help="procesa solo los ficheros que contengan esto")
    ap.add_argument("--columnas", action="store_true",
                    help="parte cada página en dos antes del OCR (cuadernillos a 2 columnas)")
    args = ap.parse_args()

    problemas = cfg.comprobar_entorno()
    if problemas:
        for p in problemas:
            print(f"ERROR de entorno: {p}", file=sys.stderr)
        return 2

    DESTINO.mkdir(parents=True, exist_ok=True)
    pdfs = sorted((RAIZ / "raw" / "cuadernillos").glob("*.pdf")) + \
           sorted((RAIZ / "raw" / "plantillas").glob("*.pdf"))
    if args.solo:
        pdfs = [p for p in pdfs if args.solo in p.stem]

    print(f"{'fichero':48} {'chars':>8} {'conf':>6}")
    print("-" * 66)
    for pdf in pdfs:
        print(f"  OCR de {pdf.name}…", file=sys.stderr)
        chars, conf = procesar(pdf, DESTINO, columnas=args.columnas)
        marca = "caché" if conf < 0 else f"{conf:.3f}"
        print(f"{pdf.stem[:48]:48} {chars:8d} {marca:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
