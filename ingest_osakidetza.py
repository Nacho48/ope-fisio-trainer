"""Ingesta de las baterías de Osakidetza (200 comunes + 500 específicas).

Estos dos PDF **no publican la respuesta correcta**. Está comprobado: la negrita
marca el enunciado (99-100 % de sus caracteres) y no las opciones (0,3 %), no hay
anotaciones ni subrayados, y el documento termina en la última pregunta sin
solucionario. Entran por tanto con `resp: null` y `resp_verificada: false`, y
`schema.SoloVerificadas` se encarga de que no toquen ningún cálculo de respuesta.

Esa misma negrita es lo que usamos para trocear: es una señal mucho más fiable
que la numeración, que en el fichero de 500 trae tres erratas de imprenta
(`100.-` por 110, `253.-` por 353 y un `233.` sin guion). Se corrigen aquí.

    python ingest_osakidetza.py --out corpus/corpus_osakidetza.jsonl
    python ingest_osakidetza.py --dry-run
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

# Un enunciado va en negrita de punta a punta; una opción, nunca.
UMBRAL_NEGRITA = 0.5

# El punto tras el número es obligatorio. Sin él, una continuación de enunciado en
# negrita como "26 de junio, de Ordenación Sanitaria de Euskadi…" abriría una
# pregunta fantasma. El guion sí es opcional: la 233 del fichero de 500 va sin él.
RE_NUMERO = re.compile(r"^\s*(\d{1,3})\s*\.\s*-?\s+(?=\S)")
RE_OPCION = re.compile(r"^\s*([a-d])\)\s*")

FICHEROS = [
    {
        "pdf": "osakidetza_comun_200.pdf",
        "bloque": "comun",
        "id_prefix": "OSAKIDETZA-COMUN",
        "esperadas": 200,
    },
    {
        "pdf": "osakidetza_especifico_500.pdf",
        "bloque": "especifico",
        "id_prefix": "OSAKIDETZA-ESP",
        "esperadas": 500,
    },
]

META = {
    "org": "Osakidetza",
    "ccaa": "País Vasco",
    # Baterías de preguntas publicadas como material de la OPE; los PDF no llevan
    # fecha de examen y no se la inventamos.
    "fecha": None,
    "turno": None,
}


@dataclass
class Pregunta:
    num: int
    num_impreso: int
    enunciado: str = ""
    opciones: list[str] = field(default_factory=list)
    pagina: int = 0


def lineas_con_negrita(pagina) -> list[tuple[str, float]]:
    """Agrupa los caracteres de la página en líneas y mide su proporción de negrita."""
    agrupadas: dict[int, list] = {}
    for ch in pagina.chars:
        agrupadas.setdefault(round(ch["top"] / 3), []).append(ch)

    lineas = []
    for clave in sorted(agrupadas):
        chars = sorted(agrupadas[clave], key=lambda c: c["x0"])
        texto = "".join(c["text"] for c in chars).strip()
        if not texto:
            continue
        negrita = sum(1 for c in chars if "Bold" in c.get("fontname", ""))
        lineas.append((texto, negrita / len(chars)))
    return lineas


def parsear(pdf: Path, esperadas: int) -> tuple[list[Pregunta], list[str]]:
    """Trocea el PDF en preguntas y corrige la numeración impresa.

    Va en tres pasadas a propósito. Renumerar sobre la marcha, dando por buena la
    secuencia esperada, hace que un falso positivo se disfrace de "errata
    corregida" y el informe salga limpio estando roto. Aquí se trocea primero
    conservando el número impreso, se descartan después los bloques que no traen
    opciones (que no son preguntas) y solo al final se renumera y se declara qué
    números no cuadraban.
    """
    # --- pasada 1: trocear, conservando la numeración impresa tal cual ---------
    bloques: list[Pregunta] = []
    actual: Pregunta | None = None

    with pdfplumber.open(pdf) as doc:
        for n_pag, pagina in enumerate(doc.pages, start=1):
            for texto, prop_negrita in lineas_con_negrita(pagina):
                es_negrita = prop_negrita >= UMBRAL_NEGRITA
                m_num = RE_NUMERO.match(texto) if es_negrita else None

                if m_num:
                    impreso = int(m_num.group(1))
                    if actual is not None:
                        bloques.append(actual)
                    actual = Pregunta(num=0, num_impreso=impreso, pagina=n_pag)
                    actual.enunciado = texto[m_num.end():].strip()
                    continue

                if actual is None:  # cabeceras previas a la primera pregunta
                    continue

                m_opt = RE_OPCION.match(texto)
                if m_opt and not es_negrita:
                    actual.opciones.append(texto[m_opt.end():].strip())
                    continue

                # Continuación: en negrita sigue el enunciado; si no, la opción abierta.
                if actual.opciones and not es_negrita:
                    actual.opciones[-1] = f"{actual.opciones[-1]} {texto}".strip()
                else:
                    actual.enunciado = f"{actual.enunciado} {texto}".strip()

    if actual is not None:
        bloques.append(actual)

    # --- pasada 2: un bloque sin opciones no era una pregunta -----------------
    avisos: list[str] = []
    preguntas: list[Pregunta] = []
    for bloque in bloques:
        if not bloque.opciones and preguntas:
            avisos.append(
                f"pág. {bloque.pagina}: '{bloque.num_impreso}.' sin opciones; "
                f"se reintegra al enunciado anterior"
            )
            anterior = preguntas[-1]
            anterior.enunciado = (
                f"{anterior.enunciado} {bloque.num_impreso}. {bloque.enunciado}".strip()
            )
            continue
        preguntas.append(bloque)

    # --- pasada 3: renumerar y declarar las erratas de imprenta ---------------
    for posicion, p in enumerate(preguntas, start=1):
        p.num = posicion
        if p.num_impreso != posicion:
            avisos.append(
                f"pág. {p.pagina}: el PDF numera '{p.num_impreso}' donde corresponde "
                f"{posicion}; se ingiere como {posicion}"
            )

    if len(preguntas) != esperadas:
        avisos.append(
            f"AVISO: {len(preguntas)} preguntas troceadas, {esperadas} esperadas"
        )
    return preguntas, avisos


def a_registro(p: Pregunta, meta: dict) -> dict:
    """Registro del corpus. `resp` va a null por obligación, no por descuido."""
    return {
        "id": f"{meta['id_prefix']}-{p.num:03d}",
        "org": META["org"],
        "ccaa": META["ccaa"],
        "fecha": META["fecha"],
        "turno": META["turno"],
        "num": p.num,
        "bloque": meta["bloque"],
        "q": p.enunciado,
        "opts": p.opciones,
        "resp": None,
        "resp_verificada": False,
        "conf": 1.0,  # texto nativo del PDF: la extracción es exacta
        "origen": "pdf_texto",
        # Baterías de estudio, no un examen con reglas de corrección: la
        # penalización no consta. Un 0.0 afirmaría que no penaliza.
        "penalizacion": None,
        "reserva": False,
        "revisar": False,
        # Se guarda la numeración original para poder rastrear las erratas de imprenta.
        "num_impreso": p.num_impreso,
    }


def informe(nombre: str, preguntas: list[Pregunta], esperadas: int,
            correcciones: list[str]) -> str:
    nums = [p.num for p in preguntas]
    huecos = sorted(set(range(1, esperadas + 1)) - set(nums))
    mal_opts = [(p.num, len(p.opciones)) for p in preguntas if len(p.opciones) != 4]
    vacias = [p.num for p in preguntas if len(p.enunciado) < 15]

    lineas = [
        f"== {nombre} ==",
        f"preguntas          : {len(preguntas)} de {esperadas} esperadas",
        f"con 4 opciones     : {len(preguntas) - len(mal_opts)}",
        f"huecos             : {huecos or 'ninguno'}",
        f"enunciados cortos  : {vacias or 'ninguno'}",
        f"erratas corregidas : {len(correcciones)}",
    ]
    for c in correcciones:
        lineas.append(f"   · {c}")
    for num, n in mal_opts[:10]:
        lineas.append(f"   ! nº {num}: {n} opciones")
    if len(mal_opts) > 10:
        lineas.append(f"   ! … y {len(mal_opts) - 10} más con nº de opciones != 4")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=cfg.CORPUS / "corpus_osakidetza.jsonl")
    ap.add_argument("--informe", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    registros: list[dict] = []
    partes: list[str] = []

    for meta in FICHEROS:
        pdf = cfg.FUENTES / meta["pdf"]
        if not pdf.is_file():
            print(f"ERROR: no encuentro {pdf}", file=sys.stderr)
            return 2
        preguntas, correcciones = parsear(pdf, meta["esperadas"])
        partes.append(informe(meta["pdf"], preguntas, meta["esperadas"], correcciones))
        registros += [a_registro(p, meta) for p in preguntas]

    texto = "\n\n".join(partes)
    print(texto)
    print(f"\nTOTAL a ingerir: {len(registros)} preguntas, "
          f"todas con resp=null y resp_verificada=false")

    if args.dry_run:
        print("\n[--dry-run] no se ha escrito nada")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in registros:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"escritas {len(registros)} preguntas en {args.out}")

    if args.informe:
        args.informe.write_text(texto, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
