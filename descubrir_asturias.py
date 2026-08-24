"""Localiza en el blog las páginas de test del SESPA (cualquier categoría) y de ERA.

Los temas 1-11 del BOPA son la parte general y son prácticamente idénticos entre
categorías: una pregunta de celador sobre la Ley 7/2019, el Estatuto de Autonomía
o la estructura del SESPA sirve igual para fisioterapeuta. Son 3-4 preguntas
garantizadas del examen que ningún otro corpus cubre, porque el resto de
comunidades preguntan por su propia normativa.

El feed de páginas de Blogger solo devuelve las últimas, así que la enumeración se
hace desde las entradas "Colección Completa", que enlazan todas las páginas de su
categoría.

    python descubrir_asturias.py --descargar
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "fuentes" / "blog_asturias"
BASE = "https://elcelatagarrapata.blogspot.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# Lo que identifica a una página del ámbito asturiano en su título o su slug.
RE_ASTURIAS = re.compile(
    r"sespa|principado de asturias|\basturias\b|\bera\b"
    r"|establecimientos residenciales", re.IGNORECASE)
RE_PAGINA = re.compile(r'href="(https?://elcelatagarrapata\.blogspot\.com/p/[^"]+\.html)"')
MARCA_ONCLICK = 'onclick="respuesta'


def bajar(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8", errors="replace")


def indices_del_blog() -> list[str]:
    """Entradas del blog que hacen de índice ('Colección Completa …')."""
    url = f"{BASE}/feeds/posts/default?alt=json&max-results=200"
    datos = json.loads(bajar(url))
    urls = []
    for e in datos["feed"].get("entry", []):
        titulo = e["title"]["$t"]
        if re.search(r"colecci[óo]n|completa|online|[íi]ndice", titulo, re.I):
            enlace = [l["href"] for l in e["link"] if l["rel"] == "alternate"][0]
            urls.append(enlace)
    return urls


def enlaces_con_titulo(html: str) -> dict[str, str]:
    """Mapa url -> texto de su entorno en la página índice.

    No basta con el texto del `<a>`: en las colecciones el enlace pone solo
    "Test nº 062" y el organismo va en el resto de la fila. Se toma una ventana
    alrededor del enlace para que el filtro pueda ver "SESPA" o "Asturias".
    """
    salida: dict[str, str] = {}
    for m in re.finditer(
            r'href="(https?://elcelatagarrapata\.blogspot\.com/p/[^"]+\.html)"', html):
        url = m.group(1)
        ventana = html[max(0, m.start() - 400): m.end() + 400]
        texto = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", ventana)).strip()
        if url not in salida or len(texto) > len(salida[url]):
            salida[url] = texto
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--descargar", action="store_true")
    ap.add_argument("--destino", type=Path, default=DESTINO)
    ap.add_argument("--pausa-min", type=float, default=1.0)
    ap.add_argument("--pausa-max", type=float, default=2.0)
    args = ap.parse_args()

    print("buscando páginas índice del blog…", file=sys.stderr)
    candidatos: dict[str, str] = {}
    indices = indices_del_blog()
    print(f"  {len(indices)} entradas índice", file=sys.stderr)

    cache = args.destino / "_indices"
    cache.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(indices, 1):
        guardado = cache / (url.rstrip("/").split("/")[-1] or "index.html")
        if guardado.is_file() and guardado.stat().st_size > 0:
            html = guardado.read_text(encoding="utf-8", errors="replace")
        else:
            try:
                html = bajar(url)
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"  aviso: {url} falló ({e})", file=sys.stderr)
                continue
            guardado.write_text(html, encoding="utf-8")
            time.sleep(random.uniform(args.pausa_min, args.pausa_max))
        nuevos = enlaces_con_titulo(html)
        candidatos.update(nuevos)
        print(f"  [{i}/{len(indices)}] {url.split('/')[-1][:52]}: "
              f"{len(nuevos)} enlaces (acumulado {len(candidatos)})", file=sys.stderr)

    asturianas = {u: t for u, t in candidatos.items()
                  if RE_ASTURIAS.search(t) or RE_ASTURIAS.search(u)}
    print(f"\npáginas totales descubiertas : {len(candidatos)}")
    print(f"del ámbito asturiano (SESPA/ERA): {len(asturianas)}")
    for u, t in sorted(asturianas.items(), key=lambda kv: kv[1]):
        print(f"   {t[:96]}")

    if not args.descargar:
        return 0

    args.destino.mkdir(parents=True, exist_ok=True)
    print(f"\n{'página':56} {'KB':>6} {'onclick':>8}  estado")
    print("-" * 88)
    fallos = 0
    for i, (url, titulo) in enumerate(sorted(asturianas.items()), 1):
        nombre = url.split("/p/")[-1]
        destino = args.destino / nombre
        if destino.is_file() and destino.stat().st_size > 0:
            texto = destino.read_text(encoding="utf-8", errors="replace")
        else:
            try:
                texto = bajar(url)
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"{nombre[:56]:56} {'-':>6} {'-':>8}  FALLO: {e}")
                fallos += 1
                continue
            destino.write_text(texto, encoding="utf-8")
            time.sleep(random.uniform(args.pausa_min, args.pausa_max))

        n = texto.count(MARCA_ONCLICK)
        estado = "OK" if n >= 20 else "FALLO: sin onclick"
        fallos += estado != "OK"
        print(f"{nombre[:56]:56} {len(texto.encode())//1024:6d} {n:8d}  {estado}")

    print(f"\n{len(asturianas)} páginas | {fallos} con fallo | en {args.destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
