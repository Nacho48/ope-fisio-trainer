"""Agrupa las preguntas en familias semánticas: el «canon».

El tribunal no muestrea uniformemente el temario; redacta sobre lo que tiene a
mano, y por eso los mismos hechos reaparecen entre comunidades con otra
redacción. Una familia es un hecho, no un tema: "¿qué agente físico aumenta el
flujo sanguíneo?" y "¿cuál de estos produce vasodilatación superficial?" son la
misma pregunta escrita de dos formas.

El hash de enunciado solo encuentra copias literales (3 cruces entre organismos) y
la similitud difusa se queda en la superficie (441). Hace falta el nivel
semántico, así que se usan embeddings multilingües y clustering aglomerativo por
umbral de distancia — no k-means, porque no se sabe cuántas familias hay.

Se usa `transformers` directamente en vez de `sentence-transformers`: la versión
instalada de este último no importa (pide a transformers un CodeCarbonCallback que
no existe en el entorno). El pooling de medias sobre la máscara de atención es
exactamente lo que hace por dentro el modelo MiniLM de paráfrasis.

    python clustering_canon.py --umbral 0.35 --muestra 10
    python clustering_canon.py --barrido           # prueba varios umbrales
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CACHE_EMB = RAIZ / "corpus" / "embeddings.npy"
CACHE_IDS = RAIZ / "corpus" / "embeddings_ids.json"


def texto_para_embedding(r: dict) -> str:
    """Enunciado más opciones: dos preguntas del mismo hecho comparten ambos."""
    opts = " | ".join(r.get("opts") or [])
    return f"{r['q']} {opts}".strip()


def calcular_embeddings(textos: list[str], lote: int = 64) -> np.ndarray:
    import torch
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODELO)
    modelo = AutoModel.from_pretrained(MODELO)
    modelo.eval()

    salida = []
    with torch.no_grad():
        for i in range(0, len(textos), lote):
            trozo = textos[i:i + lote]
            enc = tok(trozo, padding=True, truncation=True, max_length=256,
                      return_tensors="pt")
            out = modelo(**enc).last_hidden_state
            mascara = enc["attention_mask"].unsqueeze(-1).float()
            # Media ponderada por la máscara: los PAD no deben contar.
            medias = (out * mascara).sum(1) / mascara.sum(1).clamp(min=1e-9)
            salida.append(torch.nn.functional.normalize(medias, p=2, dim=1).numpy())
            if (i // lote) % 10 == 0:
                print(f"  embeddings {i}/{len(textos)}", file=sys.stderr)
    return np.vstack(salida).astype(np.float32)


def obtener_embeddings(registros: list[dict], forzar: bool = False) -> np.ndarray:
    ids = [r["id"] for r in registros]
    if not forzar and CACHE_EMB.is_file() and CACHE_IDS.is_file():
        if json.loads(CACHE_IDS.read_text(encoding="utf-8")) == ids:
            print("embeddings recuperados de la caché", file=sys.stderr)
            return np.load(CACHE_EMB)

    emb = calcular_embeddings([texto_para_embedding(r) for r in registros])
    CACHE_EMB.parent.mkdir(parents=True, exist_ok=True)
    np.save(CACHE_EMB, emb)
    CACHE_IDS.write_text(json.dumps(ids), encoding="utf-8")
    return emb


def agrupar(emb: np.ndarray, umbral: float) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering

    # `average` con distancia coseno: un miembro nuevo entra en la familia si se
    # parece al conjunto, no solo al vecino más próximo (que encadenaría familias
    # distintas a través de eslabones sueltos).
    modelo = AgglomerativeClustering(
        n_clusters=None, distance_threshold=umbral,
        metric="cosine", linkage="average",
    )
    return modelo.fit_predict(emb)


def anio_de(r: dict) -> str:
    return str(r.get("fecha") or "")[:4] or "s/f"


def construir_familias(registros: list[dict], etiquetas: np.ndarray,
                       emb: np.ndarray, anio_actual: int = 2026) -> list[dict]:
    """Arma la ficha de cada familia con más de un miembro."""
    grupos: dict[int, list[int]] = {}
    for i, e in enumerate(etiquetas):
        grupos.setdefault(int(e), []).append(i)

    familias = []
    for etiqueta, indices in grupos.items():
        if len(indices) < 2:
            continue
        miembros = [registros[i] for i in indices]

        # El representante es el miembro más próximo al centro de la familia.
        centro = emb[indices].mean(axis=0)
        centro /= np.linalg.norm(centro) + 1e-9
        mejor = indices[int(np.argmax(emb[indices] @ centro))]

        convocatorias = sorted({f"{m['org']} {anio_de(m)}" for m in miembros})
        temas = Counter(m.get("tema_primario") for m in miembros
                        if m.get("tema_primario"))

        # Frecuencia ponderada por recencia: el canon se mueve, y una familia que
        # cae en 2024 pesa más que la misma en 2005. Semivida de 8 años.
        peso = 0.0
        for m in miembros:
            a = anio_de(m)
            antiguedad = anio_actual - int(a) if a.isdigit() else 12
            peso += 0.5 ** (max(antiguedad, 0) / 8.0)

        familias.append({
            "familia_id": int(etiqueta),
            "tamano": len(miembros),
            "tema_mayoritario": temas.most_common(1)[0][0] if temas else None,
            "temas": dict(temas),
            "organismos": sorted({m["org"] for m in miembros}),
            "anios": sorted({anio_de(m) for m in miembros}),
            "convocatorias": convocatorias,
            "n_convocatorias": len(convocatorias),
            "representante": registros[mejor]["q"],
            "representante_id": registros[mejor]["id"],
            "peso_recencia": round(peso, 3),
            "miembros": [m["id"] for m in miembros],
        })

    familias.sort(key=lambda f: (-f["n_convocatorias"], -f["peso_recencia"]))
    return familias


def informe_muestra(familias: list[dict], registros: list[dict], n: int,
                    semilla: int) -> str:
    por_id = {r["id"]: r for r in registros}
    aleatorio = random.Random(semilla)
    # Se muestrean familias de 2+ convocatorias: son las que sostienen el ranking.
    candidatas = [f for f in familias if f["n_convocatorias"] >= 2] or familias
    elegidas = aleatorio.sample(candidatas, min(n, len(candidatas)))

    lineas = []
    for f in elegidas:
        lineas.append(f"--- familia {f['familia_id']} · {f['tamano']} miembros · "
                      f"{f['n_convocatorias']} convocatorias · T{f['tema_mayoritario']} ---")
        for mid in f["miembros"][:6]:
            r = por_id[mid]
            lineas.append(f"    [{r['org']} {anio_de(r)}] {r['q'][:104]}")
        if f["tamano"] > 6:
            lineas.append(f"    … y {f['tamano'] - 6} más")
        lineas.append("")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=RAIZ / "corpus" / "clasificacion.jsonl")
    ap.add_argument("--umbral", type=float, default=0.35)
    ap.add_argument("--muestra", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--barrido", action="store_true", help="prueba varios umbrales")
    ap.add_argument("--out", type=Path, default=RAIZ / "corpus" / "familias.json")
    ap.add_argument("--recalcular", action="store_true")
    args = ap.parse_args()

    registros = [json.loads(l) for l in
                 args.corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"preguntas: {len(registros)}", file=sys.stderr)

    emb = obtener_embeddings(registros, forzar=args.recalcular)
    print(f"embeddings: {emb.shape}", file=sys.stderr)

    if args.barrido:
        print(f"{'umbral':>7} {'familias':>9} {'agrupadas':>10} {'mayor':>7} "
              f"{'2+conv':>7}")
        for u in (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50):
            et = agrupar(emb, u)
            fams = construir_familias(registros, et, emb)
            agrupadas = sum(f["tamano"] for f in fams)
            mayor = max((f["tamano"] for f in fams), default=0)
            multi = sum(1 for f in fams if f["n_convocatorias"] >= 2)
            print(f"{u:7.2f} {len(fams):9d} {agrupadas:10d} {mayor:7d} {multi:7d}")
        return 0

    etiquetas = agrupar(emb, args.umbral)
    familias = construir_familias(registros, etiquetas, emb)
    agrupadas = sum(f["tamano"] for f in familias)

    print(f"umbral {args.umbral}: {len(familias)} familias, {agrupadas} preguntas "
          f"agrupadas ({100*agrupadas/len(registros):.0f} %), "
          f"{sum(1 for f in familias if f['n_convocatorias'] >= 2)} en 2+ convocatorias")

    args.out.write_text(json.dumps(familias, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"escrito {args.out}")

    if args.muestra:
        print()
        print(informe_muestra(familias, registros, args.muestra, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
