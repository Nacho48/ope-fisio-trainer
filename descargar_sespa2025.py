"""Descarga los cuadernillos y plantillas del SESPA de noviembre de 2025.

Las 15 preguntas comunes del examen se parten en dos: las estatales (Constitución,
Estatuto Marco, LOPDGDD…), que ya cubre el corpus de otras comunidades porque el
hecho evaluado es idéntico en toda España; y las **autonómicas** (Estatuto de
Autonomía del Principado, Ley del Servicio de Salud, estructura y áreas del SESPA),
donde la transferencia desde otra comunidad es cero.

Los exámenes de otras categorías del SESPA del mismo ciclo OPE 2022-2023-2024
comparten literalmente esa parte general con Fisioterapia, así que son la única
fuente reciente del bloque autonómico.

    python descargar_sespa2025.py
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CUADERNILLOS = RAIZ / "raw" / "cuadernillos"
PLANTILLAS = RAIZ / "raw" / "plantillas"
LISTADO = "https://usipa.es/examenes-oposicion-sespa-8-y-9-noviembre/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Normalización del texto del enlace a un nombre de categoría estable.
CATEGORIAS = [
    (r"ENFERMER", "enfermeria"),
    (r"TCAE|AUXILIAR DE ENFERMER", "tcae"),
    (r"TRABAJADOR", "trabajador_social"),
    (r"HIGIENISTA", "higienista"),
    (r"AUX.*ADMINISTRATIVO|ADMINISTRATIVO", "aux_administrativo"),
    (r"CELADOR", "celador"),
    (r"AYUDANTE", "ayudante_servicios"),
    (r"JEFE DE TALLER|TALLER", "jefe_taller"),
]

BASE_AST = "https://www.astursalud.es/documents/35439/1481812/"
PLANTILLAS_URL = {
    "celador": BASE_AST + "Plantilla_Provisional_Respuestas_CELADOR.pdf/"
               "67f07a08-5eb2-df32-543d-c74cc0eeee3a?t=1762787998448",
    "ayudante_servicios": BASE_AST + "PLANTILLA+PROVISIONAL+AYUDANTE.pdf/"
               "cff98807-303a-2cd1-2e31-0f41b253fbdb?t=1762788173959",
    "ayudante_servicios_rectificacion": BASE_AST +
               "rectificaci%C3%B3n+plantilla+provisional+Ayudante+de+Servicios.pdf/"
               "1add6254-6d45-cfb9-3bfb-c3e1dea4725f?t=1763125976238",
    "aux_administrativo": BASE_AST + "PLANTILLA+PROVISIONAL+AUX.ADM+09112025.pdf/"
               "2f37b601-1a73-dfd4-468e-3a7ff127c403?t=1762787797091",
    "tcae": BASE_AST + "PLANTILLA+PROVISIONAL+TCAE.pdf/"
               "a229f4d4-99b1-1af1-d74b-0e166cf4fe23?t=1762787603885",
    "jefe_taller": BASE_AST + "Plantilla+provisional+respuestas+examen+JEFE+DE+TALLER.pdf/"
               "ed173c8c-944d-c116-9fd9-2d82ea85e676?t=1762788576634",
    "higienista": BASE_AST + "PROVISIONAL+RESPUESTAS+HIGIENISTA.pdf/"
               "f099ca35-91db-9a00-578b-a9b42a455a7c?t=1762788788726",
    "enfermeria": BASE_AST + "PLANTILLA+PROVISIONAL+DE+RESPUESTAS_Enfermera_2025.pdf/"
               "4c146fad-0c91-f64e-6061-18d5fc849737?t=1762788347867",
}


def categoria_de(texto: str) -> str | None:
    arriba = texto.upper()
    for patron, nombre in CATEGORIAS:
        if re.search(patron, arriba):
            return nombre
    return None


def bajar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*", "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def guardar_pdf(url: str, destino: Path, pausa: tuple[float, float]) -> tuple[bool, str]:
    """Devuelve (ok, detalle). Un PDF de 0 bytes es descarga cortada, no corrupción."""
    if destino.is_file() and destino.stat().st_size > 1024:
        datos = destino.read_bytes()
    else:
        try:
            datos = bajar(url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            return False, f"FALLO descarga: {e}"
        if not datos:
            return False, "FALLO: 0 bytes (descarga cortada, reintentar)"
        destino.write_bytes(datos)
        time.sleep(random.uniform(*pausa))

    if not datos.startswith(b"%PDF"):
        return False, f"FALLO: no empieza por %PDF (¿HTML de error? {len(datos)} bytes)"
    return True, f"{len(datos)//1024} KB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pausa-min", type=float, default=1.0)
    ap.add_argument("--pausa-max", type=float, default=2.0)
    args = ap.parse_args()
    pausa = (args.pausa_min, args.pausa_max)

    CUADERNILLOS.mkdir(parents=True, exist_ok=True)
    PLANTILLAS.mkdir(parents=True, exist_ok=True)

    print("=== CUADERNILLOS (usipa.es) ===")
    try:
        html = bajar(LISTADO).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"no se pudo leer el listado: {e}", file=sys.stderr)
        html = ""

    encontrados: dict[str, str] = {}
    for url, texto in re.findall(
            r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>(.{0,200}?)</a>', html, re.S | re.I):
        limpio = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", texto)).strip()
        cat = categoria_de(limpio) or categoria_de(url)
        if cat and cat not in encontrados:
            encontrados[cat] = url

    for cat, url in sorted(encontrados.items()):
        ok, detalle = guardar_pdf(url, CUADERNILLOS / f"sespa2025_{cat}.pdf", pausa)
        print(f"  {cat:22} {'OK ' if ok else '!! '}{detalle}")

    esperadas = {"celador", "ayudante_servicios", "aux_administrativo", "tcae",
                 "jefe_taller", "higienista", "enfermeria"}
    faltan = sorted(esperadas - set(encontrados))
    if faltan:
        print(f"  NO están en usipa.es: {', '.join(faltan)}")

    print("\n=== PLANTILLAS (astursalud.es) ===")
    for cat, url in sorted(PLANTILLAS_URL.items()):
        ok, detalle = guardar_pdf(url, PLANTILLAS / f"sespa2025_{cat}_plantilla.pdf", pausa)
        print(f"  {cat:34} {'OK ' if ok else '!! '}{detalle}")

    print("\ncuadernillos con plantilla y examen:",
          ", ".join(sorted(set(encontrados) & set(PLANTILLAS_URL))) or "ninguno")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
