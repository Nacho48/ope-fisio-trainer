"""Lectura de las plantillas oficiales de respuestas.

Asturias y el SAS publican la misma forma de rejilla: filas de pares
`número letra` repartidos en varias columnas (Asturias 4 bloques de 25, el SAS 4
bloques de 50). Extraído el texto, ambas se recorren igual — por pares — así que
la función es una sola.

Asturias marca las preguntas anuladas con el literal `ANULADA` en lugar de letra;
esas entran en el corpus con `resp: null` y `resp_verificada: false`.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

LETRAS_VALIDAS = ("A", "B", "C", "D")
MARCA_ANULADA = "ANULADA"


def leer_rejilla(pdf: Path) -> dict[int, str | None]:
    """Devuelve {número de pregunta: letra}. Las anuladas quedan como None."""
    with pdfplumber.open(pdf) as doc:
        texto = "\n".join(pagina.extract_text() or "" for pagina in doc.pages)

    respuestas: dict[int, str | None] = {}
    for linea in texto.split("\n"):
        piezas = linea.split()
        i = 0
        while i < len(piezas) - 1:
            if piezas[i].isdigit():
                valor = piezas[i + 1].upper()
                if valor in LETRAS_VALIDAS:
                    respuestas[int(piezas[i])] = valor
                    i += 2
                    continue
                if valor == MARCA_ANULADA:
                    respuestas[int(piezas[i])] = None
                    i += 2
                    continue
            i += 1
    return respuestas
