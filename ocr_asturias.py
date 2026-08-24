"""OCR de los PDF escaneados de Asturias 2019 y volcado a JSONL.

`asturias2019_cuadernillo.pdf` (18 págs.) y `asturias2019_correccion_errores.pdf`
(1 pág.) son imagen pura: pdfplumber devuelve 0 caracteres en todas sus páginas.
Este script los rasteriza a 300 dpi, les pasa tesseract en español y reconstruye
las preguntas, casando la respuesta correcta contra la plantilla definitiva.

Toda pregunta que pase por aquí lleva `conf < 1.0`: el OCR mete erratas y el
corpus tiene que poder distinguir lo leído por máquina de lo extraído de una capa
de texto nativa.

    python ocr_asturias.py --out corpus/corpus_asturias2019.jsonl
    python ocr_asturias.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path

import ocr_config as cfg
from plantillas import leer_rejilla

# El OCR nunca produce certeza: aunque tesseract diga 99 %, capamos por debajo de
# 1.0 para que ningún cálculo trate estas preguntas como texto nativo verificado.
CONF_MAX_OCR = 0.99

# Metadatos del examen (BOPA 9-VIII-2018, convocatoria 06/08/2018).
META = {
    "org": "SESPA",
    "ccaa": "Asturias",
    "fecha": "2019-06-15",
    "turno": "libre+PI",
    "id_prefix": "SESPA2019",
}

N_PREGUNTAS_ESPERADAS = 95
N_OPCIONES_ESPERADAS = 4

# Cada fallo resta un quinto del acierto (BOPA 9-VIII-2018, pág. 7).
PENALIZACION = 0.20

# El examen puntuaba 80 preguntas; de la 81 a la 95 eran de reserva. Cuatro de
# ellas (81-84) llegaron a puntuar al sustituir a las anuladas 4, 18, 24 y 79,
# pero se conservan marcadas como reserva: salieron del mismo banco y valen como
# evidencia de qué temas caen.
RESERVA_DESDE = 81

# --- tolerancia a erratas de OCR -------------------------------------------------
# El "1" inicial del cuadernillo sale como "|", "I" o "l" con esta tipografía.
_HOMOGLIFOS = str.maketrans({"|": "1", "I": "1", "i": "1", "l": "1", "O": "0", "o": "0",
                             "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})

# Inicio de enunciado: número (posiblemente con homoglifos) + separador + mayúscula.
# El OCR llega a partir un "11." en "l |.", así que se admiten espacios internos
# dentro del número; el filtro de secuencia de `parsear` descarta los falsos positivos.
RE_ENUNCIADO = re.compile(
    r"^\s*([0-9IilO|SsBZz][0-9IilO|SsBZz ]{0,3})\s*[\.\)\-]\s*(?=[A-ZÁÉÍÓÚÑ¿¡\"«(])"
)
# Inicio de opción: letra a-d (o un dígito mal leído) + paréntesis.
RE_OPCION = re.compile(r"^\s*([a-dA-D0-9|Il])\s*\)\s*")

LETRAS = ("a", "b", "c", "d")


@dataclass
class Linea:
    texto: str
    conf: float
    pagina: int


@dataclass
class Pregunta:
    num: int
    enunciado: str = ""
    opciones: list[str] = field(default_factory=list)
    confs: list[float] = field(default_factory=list)
    pagina: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def conf(self) -> float:
        if not self.confs:
            return 0.0
        return min(sum(self.confs) / len(self.confs), CONF_MAX_OCR)


# --- OCR -------------------------------------------------------------------------

def ocr_paginas(pdf: Path, cache: Path | None = None) -> list[list[Linea]]:
    """Rasteriza el PDF y devuelve, por página, sus líneas con confianza media.

    Usa `image_to_data` en vez de `image_to_string` porque necesitamos la
    confianza palabra a palabra para poder atribuir un `conf` a cada pregunta.
    """
    pytesseract.pytesseract.tesseract_cmd = cfg.TESSERACT_EXE
    imagenes = convert_from_path(str(pdf), dpi=cfg.DPI, poppler_path=cfg.POPPLER_BIN)

    paginas: list[list[Linea]] = []
    for n, img in enumerate(imagenes, start=1):
        datos = pytesseract.image_to_data(
            img, lang=cfg.IDIOMA, config=cfg.config_tesseract(),
            output_type=pytesseract.Output.DICT,
        )
        agrupadas: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
        for i, palabra in enumerate(datos["text"]):
            if not palabra.strip():
                continue
            conf = float(datos["conf"][i])
            if conf < 0:  # tesseract marca así lo que no es texto
                continue
            clave = (datos["block_num"][i], datos["par_num"][i], datos["line_num"][i])
            agrupadas.setdefault(clave, []).append((palabra, conf))

        lineas = []
        for clave in sorted(agrupadas):
            palabras = agrupadas[clave]
            texto = " ".join(p for p, _ in palabras)
            media = sum(c for _, c in palabras) / len(palabras) / 100.0
            lineas.append(Linea(texto=texto, conf=media, pagina=n))

        # El número de página cierra la hoja y, si no se descarta, acaba pegado a
        # la última opción ("Servicio de Farmacia 17"). Solo se quita si la línea
        # final es exclusivamente dígitos: las opciones en números romanos ("I",
        # "I y II") no encajan en ese patrón y se conservan.
        if lineas and re.fullmatch(r"\d{1,3}", lineas[-1].texto.strip()):
            lineas.pop()
        paginas.append(lineas)

        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)
            destino = cache / f"{pdf.stem}_p{n:02d}.txt"
            destino.write_text("\n".join(l.texto for l in lineas), encoding="utf-8")

    return paginas


def _a_numero(token: str) -> int | None:
    """Convierte el token inicial de una línea en número, deshaciendo homoglifos."""
    limpio = token.replace(" ", "").translate(_HOMOGLIFOS)
    return int(limpio) if limpio.isdigit() else None


# --- parseo ----------------------------------------------------------------------

def parsear(paginas: list[list[Linea]], n_esperadas: int) -> tuple[list[Pregunta], list[str]]:
    """Reconstruye las preguntas a partir de las líneas OCR.

    El OCR pierde y deforma caracteres, así que no basta con confiar en el número
    leído: se exige que la numeración avance de forma plausible (el siguiente
    esperado, o como mucho tres más adelante si el OCR se ha comido alguna).
    """
    preguntas: list[Pregunta] = []
    incidencias: list[str] = []
    actual: Pregunta | None = None
    en_opcion = False
    esperado = 1

    for lineas in paginas:
        for linea in lineas:
            texto = linea.texto.strip()
            if not texto:
                continue

            m_enun = RE_ENUNCIADO.match(texto)
            num = _a_numero(m_enun.group(1)) if m_enun else None

            # Solo abrimos pregunta si el número encaja con la secuencia; así un
            # "8." dentro de un enunciado no parte la pregunta en dos.
            if num is not None and esperado <= num <= esperado + 3:
                if num > esperado:
                    incidencias.append(
                        f"salto de numeración: esperaba {esperado}, encontré {num} "
                        f"(pág. {linea.pagina})"
                    )
                if actual is not None:
                    preguntas.append(actual)
                actual = Pregunta(num=num, pagina=linea.pagina)
                actual.enunciado = texto[m_enun.end():].strip()
                actual.confs.append(linea.conf)
                en_opcion = False
                esperado = num + 1
                continue

            if actual is None:  # portada y demás preliminares
                continue

            m_opt = RE_OPCION.match(texto)
            if m_opt and len(actual.opciones) < N_OPCIONES_ESPERADAS:
                leida = m_opt.group(1).lower()
                toca = LETRAS[len(actual.opciones)]
                if leida != toca:
                    actual.avisos.append(f"opción leída '{leida}' donde tocaba '{toca}'")
                actual.opciones.append(texto[m_opt.end():].strip())
                actual.confs.append(linea.conf)
                en_opcion = True
                continue

            # Continuación: pega en la opción abierta o en el enunciado.
            actual.confs.append(linea.conf)
            if en_opcion and actual.opciones:
                actual.opciones[-1] = f"{actual.opciones[-1]} {texto}".strip()
            else:
                actual.enunciado = f"{actual.enunciado} {texto}".strip()

    if actual is not None:
        preguntas.append(actual)

    if preguntas and preguntas[-1].num < n_esperadas:
        incidencias.append(
            f"la última pregunta leída es la {preguntas[-1].num}, se esperaban {n_esperadas}"
        )
    return preguntas, incidencias


# --- plantilla de respuestas -----------------------------------------------------

def leer_plantilla(pdf: Path) -> dict[int, str | None]:
    """Plantilla definitiva: rejilla de 25 filas × 4 bloques (1-25 … 76-95)."""
    return leer_rejilla(pdf)


# --- validación ------------------------------------------------------------------

def validar(preguntas: list[Pregunta], n_esperadas: int) -> dict:
    """Comprueba el contrato: n preguntas correlativas con 4 opciones cada una."""
    numeros = [p.num for p in preguntas]
    huecos = sorted(set(range(1, n_esperadas + 1)) - set(numeros))
    duplicados = sorted({n for n in numeros if numeros.count(n) > 1})

    cuadran, no_cuadran = [], []
    for p in preguntas:
        fallos = []
        if len(p.opciones) != N_OPCIONES_ESPERADAS:
            fallos.append(f"{len(p.opciones)} opciones")
        if len(p.enunciado) < 15:
            fallos.append("enunciado sospechosamente corto")
        if any(len(o) < 2 for o in p.opciones):
            fallos.append("opción vacía o truncada")
        if p.avisos:
            fallos += p.avisos
        (no_cuadran if fallos else cuadran).append((p, fallos))

    return {
        "total": len(preguntas),
        "esperadas": n_esperadas,
        "huecos": huecos,
        "duplicados": duplicados,
        "cuadran": cuadran,
        "no_cuadran": no_cuadran,
        "conf_media": sum(p.conf for p in preguntas) / len(preguntas) if preguntas else 0.0,
        "conf_min": min((p.conf for p in preguntas), default=0.0),
    }


def normalizar_hash(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s)).strip()


def a_registro(p: Pregunta, respuestas: dict[int, str | None],
               revisar: set[int] | None = None) -> dict:
    """Convierte una pregunta OCR en registro del corpus.

    `resp_verificada` es True solo si la plantilla oficial da letra para esa
    pregunta. Las cuatro anuladas (4, 18, 24, 79) se quedan en None/False: están
    en el corpus como enunciado, pero no pueden alimentar ningún cálculo de
    respuesta.
    """
    resp = respuestas.get(p.num)
    return {
        "id": f"{META['id_prefix']}-{p.num:03d}",
        "org": META["org"],
        "ccaa": META["ccaa"],
        "fecha": META["fecha"],
        "turno": META["turno"],
        "num": p.num,
        "bloque": None,
        "q": p.enunciado,
        "opts": p.opciones,
        "resp": resp,
        "resp_verificada": resp is not None,
        "conf": round(p.conf, 4),
        "origen": "ocr",
        "penalizacion": PENALIZACION,
        "reserva": p.num >= RESERVA_DESDE,
        # El OCR deforma los números romanos de algunas opciones ("I y II" ->
        # "y !I"): estas quedan señaladas para repaso humano.
        "revisar": bool(revisar and p.num in revisar),
    }


def informe(res: dict, incidencias: list[str], nombre: str) -> str:
    lineas = [
        f"== {nombre} ==",
        f"preguntas detectadas : {res['total']} de {res['esperadas']} esperadas",
        f"cuadran (4 opciones) : {len(res['cuadran'])}",
        f"NO cuadran           : {len(res['no_cuadran'])}",
        f"huecos de numeración : {res['huecos'] or 'ninguno'}",
        f"duplicados           : {res['duplicados'] or 'ninguno'}",
        f"confianza OCR media  : {res['conf_media']:.3f}  (mínima {res['conf_min']:.3f})",
    ]
    for p, fallos in res["no_cuadran"]:
        lineas.append(f"   · nº {p.num} (pág. {p.pagina}): {'; '.join(fallos)}")
    for inc in incidencias:
        lineas.append(f"   ! {inc}")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=cfg.CORPUS / "corpus_asturias2019.jsonl")
    ap.add_argument("--informe", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true", help="valida sin escribir nada")
    ap.add_argument("--sin-cache", action="store_true", help="no guarda el texto OCR crudo")
    args = ap.parse_args()

    problemas = cfg.comprobar_entorno()
    if problemas:
        for p in problemas:
            print(f"ERROR de entorno: {p}", file=sys.stderr)
        return 2

    cuadernillo = cfg.FUENTES / "asturias2019_cuadernillo.pdf"
    plantilla = cfg.FUENTES / "asturias2019_plantilla_definitiva.pdf"
    erratas = cfg.FUENTES / "asturias2019_correccion_errores.pdf"
    cache = None if args.sin_cache else cfg.CACHE_OCR

    print(f"OCR de {cuadernillo.name} a {cfg.DPI} dpi en '{cfg.IDIOMA}'…", file=sys.stderr)
    paginas = ocr_paginas(cuadernillo, cache)
    preguntas, incidencias = parsear(paginas, N_PREGUNTAS_ESPERADAS)
    res = validar(preguntas, N_PREGUNTAS_ESPERADAS)
    print(informe(res, incidencias, cuadernillo.name))

    respuestas = leer_plantilla(plantilla)
    anuladas = sorted(n for n, v in respuestas.items() if v is None)
    print(f"\nplantilla definitiva : {len(respuestas)} entradas, "
          f"{len(anuladas)} anuladas {anuladas}")
    sin_respuesta = [p.num for p in preguntas if p.num not in respuestas]
    if sin_respuesta:
        print(f"   ! preguntas sin entrada en la plantilla: {sin_respuesta}")

    print(f"\nOCR de {erratas.name}…", file=sys.stderr)
    pags_erratas = ocr_paginas(erratas, cache)
    texto_erratas = "\n".join(l.texto for l in pags_erratas[0])
    conf_erratas = (sum(l.conf for l in pags_erratas[0]) / len(pags_erratas[0])
                    if pags_erratas[0] else 0.0)
    print(f"== {erratas.name} ==")
    print(f"líneas leídas: {len(pags_erratas[0])}, confianza media {conf_erratas:.3f}")
    print("--- contenido íntegro (1 página) ---")
    print(texto_erratas)

    if args.dry_run:
        print("\n[--dry-run] no se ha escrito nada")
        return 0

    revisar = {p.num for p, _ in res["no_cuadran"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for p in preguntas:
            fh.write(json.dumps(a_registro(p, respuestas, revisar), ensure_ascii=False) + "\n")
    print(f"\nescritas {len(preguntas)} preguntas en {args.out} "
          f"({len(revisar)} marcadas para revisión)")

    if args.informe:
        args.informe.write_text(
            informe(res, incidencias, cuadernillo.name), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
