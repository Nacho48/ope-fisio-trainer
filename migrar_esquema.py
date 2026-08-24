"""Lleva los JSONL antiguos al esquema con `resp_verificada`.

El corpus del blog (SESCAM) se generó antes de que existiera el campo. Sus
preguntas traen la respuesta marcada en el propio HTML de origen, así que se
migran como verificadas y con `conf` 1.0: el texto es nativo, no OCR.

Es idempotente: pasarlo dos veces no cambia nada.

    python migrar_esquema.py corpus/*.jsonl
    python migrar_esquema.py corpus/corpus_sescam2026_p1.jsonl --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Valores por defecto de un corpus extraído de HTML con la respuesta ya marcada.
# `penalizacion` 0.0 vale para el SESCAM porque su convocatoria dice que los
# fallos no restan; los exámenes que sí penalizan la fijan en su propio ingestor.
DEFECTOS = {"conf": 1.0, "origen": "html", "revisar": False,
            "penalizacion": 0.0, "reserva": False}


def migrar_registro(r: dict) -> tuple[dict, bool]:
    """Devuelve el registro migrado y si ha cambiado algo."""
    antes = dict(r)

    if "resp_verificada" not in r:
        # Sin el campo, el criterio es la propia respuesta: si el parser sacó
        # letra del HTML, está verificada; si no, no lo está y `resp` va a None.
        r["resp_verificada"] = r.get("resp") in ("A", "B", "C", "D")
        if not r["resp_verificada"]:
            r["resp"] = None

    for campo, valor in DEFECTOS.items():
        r.setdefault(campo, valor)

    return r, r != antes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ficheros", nargs="+", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for ruta in args.ficheros:
        registros, cambiados = [], 0
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            r, cambio = migrar_registro(json.loads(linea))
            registros.append(r)
            cambiados += cambio

        verificadas = sum(1 for r in registros if r["resp_verificada"])
        print(f"{ruta.name}: {len(registros)} registros, {cambiados} migrados, "
              f"{verificadas} verificadas / {len(registros) - verificadas} sin verificar")

        if not args.dry_run and cambiados:
            with ruta.open("w", encoding="utf-8") as fh:
                for r in registros:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    if args.dry_run:
        print("[--dry-run] no se ha escrito nada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
