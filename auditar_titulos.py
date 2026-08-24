"""Contrasta el `<title>` de cada página descargada con lo que dice el índice.

El índice se construyó leyendo la página recopilatoria del blog sin verificar cada
destino, así que puede apuntar a exámenes de otra categoría. Una página de otra
categoría no da ningún error al parsear: entra limpia y envenena las frecuencias
temáticas en silencio, que es el peor fallo posible aquí.

El título de la página es la fuente fiable. Se comprueba:
  1. Que menciona FISIOTERAPEUTA. Si no, la página se descarta.
  2. Que el organismo del título encaja con el `ccaa_org` del CSV.
  3. Que la fecha del título encaja con el `ano_examen` del CSV.

    python auditar_titulos.py
    python auditar_titulos.py --mover      # aparta las que no son de fisioterapeuta
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup

RAIZ = Path(__file__).resolve().parent
BLOG = RAIZ / "fuentes" / "blog"
DESCARTES = BLOG / "_descartadas"

# La categoría hay que leerla del "Test de X", no de cualquier aparición de la
# palabra: `ope-consolidacion-sas-2002_14.html` se titula "Test de Enfermera nº 09
# … - FISIOTERAPEUTAS", con la categoría real al principio y esa palabra al final
# como etiqueta. Buscar "fisioterap" suelto la daba por buena.
RE_CATEGORIA = re.compile(r"test\s+de\s+fisioterap", re.IGNORECASE)
# Fechas del tipo 15-03-2026 o 15/03/2026.
RE_FECHA = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b")
RE_ANIO = re.compile(r"\b(20\d{2})\b")

# Raíces por las que se reconoce cada organismo en el título. Son raíces y no
# nombres completos porque los títulos usan el gentilicio: "Servicio CÁNTABRO",
# "Servicio CANARIO", "Servicio EXTREMEÑO" — que no contienen "Cantabria",
# "Canarias" ni "Extremadura".
# Las claves son los valores literales de `ccaa_org` en el CSV, no siglas sueltas:
# "SCS" es a la vez Cantabria y Canarias, así que casar por el primer token elige
# la comunidad equivocada la mitad de las veces.
PISTAS_ORG = {
    "SAS Andalucia": ("SAS", "ANDALUZ", "ANDALUC"),
    "Osakidetza": ("OSAKIDETZA", "VASCO"),
    "SCS Cantabria": ("CANTABR",),
    "SCS Canarias": ("CANARI",),
    "SESCAM CLM": ("SESCAM", "MANCHA"),
    "Red Sanitaria Militar": ("MILITAR", "DEFENSA", "RSM"),
    "SERIS La Rioja": ("SERIS", "RIOJA"),
    "SES Extremadura": ("EXTREM",),
    "SMS Murcia": ("SMS", "MURCIA", "MURCIANO"),
    "SACYL CyL": ("SACYL", "CASTILLA Y LEON"),
    "SALUD Aragon": ("ARAGON", "ARAGONES", "SALUD"),
    "JCyL": ("JUNTA DE CASTILLA Y LEON", "CASTILLA Y LEON", "JCYL"),
    "SERMAS Madrid": ("SERMAS", "MADRID"),
    "IB-Salut Baleares": ("IB-SALUT", "IBSALUT", "BALEAR"),
    "DGA Aragon": ("DGA", "ARAGON"),
    "Hosp Poniente": ("PONIENTE",),
}


def sin_tildes(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in s if not unicodedata.combining(c)).upper()


def leer_titulo(fichero: Path) -> str:
    # El <title> vive en la cabecera: no hace falta parsear el documento entero.
    cabeza = fichero.read_text(encoding="utf-8", errors="replace")[:8000]
    sopa = BeautifulSoup(cabeza, "html.parser")
    if sopa.title and sopa.title.string:
        return re.sub(r"\s+", " ", sopa.title.string).strip()
    return ""


def fecha_del_titulo(titulo: str) -> str | None:
    m = RE_FECHA.search(titulo)
    if m:
        dia, mes, anio = m.groups()
        return f"{anio}-{int(mes):02d}-{int(dia):02d}"
    anios = RE_ANIO.findall(titulo)
    return max(anios) if anios else None


def organismo_encaja(titulo: str, ccaa_org: str) -> bool | None:
    """True si el título confirma el organismo, False si lo contradice, None si calla."""
    arriba = sin_tildes(titulo)
    pistas = PISTAS_ORG.get(ccaa_org)
    if pistas is None:
        return None
    if any(sin_tildes(p) in arriba for p in pistas):
        return True
    # El título nombra otro organismo conocido: contradicción de verdad.
    for otra_clave, otras in PISTAS_ORG.items():
        if otra_clave == ccaa_org:
            continue
        if any(sin_tildes(p) in arriba for p in otras if len(p) > 4):
            return False
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--indice", type=Path, default=RAIZ / "indice_examenes.csv")
    ap.add_argument("--blog", type=Path, default=BLOG)
    ap.add_argument("--mover", action="store_true",
                    help="aparta a _descartadas/ las que no son de fisioterapeuta")
    args = ap.parse_args()

    with args.indice.open(encoding="utf-8-sig", newline="") as fh:
        filas = {Path((f.get("slug_blog") or "").strip()).name: f
                 for f in csv.DictReader(fh) if (f.get("slug_blog") or "").strip()}

    fuera: list[tuple[str, str]] = []
    dudas_org: list[tuple[str, str, str]] = []
    dudas_fecha: list[tuple[str, str, str]] = []
    sin_titulo: list[str] = []
    ok = 0

    for fichero in sorted(args.blog.glob("*.html")):
        titulo = leer_titulo(fichero)
        fila = filas.get(fichero.name, {})

        if not titulo:
            sin_titulo.append(fichero.name)
            continue

        if not RE_CATEGORIA.search(titulo):
            fuera.append((fichero.name, titulo[:96]))
            continue
        ok += 1

        ccaa_org = (fila.get("ccaa_org") or "").strip()
        if organismo_encaja(titulo, ccaa_org) is False:
            dudas_org.append((fichero.name, ccaa_org, titulo[:88]))

        del_csv = (fila.get("ano_examen") or "").strip()
        del_titulo = fecha_del_titulo(titulo)
        if del_csv and del_titulo and not (
                del_csv == del_titulo or del_csv[:4] in del_titulo
                or del_titulo[:4] in del_csv):
            dudas_fecha.append((fichero.name, del_csv, del_titulo))

    print(f"páginas analizadas : {ok + len(fuera) + len(sin_titulo)}")
    print(f"  son de FISIOTERAPEUTA : {ok}")
    print(f"  NO lo son (descartar) : {len(fuera)}")
    if sin_titulo:
        print(f"  sin <title> legible   : {len(sin_titulo)} -> {sin_titulo}")

    if fuera:
        print("\n--- FUERA: el título no menciona fisioterapeuta ---")
        for nombre, titulo in fuera:
            print(f"  {nombre}\n      {titulo}")

    if dudas_org:
        print(f"\n--- organismo del CSV contradicho por el título ({len(dudas_org)}) ---")
        for nombre, ccaa_org, titulo in dudas_org:
            print(f"  {nombre}\n      CSV dice '{ccaa_org}' | título: {titulo}")

    if dudas_fecha:
        print(f"\n--- fecha del CSV distinta de la del título ({len(dudas_fecha)}) ---")
        for nombre, del_csv, del_titulo in dudas_fecha:
            print(f"  {nombre}: CSV={del_csv}  título={del_titulo}")

    if args.mover and fuera:
        DESCARTES.mkdir(parents=True, exist_ok=True)
        for nombre, _ in fuera:
            (args.blog / nombre).rename(DESCARTES / nombre)
        print(f"\napartadas {len(fuera)} páginas en {DESCARTES}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
