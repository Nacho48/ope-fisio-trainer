"""Une los corpus parciales en un único `corpus/corpus.jsonl` ya validado.

La cuarentena queda fuera a propósito: son las preguntas que no pasaron el
control de calidad, no corpus.

    python exportar_corpus.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from schema import Corpus, partes_del_corpus

RAIZ = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus-dir", type=Path, default=RAIZ / "corpus")
    ap.add_argument("--out", type=Path, default=RAIZ / "corpus" / "corpus.jsonl")
    args = ap.parse_args()

    partes = partes_del_corpus(args.corpus_dir)
    if not partes:
        print("no hay corpus parciales que unir")
        return 1

    # Cargar con el esquema estricto: si algo incumple el contrato, revienta aquí
    # y no en el fichero que se entrega.
    c = Corpus.cargar(*partes)

    with args.out.open("w", encoding="utf-8") as fh:
        for r in c:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    verificadas = len(c.verificadas())
    print(f"unidas {len(partes)} partes -> {args.out}")
    for p in partes:
        print(f"   · {p.name}")
    print(f"{len(c)} preguntas | {verificadas} verificadas | "
          f"{len(c.sin_verificar)} sin verificar")
    print("por organismo: " + ", ".join(
        f"{k}={v}" for k, v in Counter(r["org"] for r in c).most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
