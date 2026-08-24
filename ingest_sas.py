"""Ingesta del SAS 2025, turno de acceso libre (153 preguntas).

`sas2025_cuadernillo.pdf` trae dos turnos completos: acceso libre en las páginas
1-36 y promoción interna en las 37-72. Cada uno se compone de cuestionario
teórico (1-100), práctico (101-150) y reserva (151-153).

**Solo se ingiere el turno libre**, por dos razones: es el único que cubre
`sas2025_plantilla_libre.pdf` (153 respuestas), y los dos turnos son el mismo
banco de preguntas barajado, así que meter ambos duplicaría las frecuencias de
enunciado — justo la métrica que el corpus existe para medir.

El SAS penaliza cada fallo con ¼ del acierto (portada del cuadernillo), lo que
queda registrado en `penalizacion` para no comparar a ciegas con exámenes que no
restan.

    python ingest_sas.py --out corpus/corpus_sas2025.jsonl
    python ingest_sas.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

import ocr_config as cfg
from plantillas import leer_rejilla

# El enunciado va numerado sin punto ("5 El personal estatutario…"), así que se
# exige mayúscula inicial detrás: sin ese anclaje, cualquier cifra suelta dentro
# de un enunciado abriría una pregunta fantasma.
RE_ENUNCIADO = re.compile(r"^\s*(\d{1,3})\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"«(])")
RE_OPCION = re.compile(r"^\s*([A-D])\)\s*")

LETRAS = ("A", "B", "C", "D")

# El cuestionario práctico agrupa preguntas bajo un caso clínico. Ese texto no es
# una opción: sin cortarlo aquí se pegaría al final de la opción D) de la pregunta
# anterior. Se conserva como `contexto` de las preguntas que vienen detrás, porque
# sin él sus enunciados ("¿qué tratamiento aplicaría?") no se sostienen solos.
RE_CASO = re.compile(r"^\s*CASO\s+PR[ÁA]CTICO\s*\d*\s*:?", re.IGNORECASE)

# Cabeceras y pies que se repiten en cada hoja.
RE_RUIDO = re.compile(
    r"^\s*(P[áa]gina\s+\d+\s+de\s+\d+"
    r"|SAS_FISIOTERAPEUTA.*"
    r"|\d{4}\s+CUESTIONARIO.*"
    r"|(TE[ÓO]RICO|PR[ÁA]CTICO|RESERVA)\s*$"
    r"|PREGUNTAS\s+ACCESO.*)\s*$",
    re.IGNORECASE,
)

# Páginas (base 1) de cada sección del turno libre, medidas sobre el PDF.
SECCIONES = [
    ("teorico", range(3, 22), 1, 100),
    ("practico", range(22, 35), 101, 150),
    ("reserva", range(35, 36), 151, 153),
]

N_ESPERADAS = 153
PRIMERA_RESERVA = 151
PENALIZACION = 0.25  # ¼ del acierto, según la portada del cuadernillo

META = {
    "org": "SAS",
    "ccaa": "Andalucía",
    "fecha": "2025-01-01",
    "turno": "libre",
    "id_prefix": "SAS2025",
}


@dataclass
class Pregunta:
    num: int
    seccion: str
    pagina: int
    enunciado: str = ""
    opciones: list[str] = field(default_factory=list)
    contexto: str | None = None


def parsear(pdf: Path) -> tuple[list[Pregunta], list[str]]:
    """Trocea el turno libre en preguntas, sección a sección.

    Mismo esquema en tres pasadas que el ingestor de Osakidetza: trocear sin
    tocar la numeración, descartar los bloques que no traen opciones (no son
    preguntas) y solo al final comprobar que la numeración es la esperada. Así un
    falso positivo sale en el informe en vez de esconderse tras una renumeración.
    """
    bloques: list[Pregunta] = []
    avisos: list[str] = []

    with pdfplumber.open(pdf) as doc:
        for seccion, paginas, desde, hasta in SECCIONES:
            actual: Pregunta | None = None
            caso: list[str] | None = None  # caso clínico en curso, si lo hay
            contexto_vigente: str | None = None

            for n_pag in paginas:
                texto = doc.pages[n_pag - 1].extract_text() or ""
                for linea in texto.split("\n"):
                    linea = linea.strip()
                    if not linea or RE_RUIDO.match(linea):
                        continue

                    if RE_CASO.match(linea):
                        # Cierra la pregunta en curso y empieza a acumular el caso.
                        if actual is not None:
                            bloques.append(actual)
                            actual = None
                        caso = [linea]
                        continue

                    m_enun = RE_ENUNCIADO.match(linea)
                    if m_enun and desde <= int(m_enun.group(1)) <= hasta:
                        if caso is not None:
                            contexto_vigente = " ".join(caso).strip()
                            caso = None
                        if actual is not None:
                            bloques.append(actual)
                        actual = Pregunta(num=int(m_enun.group(1)), seccion=seccion,
                                          pagina=n_pag, contexto=contexto_vigente)
                        actual.enunciado = linea[m_enun.end():].strip()
                        continue

                    if caso is not None:  # seguimos dentro del enunciado del caso
                        caso.append(linea)
                        continue

                    if actual is None:  # cabecera de sección
                        continue

                    m_opt = RE_OPCION.match(linea)
                    # Solo abre opción la letra que toca: una línea suelta "A)."
                    # es el final de la opción B), no una quinta opción.
                    if m_opt and len(actual.opciones) < len(LETRAS) \
                            and m_opt.group(1) == LETRAS[len(actual.opciones)]:
                        actual.opciones.append(linea[m_opt.end():].strip())
                    elif actual.opciones:
                        actual.opciones[-1] = f"{actual.opciones[-1]} {linea}".strip()
                    else:
                        actual.enunciado = f"{actual.enunciado} {linea}".strip()

            if actual is not None:
                bloques.append(actual)

    preguntas: list[Pregunta] = []
    for bloque in bloques:
        if not bloque.opciones and preguntas:
            avisos.append(f"pág. {bloque.pagina}: '{bloque.num}' sin opciones; "
                          f"se reintegra al enunciado anterior")
            preguntas[-1].enunciado += f" {bloque.num} {bloque.enunciado}"
            continue
        preguntas.append(bloque)

    numeros = [p.num for p in preguntas]
    huecos = sorted(set(range(1, N_ESPERADAS + 1)) - set(numeros))
    if huecos:
        avisos.append(f"faltan las preguntas {huecos}")
    duplicados = sorted({n for n in numeros if numeros.count(n) > 1})
    if duplicados:
        avisos.append(f"números duplicados: {duplicados}")
    return preguntas, avisos


def a_registro(p: Pregunta, respuestas: dict[int, str | None]) -> dict:
    resp = respuestas.get(p.num)
    return {
        "id": f"{META['id_prefix']}-{p.num:03d}",
        "org": META["org"],
        "ccaa": META["ccaa"],
        "fecha": META["fecha"],
        "turno": META["turno"],
        "num": p.num,
        "bloque": p.seccion,
        "q": p.enunciado,
        "opts": p.opciones,
        "resp": resp,
        "resp_verificada": resp is not None,
        "conf": 1.0,  # texto nativo del PDF
        "origen": "pdf_texto",
        "penalizacion": PENALIZACION,
        # Las 151-153 no puntuaron, pero salieron del mismo banco: se conservan
        # como evidencia de qué temas entran.
        "reserva": p.num >= PRIMERA_RESERVA,
        "revisar": False,
        # Caso clínico del que cuelga la pregunta (solo en el cuestionario
        # práctico); sin él, enunciados como "¿qué técnica aplicaría?" no se
        # entienden por sí solos.
        "contexto": p.contexto,
    }


def informe(preguntas: list[Pregunta], respuestas: dict[int, str | None],
            avisos: list[str]) -> str:
    por_seccion: dict[str, list[int]] = {}
    for p in preguntas:
        por_seccion.setdefault(p.seccion, []).append(p.num)

    lineas = [
        "== sas2025_cuadernillo.pdf (turno LIBRE) ==",
        f"preguntas        : {len(preguntas)} de {N_ESPERADAS} esperadas",
    ]
    for seccion, nums in por_seccion.items():
        lineas.append(f"  {seccion:9}: {len(nums):3d}  ({min(nums)}-{max(nums)})")

    mal = [(p.num, len(p.opciones)) for p in preguntas if len(p.opciones) != 4]
    lineas.append(f"con 4 opciones   : {len(preguntas) - len(mal)}")
    lineas.append(f"plantilla libre  : {len(respuestas)} respuestas")
    sin_resp = [p.num for p in preguntas if respuestas.get(p.num) is None]
    lineas.append(f"sin respuesta    : {sin_resp or 'ninguna'}")
    lineas.append(f"de reserva       : {sum(1 for p in preguntas if p.num >= PRIMERA_RESERVA)}")
    lineas.append(f"con caso clínico : {sum(1 for p in preguntas if p.contexto)}")
    lineas.append(f"penalización     : {PENALIZACION} por fallo")
    for num, n in mal[:10]:
        lineas.append(f"   ! nº {num}: {n} opciones")
    for a in avisos:
        lineas.append(f"   ! {a}")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=cfg.CORPUS / "corpus_sas2025.jsonl")
    ap.add_argument("--informe", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cuadernillo = cfg.FUENTES / "sas2025_cuadernillo.pdf"
    plantilla = cfg.FUENTES / "sas2025_plantilla_libre.pdf"
    for ruta in (cuadernillo, plantilla):
        if not ruta.is_file():
            print(f"ERROR: no encuentro {ruta}", file=sys.stderr)
            return 2

    preguntas, avisos = parsear(cuadernillo)
    respuestas = leer_rejilla(plantilla)
    texto = informe(preguntas, respuestas, avisos)
    print(texto)

    if args.dry_run:
        print("\n[--dry-run] no se ha escrito nada")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for p in preguntas:
            fh.write(json.dumps(a_registro(p, respuestas), ensure_ascii=False) + "\n")
    print(f"\nescritas {len(preguntas)} preguntas en {args.out}")

    if args.informe:
        args.informe.write_text(texto, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
