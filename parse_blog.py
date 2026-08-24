"""Extrae preguntas de las páginas guardadas de elcelatagarrapata.blogspot.com.

Cada pregunta es un `<form name="preguntaNN">` y **la respuesta correcta viaja
dentro del propio HTML**, en el `onclick` de cada radio:

    <input name="pregunta01" onclick="respuesta01('Correcto')" type="radio" />

Eso las hace autoverificadas: no hay que cruzar ninguna plantilla, así que entran
con `resp_verificada: true` directamente. Es la fuente que lleva el corpus de
unos cientos de preguntas verificadas a varios miles.

El HTML trae ~2.500 líneas de menús y widgets de Blogger alrededor; solo se mira
lo que hay dentro de los `<form>`. La estructura se recorre con BeautifulSoup, no
con expresiones regulares; estas se reservan para limpiar texto.

    python parse_blog.py fuentes/blog/ --indice indice_examenes.csv \\
        --out corpus/corpus_blog.jsonl --cuarentena corpus/cuarentena.jsonl \\
        --informe docs/informe_blog.txt
    python parse_blog.py fuentes/blog/una-pagina.html --dry-run
"""

from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import random
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, NavigableString, Tag

LETRAS = ("A", "B", "C", "D", "E", "F")
N_OPCIONES_NORMAL = 4

RE_NOMBRE_FORM = re.compile(r"^pregunta_?(\d{1,3})$", re.IGNORECASE)
RE_NUM_ENUNCIADO = re.compile(r"^\s*(\d{1,3})\s*[\.\)\-]\s*")
RE_PREFIJO_OPCION = re.compile(r"^\s*[a-fA-F]\s*[\)\.\-]\s+")
RE_ENTIDAD_RESIDUAL = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]{2,8});")
RE_CORRECTO = re.compile(r"""respuesta\w*\s*\(\s*['"]\s*correcto\s*['"]\s*\)""", re.I)
RE_INCORRECTO = re.compile(r"""respuesta\w*\s*\(\s*['"]\s*incorrecto\s*['"]\s*\)""", re.I)


@dataclass
class PreguntaBlog:
    num: int
    enunciado: str
    opciones: list[str]
    indice_correcta: int | None
    n_correctas: int
    fichero: str
    # `fallos` manda la pregunta a cuarentena; `avisos` solo se informa.
    fallos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def resp(self) -> str | None:
        if self.indice_correcta is None or self.indice_correcta >= len(LETRAS):
            return None
        return LETRAS[self.indice_correcta]


# --- limpieza de texto -----------------------------------------------------------

def limpiar(texto: str) -> str:
    """Colapsa espacios y termina de decodificar entidades si quedan.

    BeautifulSoup ya decodifica al parsear; el `unescape` extra solo se aplica si
    aún se ve una entidad, para no convertir un `&amp;` legítimo en `&`.
    """
    if RE_ENTIDAD_RESIDUAL.search(texto):
        texto = html_lib.unescape(texto)
    texto = texto.replace("\xa0", " ")
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_hash(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def extraer_opciones(form: Tag) -> list[str]:
    """Texto de cada opción: lo que va tras su `<input>` y antes del `<br>`.

    Recorre el formulario en orden documental en lugar de mirar los hermanos de
    cada input. Es deliberado: basta con que un `<input>` venga sin barra de
    cierre — `<input type="radio">`, como escribe medio Blogger — para que
    html.parser lo trate como etiqueta con contenido y **anide dentro los demás
    inputs**. Entonces `next_siblings` sale vacío y la opción se pierde en
    silencio. Recorriendo `descendants` el orden se respeta pase lo que pase con
    la anidación.
    """
    opciones: list[str] = []
    abierta: list[str] | None = None

    def cerrar() -> None:
        nonlocal abierta
        if abierta is not None:
            opciones.append(limpiar("".join(abierta)))
            abierta = None

    for nodo in form.descendants:
        if isinstance(nodo, Tag):
            if nodo.name == "input":
                tipo = (nodo.get("type") or "").lower()
                cerrar()
                # Solo los radios abren opción; el cuadro "Resultado" la cierra.
                if tipo == "radio":
                    abierta = []
            elif nodo.name == "br":
                cerrar()
        elif isinstance(nodo, NavigableString) and abierta is not None:
            abierta.append(str(nodo))

    cerrar()
    return opciones


# --- extracción ------------------------------------------------------------------

def extraer_preguntas(contenido: str, fichero: str) -> list[PreguntaBlog]:
    """Saca todas las preguntas de una página del blog."""
    sopa = BeautifulSoup(contenido, "html.parser")
    preguntas: list[PreguntaBlog] = []

    for form in sopa.find_all("form"):
        nombre = form.get("name") or ""
        radios = [e for e in form.find_all("input")
                  if (e.get("type") or "").lower() == "radio"]
        if not radios:
            continue

        fallos: list[str] = []
        avisos: list[str] = []

        # --- enunciado: el primer <p> del form, sin su número de orden --------
        parrafo = form.find("p")
        bruto = limpiar(parrafo.get_text(" ", strip=False)) if parrafo else ""
        m_num = RE_NUM_ENUNCIADO.match(bruto)
        enunciado = bruto[m_num.end():].strip() if m_num else bruto

        # --- número: el del enunciado manda; el del form es el respaldo -------
        m_nombre = RE_NOMBRE_FORM.match(nombre)
        num_form = int(m_nombre.group(1)) if m_nombre else None
        num_texto = int(m_num.group(1)) if m_num else None
        num = num_texto or num_form or (len(preguntas) + 1)
        if num_texto and num_form and num_texto != num_form:
            # No es un defecto: el `name` del form numera dentro de la página
            # (pregunta01…preguntaNN) mientras que el enunciado conserva la
            # numeración del examen original, que es la que interesa guardar.
            avisos.append(f"el enunciado dice {num_texto} y el form {num_form}")
        if num_texto is None and num_form is None:
            fallos.append("sin número ni en el enunciado ni en el form")

        # --- opciones y cuál está marcada como correcta -----------------------
        textos = extraer_opciones(form)
        if len(textos) != len(radios):
            fallos.append(f"{len(radios)} radios pero {len(textos)} textos de opción")
            textos += [""] * (len(radios) - len(textos))

        opciones: list[str] = []
        correctas: list[int] = []
        for i, radio in enumerate(radios):
            onclick = radio.get("onclick") or ""
            if RE_CORRECTO.search(onclick):
                correctas.append(i)
            elif not RE_INCORRECTO.search(onclick):
                fallos.append(f"opción {i + 1} sin marca Correcto/Incorrecto")
            opciones.append(RE_PREFIJO_OPCION.sub("", textos[i]).strip())

        if len(correctas) != 1:
            fallos.append(f"{len(correctas)} opciones marcadas como Correcto")
        if len(opciones) != N_OPCIONES_NORMAL:
            fallos.append(f"{len(opciones)} opciones")
        if len(enunciado) < 10:
            fallos.append("enunciado vacío o demasiado corto")
        cortas = [i + 1 for i, o in enumerate(opciones) if len(o) < 3]
        if cortas:
            fallos.append(f"opciones truncadas o vacías: {cortas}")

        preguntas.append(PreguntaBlog(
            num=num,
            enunciado=enunciado,
            opciones=opciones,
            indice_correcta=correctas[0] if len(correctas) == 1 else None,
            n_correctas=len(correctas),
            fichero=fichero,
            fallos=fallos,
            avisos=avisos,
        ))

    return preguntas


# --- metadatos -------------------------------------------------------------------

def cargar_indice(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# El campo `ccaa_org` del índice mezcla organismo y comunidad en un solo texto, y
# partirlo por el primer espacio se equivoca ("Red Sanitaria Militar" daría
# ccaa="Sanitaria Militar"). Se mapea explícito: son dieciséis valores fijos.
ORGANISMOS = {
    "SAS Andalucia": ("SAS", "Andalucía"),
    "Osakidetza": ("Osakidetza", "País Vasco"),
    "SCS Cantabria": ("SCS", "Cantabria"),
    "SCS Canarias": ("SCS", "Canarias"),
    "SESCAM CLM": ("SESCAM", "Castilla-La Mancha"),
    "Red Sanitaria Militar": ("Red Sanitaria Militar", "Estatal"),
    "SERIS La Rioja": ("SERIS", "La Rioja"),
    "SES Extremadura": ("SES", "Extremadura"),
    "SMS Murcia": ("SMS", "Murcia"),
    "SACYL CyL": ("SACYL", "Castilla y León"),
    "SALUD Aragon": ("SALUD", "Aragón"),
    "JCyL": ("JCyL", "Castilla y León"),
    "SERMAS Madrid": ("SERMAS", "Madrid"),
    "IB-Salut Baleares": ("IB-Salut", "Baleares"),
    "DGA Aragon": ("DGA", "Aragón"),
    "Hosp Poniente": ("Hospital de Poniente", "Andalucía"),
}

# El `<title>` de la página nombra los turnos convocados; el índice no siempre.
TURNOS_EN_TITULO = (
    ("libre", re.compile(r"turno\s+libre|acceso\s+libre", re.I)),
    ("PI", re.compile(r"promoci[óo]n\s+interna", re.I)),
    ("discap", re.compile(r"discapacidad", re.I)),
)


def turno_del_titulo(contenido: str) -> str | None:
    """Deduce el turno del `<title>`, que suele enumerarlos."""
    sopa = BeautifulSoup(contenido[:4000], "html.parser")
    if not sopa.title or not sopa.title.string:
        return None
    titulo = sopa.title.string
    etiquetas = [nombre for nombre, patron in TURNOS_EN_TITULO if patron.search(titulo)]
    return "+".join(etiquetas) or None


def _clave(texto: str) -> str:
    """Clave laxa para casar nombre de fichero con slug del índice."""
    return re.sub(r"[^a-z0-9]", "", Path(texto).stem.lower())


def casar_metadatos(fichero: Path, indice: list[dict[str, str]]) -> dict | None:
    """Busca la fila del índice cuyo slug corresponde a este fichero.

    El nombre tiene que coincidir exactamente con el basename del slug. La
    coincidencia por subcadena, que parecía una comodidad, asignaba la misma fila
    a media docena de ficheros: "test-de-fisioterapeutas-ope" está contenido en
    "test-de-fisioterapeutas-ope_1", "_2", "_7"… y todos heredaban el mismo
    `prio`, generando ids duplicados.
    """
    objetivo = _clave(fichero.name)
    for fila in indice:
        slug = fila.get("slug_blog") or ""
        if slug and _clave(Path(slug).name) == objetivo:
            return fila
    return None


def metadatos_de_fila(fila: dict[str, str] | None, args, fichero: Path,
                      contenido: str = "") -> dict:
    """Combina índice, `<title>` y overrides de CLI. La CLI siempre gana."""
    ccaa_org = (fila or {}).get("ccaa_org", "").strip()
    org, ccaa = ORGANISMOS.get(ccaa_org, (ccaa_org, ""))
    descripcion = (fila or {}).get("descripcion", "")

    turno = args.turno
    if turno is None:
        bajo = descripcion.lower()
        etiquetas = [t for t, clave in
                     (("libre", "libre"), ("PI", "promoción interna"),
                      ("PI", "promocion interna"), ("discap", "discapacidad"))
                     if clave in bajo]
        turno = "+".join(dict.fromkeys(etiquetas)) or None
    if turno is None and contenido:
        turno = turno_del_titulo(contenido)

    prefijo = args.id_prefix
    if prefijo is None:
        base = re.sub(r"[^A-Z0-9]", "", (args.org or org or fichero.stem).upper())[:10]
        anio = ((fila or {}).get("ano_examen") or "")[:4]
        prefijo = f"{base}{anio}" if anio else base or "BLOG"

    # Organismo y año no identifican una página: un mismo examen se publica en dos
    # o tres partes y del mismo año hay varias convocatorias, así que "DGA2015-001"
    # se generaba cinco veces. El `prio` del índice es único por fila y estable.
    parte = (fila or {}).get("prio") or ""
    if not parte:
        parte = str(abs(hash(fichero.name)) % 100)

    return {
        "parte": f"{int(parte):02d}" if str(parte).isdigit() else str(parte)[:3],
        "org": args.org or org or None,
        "ccaa": args.ccaa or ccaa or None,
        "fecha": args.fecha or (fila or {}).get("ano_examen") or None,
        "turno": turno,
        "id_prefix": prefijo,
        "penalizacion": args.penalizacion,
    }


def a_registro(p: PreguntaBlog, meta: dict) -> dict:
    return {
        "id": f"{meta['id_prefix']}-{meta['parte']}-{p.num:03d}",
        "org": meta["org"],
        "ccaa": meta["ccaa"],
        "fecha": meta["fecha"],
        "turno": meta["turno"],
        "num": p.num,
        "bloque": None,
        "q": p.enunciado,
        "opts": p.opciones,
        "resp": p.resp,
        # La respuesta viene marcada en el propio HTML de origen: autoverificada.
        "resp_verificada": p.resp is not None,
        "conf": 1.0,
        "origen": "html",
        "penalizacion": meta["penalizacion"],
        "reserva": False,
        "revisar": False,
    }


# --- control de calidad ----------------------------------------------------------

def informe_qa(por_fichero: dict[str, list[PreguntaBlog]], registros: list[dict],
               cuarentena: list[dict], colisiones: list[str],
               muestra: int, semilla: int, verbose: bool) -> str:
    lineas: list[str] = []
    total = sum(len(v) for v in por_fichero.values())
    lineas.append(f"ficheros procesados: {len(por_fichero)} | preguntas: {total} "
                  f"| al corpus: {len(registros)} | a cuarentena: {len(cuarentena)}")

    if verbose:
        for nombre, preguntas in sorted(por_fichero.items()):
            lineas.append(f"  {nombre}: {len(preguntas)}")

    # 2. Distribución de la letra correcta: el detector principal de parser roto.
    cuenta = Counter(r["resp"] for r in registros if r["resp"])
    n = sum(cuenta.values())
    if n:
        reparto = []
        sospechoso = False
        for letra in LETRAS[:N_OPCIONES_NORMAL]:
            pct = 100 * cuenta.get(letra, 0) / n
            sospechoso |= pct > 45
            reparto.append(f"{letra}={cuenta.get(letra, 0)} ({pct:.1f}%)")
        lineas.append("letra correcta: " + "  ".join(reparto)
                      + ("   <-- SOSPECHOSO" if sospechoso else ""))

    # 3-6. Anomalías, agrupadas por tipo para no llenar el informe.
    motivos = Counter()
    avisos = Counter()
    for preguntas in por_fichero.values():
        for p in preguntas:
            for f in p.fallos:
                motivos[re.sub(r"\d+", "N", f)] += 1
            for a in p.avisos:
                avisos[re.sub(r"\d+", "N", a)] += 1
    if motivos:
        lineas.append("a cuarentena por:")
        for motivo, veces in motivos.most_common(6):
            lineas.append(f"  ×{veces}  {motivo}")
    if avisos:
        lineas.append("avisos (no impiden la ingesta):")
        for aviso, veces in avisos.most_common(3):
            lineas.append(f"  ×{veces}  {aviso}")

    for nombre, preguntas in sorted(por_fichero.items()):
        nums = [p.num for p in preguntas]
        # Los huecos se miden dentro del rango observado: muchas páginas son la
        # "parte 2" de un examen y arrancan en la 9, la 26 o la 51, sin que falte
        # nada.
        huecos = (sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
                  if nums else [])
        repetidos = sorted({x for x in nums if nums.count(x) > 1})
        if huecos or repetidos:
            lineas.append(f"  {nombre}: rango {min(nums)}-{max(nums)} "
                          f"huecos={huecos[:8]} duplicados={repetidos[:8]}")

    if colisiones:
        lineas.append(f"ids que ya existían y NO se han reescrito: {len(colisiones)} "
                      f"({', '.join(colisiones[:5])}…)")

    # 7. Recurrencias: no son un error, son la señal que se busca.
    grupos: dict[str, list[dict]] = {}
    for r in registros:
        grupos.setdefault(normalizar_hash(r["q"]), []).append(r)
    repes = sorted(((k, v) for k, v in grupos.items() if len(v) > 1),
                   key=lambda kv: -len(kv[1]))
    lineas.append(f"RECURRENCIAS: {len(repes)} enunciados repetidos")
    for _, regs in repes[:5]:
        procedencias = ", ".join(sorted({str(r["id"]).rsplit("-", 1)[0] for r in regs}))
        lineas.append(f"  ×{len(regs)}  {regs[0]['q'][:60]}…  [{procedencias}]")

    # 8. Muestreo para revisión humana.
    if muestra and registros:
        aleatorio = random.Random(semilla)
        lineas.append(f"--- muestra de {min(muestra, len(registros))} preguntas ---")
        for r in aleatorio.sample(registros, min(muestra, len(registros))):
            lineas.append(f"[{r['id']}] {r['q'][:100]}")
            for letra, opcion in zip(LETRAS, r["opts"]):
                marca = "*" if letra == r["resp"] else " "
                lineas.append(f"   {marca}{letra}) {opcion[:78]}")
    return "\n".join(lineas)


# --- entrada/salida --------------------------------------------------------------

def recopilar_ficheros(rutas: Iterable[Path]) -> list[Path]:
    ficheros: list[Path] = []
    for ruta in rutas:
        if ruta.is_dir():
            for patron in ("*.html", "*.htm", "*.txt"):
                ficheros += sorted(ruta.glob(patron))
        elif ruta.is_file():
            ficheros.append(ruta)
        else:
            print(f"aviso: no existe {ruta}", file=sys.stderr)
    return ficheros


def leer(fichero: Path) -> str:
    """Lee el HTML tolerando que no venga en UTF-8."""
    for codec in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return fichero.read_text(encoding=codec)
        except UnicodeDecodeError:
            continue
    return fichero.read_text(encoding="utf-8", errors="replace")


def ids_existentes(ruta: Path) -> set[str]:
    if not ruta.is_file():
        return set()
    return {json.loads(l)["id"] for l in ruta.read_text(encoding="utf-8").splitlines()
            if l.strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entradas", nargs="+", type=Path,
                    help="ficheros .html/.txt o un directorio con ellos")
    ap.add_argument("--indice", type=Path, default=Path("indice_examenes.csv"))
    ap.add_argument("--out", type=Path, default=Path("corpus/corpus_blog.jsonl"))
    ap.add_argument("--cuarentena", type=Path, default=Path("corpus/cuarentena.jsonl"))
    ap.add_argument("--informe", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true", help="parsea e informa sin escribir")
    ap.add_argument("--muestra", type=int, default=3, help="preguntas de muestra (0 = ninguna)")
    ap.add_argument("--seed", type=int, default=0, help="semilla del muestreo")
    ap.add_argument("--verbose", action="store_true", help="detalla el recuento por fichero")
    # Overrides de metadatos, para ficheros que el índice no cubra.
    ap.add_argument("--org")
    ap.add_argument("--ccaa")
    ap.add_argument("--fecha")
    ap.add_argument("--turno")
    ap.add_argument("--id-prefix", dest="id_prefix")
    ap.add_argument("--penalizacion", type=float, default=None,
                    help="fracción que resta cada fallo; si no se pasa, queda 'no consta'")
    args = ap.parse_args()

    ficheros = recopilar_ficheros(args.entradas)
    if not ficheros:
        print("no hay nada que parsear", file=sys.stderr)
        return 1

    indice = cargar_indice(args.indice) if args.indice.is_file() else []
    if not indice:
        print(f"aviso: sin índice utilizable en {args.indice}; "
              f"los metadatos saldrán de la CLI", file=sys.stderr)

    por_fichero: dict[str, list[PreguntaBlog]] = {}
    registros: list[dict] = []
    cuarentena: list[dict] = []
    sin_indice: list[str] = []

    for fichero in ficheros:
        contenido = leer(fichero)
        preguntas = extraer_preguntas(contenido, fichero.name)
        if not preguntas:
            print(f"aviso: {fichero.name} no contiene ningún formulario de pregunta",
                  file=sys.stderr)
            continue
        por_fichero[fichero.name] = preguntas

        fila = casar_metadatos(fichero, indice)
        if fila is None:
            sin_indice.append(fichero.name)
        meta = metadatos_de_fila(fila, args, fichero, contenido)

        for p in preguntas:
            registro = a_registro(p, meta)
            (cuarentena if p.fallos else registros).append(registro)

    # Acumulación: nunca se pisa un id ya presente en el corpus. Se comprueba
    # también contra los generados en esta misma pasada; si no, dos páginas del
    # mismo organismo y año se pisan entre sí sin que salte nada.
    ya_estaban = ids_existentes(args.out)
    vistos: set[str] = set()
    colisiones: list[str] = []
    nuevos: list[dict] = []
    for r in registros:
        if r["id"] in ya_estaban or r["id"] in vistos:
            colisiones.append(r["id"])
            continue
        vistos.add(r["id"])
        nuevos.append(r)

    if sin_indice:
        print(f"aviso: {len(sin_indice)} ficheros sin fila en el índice: "
              f"{', '.join(sin_indice[:5])}", file=sys.stderr)

    texto = informe_qa(por_fichero, registros, cuarentena, colisiones,
                       args.muestra, args.seed, args.verbose)
    print(texto)

    if args.dry_run:
        print("\n[--dry-run] no se ha escrito nada")
        return 0

    if nuevos:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as fh:
            for r in nuevos:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    if cuarentena:
        args.cuarentena.parent.mkdir(parents=True, exist_ok=True)
        with args.cuarentena.open("a", encoding="utf-8") as fh:
            for r in cuarentena:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nañadidas {len(nuevos)} preguntas a {args.out}"
          + (f" | {len(cuarentena)} a {args.cuarentena}" if cuarentena else ""))
    if args.informe:
        args.informe.write_text(texto, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
