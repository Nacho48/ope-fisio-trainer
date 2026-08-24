"""Descarga las páginas de tests de elcelatagarrapata.blogspot.com.

Las URL salen de la columna `slug_blog` de `indice_examenes.csv`; cada valor es la
ruta relativa dentro del blog. El fichero se guarda con el basename del slug (sin
la carpeta `p/`), que es lo que `parse_blog.py` espera para casar cada página con
su fila del índice.

Es HTML estático de Blogger: los `onclick` con la respuesta correcta vienen en el
fuente y no hacen falta ni navegador ni JavaScript.

Se descarga en serie y con pausa entre peticiones: son 54 páginas de un blog
personal, no hay ninguna prisa que justifique martillearlo.

    python descargar_blog.py
    python descargar_blog.py --solo test-de-fisioterapeutas-opes-202324.html
    python descargar_blog.py --forzar        # vuelve a bajar las ya presentes
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://elcelatagarrapata.blogspot.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Una página de 50 preguntas trae 4 onclick por pregunta.
ONCLICK_ESPERADOS = 200
MARCA_ONCLICK = 'onclick="respuesta'

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "fuentes" / "blog"


def descargar(url: str) -> bytes:
    peticion = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-ES,es;q=0.9",
    })
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        return respuesta.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--indice", type=Path, default=RAIZ / "indice_examenes.csv")
    ap.add_argument("--destino", type=Path, default=DESTINO)
    ap.add_argument("--solo", help="descarga solo el fichero con este nombre")
    ap.add_argument("--forzar", action="store_true", help="rebaja las ya descargadas")
    ap.add_argument("--pausa-min", type=float, default=1.0)
    ap.add_argument("--pausa-max", type=float, default=2.0)
    args = ap.parse_args()

    with args.indice.open(encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh))

    args.destino.mkdir(parents=True, exist_ok=True)
    resultados: list[tuple[str, int, int, str]] = []

    tareas = []
    for fila in filas:
        slug = (fila.get("slug_blog") or "").strip()
        if not slug:
            continue
        nombre = Path(slug).name
        if args.solo and nombre != args.solo:
            continue
        tareas.append((slug, nombre))

    for i, (slug, nombre) in enumerate(tareas, start=1):
        destino = args.destino / nombre
        if destino.is_file() and destino.stat().st_size > 0 and not args.forzar:
            texto = destino.read_text(encoding="utf-8", errors="replace")
            n = texto.count(MARCA_ONCLICK)
            resultados.append((nombre, destino.stat().st_size // 1024, n, "YA ESTABA"))
            continue

        url = BASE + slug.lstrip("/")
        print(f"[{i}/{len(tareas)}] {nombre}", file=sys.stderr)
        try:
            crudo = descargar(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            resultados.append((nombre, 0, 0, f"FALLO: {e}"))
            continue

        texto = crudo.decode("utf-8", errors="replace")
        destino.write_text(texto, encoding="utf-8")
        n = texto.count(MARCA_ONCLICK)
        estado = "OK" if n >= ONCLICK_ESPERADOS * 0.5 else "FALLO: sin onclick"
        resultados.append((nombre, len(texto.encode("utf-8")) // 1024, n, estado))

        if i < len(tareas):
            time.sleep(random.uniform(args.pausa_min, args.pausa_max))

    print(f"\n{'página':58} {'KB':>6} {'onclick':>8}  estado")
    print("-" * 92)
    for nombre, kb, n, estado in resultados:
        print(f"{nombre[:58]:58} {kb:6d} {n:8d}  {estado}")

    fallos = [r for r in resultados if r[3].startswith("FALLO")]
    total_onclick = sum(r[2] for r in resultados)
    print(f"\n{len(resultados)} páginas | {total_onclick} onclick en total "
          f"| {len(fallos)} con fallo")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
