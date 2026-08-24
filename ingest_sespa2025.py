"""Extrae el bloque autonómico de los exámenes del SESPA de noviembre de 2025.

De las 15 preguntas comunes del examen, las estatales ya están cubiertas por el
corpus de otras comunidades —el hecho evaluado es idéntico en toda España— y
volver a capturarlas solo inflaría las frecuencias. Las autonómicas no tienen
transferencia ninguna: ninguna pregunta de otra comunidad sirve para el Estatuto
de Autonomía del Principado o la estructura del SESPA.

Estos exámenes son del mismo ciclo OPE 2022-2023-2024 y del mismo organismo, así
que comparten literalmente la parte general con Fisioterapia: es la fuente más
reciente que existe de ese bloque.

    python ingest_sespa2025.py --dry-run
    python ingest_sespa2025.py --out corpus/corpus_autonomico_sespa2025.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from clasificar_temas import clasificar
from plantillas import leer_rejilla

RAIZ = Path(__file__).resolve().parent
# Los cuadernillos se leen del OCR a dos columnas; el de página entera intercala
# las columnas y es inservible.
TEXTO = RAIZ / "raw" / "texto_col"
PLANTILLAS = RAIZ / "raw" / "plantillas"

FECHAS = {"aux_administrativo": "2025-11-09", "enfermeria": "2025-11-09",
          "higienista": "2025-11-08", "tcae": "2025-11-08",
          "trabajador_social": "2025-11-09", "celador": "2025-11-08",
          "ayudante_servicios": "2025-11-08", "jefe_taller": "2025-11-08"}
NOMBRES = {"aux_administrativo": "Auxiliar Administrativo", "enfermeria": "Enfermería",
           "higienista": "Higienista Dental", "tcae": "TCAE",
           "trabajador_social": "Trabajador/a Social", "celador": "Celador",
           "ayudante_servicios": "Ayudante de Servicios", "jefe_taller": "Jefe de Taller"}

# Inicio de pregunta en el texto OCR: número + separador. Se admiten homoglifos
# porque el OCR confunde 1 con l o |, igual que en el cuadernillo de 2019.
RE_PREGUNTA = re.compile(r"^\s*([0-9IilO|]{1,3})\s*[\.\-\)]\s*(?=\S)")
RE_OPCION = re.compile(r"^\s*([a-dA-D])\s*[\)\.\-]\s*(?=\S)")
_HOMOGLIFOS = str.maketrans({"|": "1", "I": "1", "i": "1", "l": "1", "O": "0", "o": "0"})

# Lo que hace autonómica a una pregunta: norma, órgano o territorio del Principado.
RE_AUTONOMICO = re.compile(
    r"principado de asturias|\basturias\b|asturiano|estatuto de autonomia"
    r"|junta general|consejeria de (salud|sanidad)|\bsespa\b|servicio de salud del principado"
    r"|areas? sanitarias?|\bbopa\b|ley del principado|\b7/2019\b|\b189/2023\b"
    r"|\b51/2019\b|\b7/2013\b|mapa sanitario|zona basica de salud"
    r"|establecimientos residenciales|\bera\b|oviedo|gijon|aviles",
    re.IGNORECASE)

UMBRAL_JACCARD = 0.5


def norm(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


PALABRAS_VACIAS = {
    "de", "la", "el", "los", "las", "un", "una", "y", "o", "que", "en", "del", "al",
    "por", "para", "con", "se", "es", "son", "su", "sus", "lo", "a", "cual", "cuales",
    "señale", "senale", "indique", "respuesta", "correcta", "incorrecta", "siguientes",
    "segun", "sobre", "the", "no", "si", "ser", "esta", "este", "estos",
}


def tokens(texto: str) -> set[str]:
    limpio = re.sub(r"[^a-z0-9ñ ]", " ", norm(texto))
    return {t for t in limpio.split() if len(t) > 2 and t not in PALABRAS_VACIAS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def a_numero(token: str) -> int | None:
    limpio = token.translate(_HOMOGLIFOS)
    return int(limpio) if limpio.isdigit() else None


def parsear_cuadernillo(ruta: Path) -> tuple[list[dict], list[str]]:
    """Trocea el texto OCR en preguntas con sus cuatro opciones."""
    preguntas: list[dict] = []
    avisos: list[str] = []
    actual: dict | None = None
    esperado = 1

    for linea in ruta.read_text(encoding="utf-8").split("\n"):
        linea = linea.strip()
        if not linea or linea.startswith("====="):
            continue

        m = RE_PREGUNTA.match(linea)
        num = a_numero(m.group(1)) if m else None
        if num is not None and esperado <= num <= esperado + 3:
            if num > esperado:
                avisos.append(f"salto de numeración: esperaba {esperado}, vino {num}")
            if actual:
                preguntas.append(actual)
            actual = {"numero": num, "enunciado": linea[m.end():].strip(), "opciones": {}}
            esperado = num + 1
            continue

        if actual is None:
            continue

        m_op = RE_OPCION.match(linea)
        letra = m_op.group(1).lower() if m_op else None
        # La letra tiene que ser la que toca: una "a)" suelta dentro de un texto
        # no abre opción nueva.
        n_op = len(actual["opciones"])
        if letra and n_op < 4 and letra == "abcd"[n_op]:
            actual["opciones"][letra] = linea[m_op.end():].strip()
        elif actual["opciones"]:
            ultima = list(actual["opciones"])[-1]
            actual["opciones"][ultima] = f"{actual['opciones'][ultima]} {linea}".strip()
        else:
            actual["enunciado"] = f"{actual['enunciado']} {linea}".strip()

    if actual:
        preguntas.append(actual)
    return preguntas, avisos


def leer_rejilla_escaneada(pdf: Path) -> dict[int, str]:
    """Lee una plantilla escaneada que viene como tabla con bordes.

    Tesseract no sabe leer estas rejillas de corrido: toma los bordes de las
    celdas por caracteres y devuelve basura. Pero cada columna de letras, aislada,
    es una lista vertical que lee perfectamente. Así que se buscan solo las letras
    A-D, se agrupan por su posición horizontal en columnas y se ordenan por altura;
    la numeración se deduce del orden, que en estas plantillas es siempre
    consecutivo por columnas.
    """
    from pdf2image import convert_from_path
    import pytesseract
    import ocr_config as cfg

    pytesseract.pytesseract.tesseract_cmd = cfg.TESSERACT_EXE
    config = (f"--tessdata-dir {cfg.TESSDATA_DIR} --psm 6 "
              f"-c tessedit_char_whitelist=ABCD")

    letras: list[str] = []
    for img in convert_from_path(str(pdf), dpi=300, poppler_path=cfg.POPPLER_BIN):
        datos = pytesseract.image_to_data(img, lang="spa", config=config,
                                          output_type=pytesseract.Output.DICT)
        tokens = [(datos["left"][i], datos["top"][i], datos["text"][i].strip())
                  for i in range(len(datos["text"]))
                  if datos["text"][i].strip() in ("A", "B", "C", "D")
                  and float(datos["conf"][i]) > 30]
        if not tokens:
            continue

        # Agrupar en columnas: un salto grande en X separa un bloque del siguiente.
        xs = sorted({x for x, _, _ in tokens})
        cortes, anterior = [], xs[0]
        for x in xs[1:]:
            if x - anterior > img.width * 0.06:
                cortes.append((anterior + x) / 2)
            anterior = x
        limites = [0] + cortes + [img.width]

        for i in range(len(limites) - 1):
            columna = [t for t in tokens if limites[i] <= t[0] < limites[i + 1]]
            letras += [t[2] for t in sorted(columna, key=lambda t: t[1])]

    return {n: l for n, l in enumerate(letras, start=1)}


def leer_plantilla(categoria: str) -> dict[int, str]:
    """Plantilla de respuestas: del PDF si tiene texto, del OCR si venía escaneada."""
    pdf = PLANTILLAS / f"sespa2025_{categoria}_plantilla.pdf"
    respuestas: dict[int, str] = {}
    if pdf.is_file():
        respuestas = {k: v for k, v in leer_rejilla(pdf).items() if v}

    # Menos de diez respuestas significa que el PDF venía escaneado y no que la
    # plantilla sea corta: se relee la rejilla por columnas.
    if len(respuestas) < 10 and pdf.is_file():
        respuestas = leer_rejilla_escaneada(pdf)

    # La rectificación se aplica encima de la plantilla base, nunca al revés.
    rect = PLANTILLAS / f"sespa2025_{categoria}_rectificacion_plantilla.pdf"
    if rect.is_file():
        respuestas.update({k: v for k, v in leer_rejilla(rect).items() if v})
    return respuestas


def clasificar_ambito(pregunta: dict) -> tuple[str, str | None]:
    """estatal | autonomico, con el fragmento que lo justifica."""
    texto = pregunta["enunciado"] + " " + " ".join(pregunta["opciones"].values())
    m = RE_AUTONOMICO.search(norm(texto))
    if m:
        ini = max(0, m.start() - 30)
        return "autonomico", texto[ini:m.end() + 40].strip()
    return "estatal", None


def asignar_hechos(preguntas: list[dict]) -> None:
    """Agrupa por hecho evaluado, no por enunciado.

    Las categorías comparten temario general, así que el mismo hecho aparece con
    distinta redacción. Se conservan todas las variantes bajo un `hecho_id`
    común: al tribunal le gusta reciclar formulación.
    """
    grupos: list[tuple[set[str], str]] = []
    for p in preguntas:
        t = tokens(p["enunciado"])
        for toks, hid in grupos:
            if jaccard(t, toks) >= UMBRAL_JACCARD:
                p["hecho_id"] = hid
                break
        else:
            hid = f"H_{len(grupos) + 1:03d}"
            grupos.append((t, hid))
            p["hecho_id"] = hid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=RAIZ / "corpus" / "corpus_autonomico_sespa2025.jsonl")
    ap.add_argument("--generales", type=int, default=None,
                    help="tamaño del bloque general, si se conoce por las bases")
    ap.add_argument("--muestra", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    salida: list[dict] = []
    informe: list[str] = []
    muestras: list[str] = []

    for txt in sorted(TEXTO.glob("sespa2025_*.txt")):
        if "plantilla" in txt.stem or "rectificacion" in txt.stem:
            continue
        categoria = txt.stem.replace("sespa2025_", "")

        preguntas, avisos = parsear_cuadernillo(txt)
        plantilla = leer_plantilla(categoria)

        if not plantilla:
            informe.append(f"{categoria:20} SIN PLANTILLA — descartada")
            continue

        limite = args.generales
        generales = [p for p in preguntas if p["numero"] <= limite]

        # El cruce va por NÚMERO de pregunta, nunca por posición en la lista: así
        # una pregunta que el OCR no haya recuperado deja un hueco, pero no
        # desplaza el emparejamiento de las demás. Lo que sí se exige es que el
        # bloque general esté completo, que es lo único que se va a ingerir.
        faltan = [n for n in range(1, limite + 1)
                  if n not in {p["numero"] for p in generales}]
        fuera = [p["numero"] for p in preguntas if p["numero"] not in plantilla]
        if faltan:
            informe.append(f"{categoria:20} ABORTADA — faltan del bloque general: {faltan}")
            continue
        if fuera:
            informe.append(f"{categoria:20} ABORTADA — números fuera de la plantilla: "
                           f"{fuera[:6]}")
            continue
        autonomicas = []
        for p in generales:
            ambito, evidencia = clasificar_ambito(p)
            if ambito != "autonomico":
                continue
            resp = plantilla.get(p["numero"], "").lower()
            if resp not in ("a", "b", "c", "d"):
                continue
            if len(p["opciones"]) != 4:
                continue
            p.update({"ambito": ambito, "evidencia": evidencia,
                      "respuesta_correcta": resp, "categoria": categoria})
            autonomicas.append(p)

        asignar_hechos(autonomicas)
        for p in autonomicas:
            # El temario literal está en el repo (docs/temario_44.md), así que el
            # tema se mapea de verdad. Si el clasificador no decide o devuelve un
            # tema específico, se deja a null antes que inventar la taxonomía.
            tema, _, _ = clasificar(p["enunciado"], list(p["opciones"].values()))
            salida.append({
                "id": f"sespa2025_{categoria}_{p['numero']:03d}",
                "fuente": "SESPA",
                "categoria": NOMBRES.get(categoria, categoria),
                "fecha_examen": FECHAS.get(categoria),
                "ciclo_ope": "2022-2023-2024",
                "bloque": "general",
                "ambito": "autonomico",
                "tema": f"T{tema}" if tema and tema <= 11 else None,
                "hecho_id": p["hecho_id"],
                "enunciado": p["enunciado"],
                "opciones": p["opciones"],
                "respuesta_correcta": p["respuesta_correcta"],
                "plantilla": "provisional",
                "kappa": 1.0,
            })

        estatales = len(generales) - len(autonomicas)
        informe.append(f"{categoria:20} {len(preguntas):3d}/{len(plantilla)} parseadas · "
                       f"general 1-{limite} completo · autonómicas {len(autonomicas):2d} · "
                       f"estatales {estatales:2d}"
                       + (f" · {len(avisos)} avisos" if avisos else ""))
        for p in autonomicas[:args.muestra]:
            muestras.append(f"  [{categoria} {p['numero']}] {p['enunciado'][:88]}")

    print("=== INFORME ===")
    for l in informe:
        print(l)
    hechos = len({r["hecho_id"] for r in salida})
    print(f"TOTAL autonómicas: {len(salida)} en {hechos} hechos distintos")
    if muestras:
        print("=== MUESTRA para revisión manual ===")
        for m in muestras[:args.muestra * 4]:
            print(m)

    if args.dry_run:
        print("[--dry-run] no se ha escrito nada")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in salida:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"escritas {len(salida)} preguntas en {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
