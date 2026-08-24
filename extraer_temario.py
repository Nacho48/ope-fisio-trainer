"""Extrae el programa (temario) de la convocatoria de Fisioterapeuta del SESPA 2025.

Fuente: BOPA núm. 90 de 13-V-2025, código 2025-03471, Resolución de 28 de abril de
2025 de la Dirección Gerencia del SESPA (33 plazas de Fisioterapeuta).

Ojo con la numeración del anexo: el texto de las bases remite dos veces al
"Anexo III" (base 1.4 y base 7.1), pero en el PDF el programa aparece impreso
como **ANEXO IV** en la página 19 — la misma etiqueta que lleva el anexo de
protección de datos de la página 24. Es una errata del boletín; el contenido es
el que corresponde al Anexo III.

El volcado es literal: no se corrige ortografía, no se resume y no se reordena.

    python extraer_temario.py --out docs/temario_44.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pdfplumber

RAIZ = Path(__file__).resolve().parent
PDF = RAIZ / "fuentes" / "bases_bopa_2025.pdf"

# El programa ocupa de la página 19 hasta antes del anexo de protección de datos.
PAG_INICIO, PAG_FIN = 19, 23

# El discriminante es el COLOR, no la fuente. El logotipo institucional va en la
# fuente `Asturica` y la cabecera en Verdana, ambos en azul, y hay además texto
# blanco invisible; el cuerpo del programa es siempre negro. Sin este filtro, el
# "GOBIERNO" del logo aparece pegado al final del tema 26 —cayó justo entre dos
# temas— y ningún filtro por palabras lo distinguiría de un enunciado legítimo.
#
# Filtrar por fuente NO vale: el cuerpo mezcla Arial y Calibri (el tema 3 continúa
# en Calibri), así que exigir Arial truncaba temas por la mitad.
NEGROS = {"(0.0,)", "(0,)", "0", "0.0", "None"}


def es_cuerpo(obj) -> bool:
    if obj.get("object_type") != "char":
        return True
    return str(obj.get("non_stroking_color")) in NEGROS


RE_TEMA = re.compile(r"^\s*TEMA\s+(\d{1,2})\s*[:.]\s*(.*)$")
RE_SECCION = re.compile(r"^\s*(PARTE GENERAL|TEMARIO ESPEC[ÍI]FICO|PARTE ESPEC[ÍI]FICA)\s*$")
# Cabecera y pie que el BOPA repite en cada página.
RE_RUIDO = re.compile(
    r"^\s*(BOLET[ÍI]N OFICIAL|núm\.\s*\d+|https://sede|\d{4,}-\d{4,}|\.dóC|ANEXO|PROGRAMA)",
    re.IGNORECASE,
)

ESPERADOS = {"PARTE GENERAL": 11, "TEMARIO ESPECÍFICO": 33}


def extraer(pdf: Path) -> dict[str, list[tuple[int, str]]]:
    secciones: dict[str, list[tuple[int, str]]] = {}
    actual_seccion: str | None = None
    numero: int | None = None
    piezas: list[str] = []

    def cerrar() -> None:
        nonlocal numero, piezas
        if actual_seccion and numero is not None:
            texto = re.sub(r"\s+", " ", " ".join(piezas)).strip()
            secciones.setdefault(actual_seccion, []).append((numero, texto))
        numero, piezas = None, []

    with pdfplumber.open(pdf) as doc:
        for pagina in doc.pages[PAG_INICIO - 1:PAG_FIN]:
            texto = pagina.filter(es_cuerpo).extract_text() or ""
            for linea in texto.split("\n"):
                if RE_RUIDO.match(linea) or not linea.strip():
                    continue

                m_sec = RE_SECCION.match(linea)
                if m_sec:
                    cerrar()
                    actual_seccion = ("TEMARIO ESPECÍFICO"
                                      if "ESPEC" in m_sec.group(1).upper()
                                      else "PARTE GENERAL")
                    continue

                m_tema = RE_TEMA.match(linea)
                if m_tema:
                    cerrar()
                    numero = int(m_tema.group(1))
                    piezas = [m_tema.group(2).strip()]
                    continue

                if numero is not None:
                    piezas.append(linea.strip())

    cerrar()
    return secciones


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", type=Path, default=PDF)
    ap.add_argument("--out", type=Path, default=RAIZ / "docs" / "temario_44.md")
    args = ap.parse_args()

    secciones = extraer(args.pdf)

    problemas = []
    for nombre, esperados in ESPERADOS.items():
        temas = secciones.get(nombre, [])
        if len(temas) != esperados:
            problemas.append(f"{nombre}: {len(temas)} temas, se esperaban {esperados}")

    # La numeración del BOPA es continua entre las dos partes: la general va del 1
    # al 11 y la específica arranca en el 12, no vuelve a empezar. Se comprueba
    # así, de corrido, porque es lo que dice el documento.
    todos = [n for nombre in ("PARTE GENERAL", "TEMARIO ESPECÍFICO")
             for n, _ in secciones.get(nombre, [])]
    if todos != list(range(1, len(todos) + 1)):
        problemas.append(f"la numeración corrida no es 1..{len(todos)}: {todos}")

    lineas = [
        "# Temario Fisioterapeuta SESPA 2025",
        "",
        "Transcripción literal del programa de la convocatoria. Fuente: **BOPA núm. 90 "
        "de 13-V-2025**, código 2025-03471, Resolución de 28 de abril de 2025 de la "
        "Dirección Gerencia del SESPA (33 plazas de Fisioterapeuta), páginas 19-23.",
        "",
        "> El texto de las bases remite al **Anexo III** (bases 1.4 y 7.1), pero en el "
        "PDF el programa está impreso como **ANEXO IV** (pág. 19), la misma etiqueta "
        "que el anexo de protección de datos (pág. 24). Es una errata del boletín.",
        "",
        "> «La normativa reguladora de las materias comprendidas en este Programa se "
        "entenderá referida a la vigente el día de la publicación en el BOPA de la "
        "resolución que señale el comienzo de las pruebas.»",
        "",
    ]

    for nombre in ("PARTE GENERAL", "TEMARIO ESPECÍFICO"):
        temas = secciones.get(nombre, [])
        lineas.append(f"## {nombre} ({len(temas)} temas)")
        lineas.append("")
        for n, texto in temas:
            lineas.append(f"{n}. {texto}")
        lineas.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lineas), encoding="utf-8")

    total = sum(len(v) for v in secciones.values())
    for nombre, temas in secciones.items():
        print(f"{nombre}: {len(temas)} temas")
    print(f"TOTAL: {total} (se esperaban 44)")
    print(f"escrito en {args.out}")
    for p in problemas:
        print(f"  ! {p}", file=sys.stderr)
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
