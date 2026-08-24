"""Ingiere la parte general asturiana desde tests del SESPA/ERA de cualquier categoría.

Los temas 1-11 del BOPA son la parte general y son casi idénticos entre
categorías: una pregunta de celador o de TCAE sobre la Ley 7/2019, el Estatuto de
Autonomía o la estructura orgánica del SESPA vale exactamente igual para
fisioterapeuta. Son 3-4 preguntas garantizadas del examen que ningún otro corpus
cubre, porque cada comunidad pregunta por su propia normativa.

Por eso aquí solo entra lo que clasifica en T1-T11: una pregunta de celador sobre
movilización de pacientes no sirve, y una sobre el Consejo de Salud del Principado
sí. Todas quedan marcadas con `ambito: "asturias"` para poder entrenarlas aparte.

    python ingest_asturias.py --dry-run
    python ingest_asturias.py --out corpus/corpus_asturias_general.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

import parse_blog as blog
from clasificar_temas import clasificar

RAIZ = Path(__file__).resolve().parent
FUENTE = RAIZ / "fuentes" / "blog_asturias"

# El título es la fuente fiable del ámbito: el contexto del enlace en las páginas
# índice arrastra el organismo de la fila de al lado.
RE_AMBITO = re.compile(
    r"sespa|principado de asturias|\be\.?r\.?a\.?\b|establecimientos residenciales"
    r"|monte naranco|cabuenes|hospital de jarrio", re.IGNORECASE)
RE_FECHA = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")
RE_ANIO = re.compile(r"\b(20\d{2}|19\d{2})\b")

TEMA_MAX_GENERAL = 11


def organismo(titulo: str) -> str:
    t = titulo.upper()
    if re.search(r"\bE\.?R\.?A\.?\b|ESTABLECIMIENTOS RESIDENCIALES", t):
        return "ERA"
    if "MONTE NARANCO" in t:
        return "Hospital Monte Naranco"
    return "SESPA"


def categoria(titulo: str) -> str | None:
    for patron, nombre in (
        (r"CELADOR", "celador"), (r"TCAE|AUXILIAR DE ENFERMER", "TCAE"),
        (r"ENFERMER", "enfermería"), (r"ADMINISTRATIV", "administrativo"),
        (r"FISIOTERAPE", "fisioterapeuta"), (r"T[ÉE]CNIC", "técnico"),
        (r"MATRON", "matrona"), (r"LOGOPED", "logopeda"),
    ):
        if re.search(patron, titulo, re.IGNORECASE):
            return nombre
    return None


def fecha_de(titulo: str) -> str | None:
    m = RE_FECHA.search(titulo)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    anios = RE_ANIO.findall(titulo)
    return f"{max(anios)}-01-01" if anios else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fuente", type=Path, default=FUENTE)
    ap.add_argument("--out", type=Path,
                    default=RAIZ / "corpus" / "corpus_asturias_general.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    paginas = sorted(p for p in args.fuente.glob("*.html"))
    if not paginas:
        print(f"no hay páginas en {args.fuente}", file=sys.stderr)
        return 1

    registros: list[dict] = []
    descartadas_pagina = 0
    fuera_de_general = 0
    sin_tema = 0
    por_categoria: Counter = Counter()
    por_tema: Counter = Counter()
    vistos: set[str] = set()

    for pagina in paginas:
        html = blog.leer(pagina)
        sopa = BeautifulSoup(html[:8000], "html.parser")
        titulo = sopa.title.string if sopa.title and sopa.title.string else ""
        titulo = re.sub(r"\s+", " ", titulo).strip()

        if not RE_AMBITO.search(titulo):
            descartadas_pagina += 1
            continue

        preguntas = blog.extraer_preguntas(html, pagina.name)
        org = organismo(titulo)
        cat = categoria(titulo)
        fecha = fecha_de(titulo)
        anio = (fecha or "")[:4] or "0000"
        prefijo = f"AST{org.replace(' ', '')[:4].upper()}{anio}"

        for p in preguntas:
            if p.fallos or p.resp is None:
                continue
            tema, tema2, evidencia = clasificar(p.enunciado, p.opciones)
            if tema is None:
                sin_tema += 1
                continue
            if tema > TEMA_MAX_GENERAL:
                fuera_de_general += 1
                continue

            id_ = f"{prefijo}-{pagina.stem[-12:]}-{p.num:03d}"
            if id_ in vistos:
                continue
            vistos.add(id_)

            registros.append({
                "id": id_,
                "org": org,
                "ccaa": "Asturias",
                "fecha": fecha,
                "turno": None,
                "num": p.num,
                "bloque": "general",
                "q": p.enunciado,
                "opts": p.opciones,
                "resp": p.resp,
                "resp_verificada": True,   # la respuesta viaja en el propio HTML
                "conf": 1.0,
                "origen": "html",
                "penalizacion": None,      # no consta para estas convocatorias
                "reserva": False,
                "revisar": False,
                "ambito": "asturias",
                "categoria_origen": cat,
                "tema_primario": tema,
                "tema_secundario": tema2,
                "tema_evidencia": evidencia,
            })
            por_categoria[cat or "?"] += 1
            por_tema[tema] += 1

    print(f"páginas leídas          : {len(paginas)}")
    print(f"  descartadas por título: {descartadas_pagina} (no eran del SESPA/ERA)")
    print(f"preguntas T1-T11        : {len(registros)}")
    print(f"  fuera de la general   : {fuera_de_general}")
    print(f"  sin tema asignable    : {sin_tema}")
    print("por categoría de origen : " +
          ", ".join(f"{k}={v}" for k, v in por_categoria.most_common()))
    print("por tema                : " +
          ", ".join(f"T{k}={v}" for k, v in sorted(por_tema.items())))

    if args.dry_run:
        print("\n[--dry-run] no se ha escrito nada")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in registros:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nescritas {len(registros)} preguntas en {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
