"""Genera `trainer.html`: un entrenador autocontenido que funciona sin servidor.

Todo va embebido en un único fichero porque el destino es abrirlo desde el
sistema de archivos del móvil: con `file://` un `fetch` a un JSON de al lado lo
bloquea la política de mismo origen, así que los datos tienen que viajar dentro
del HTML.

Los campos se abrevian (`q`, `o`, `r`, `fam`…) para que el fichero no se dispare:
son 3.000 preguntas con sus opciones y cada carácter se multiplica por cuatro.

    python generar_trainer.py
    python generar_trainer.py --sin-familias      # si aún no hay clustering
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MAX_CONTEXTO = 700          # los casos clínicos del SAS llegan a ser muy largos
MAX_CONVOCATORIAS_CHIP = 6  # en el móvil no caben más


def nombres_de_temas(ruta: Path) -> dict[int, str]:
    """Nombre corto de cada tema: su primera frase, que es la que lo identifica."""
    nombres: dict[int, str] = {}
    if not ruta.is_file():
        return nombres
    for linea in ruta.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^(\d{1,2})\.\s+(.*)$", linea.strip())
        if not m:
            continue
        texto = m.group(2)
        corte = re.split(r"(?<=[a-záéíóúñ0-9\)])[.:]\s", texto, maxsplit=1)[0]
        nombres[int(m.group(1))] = corte.strip()[:70]
    return nombres


# El examen son 15 preguntas de la parte general y 65 de la específica (base 7.1).
N_GENERAL, N_ESPECIFICO = 15, 65
TEMA_MAX_GENERAL = 11
# Margen honesto de la proyección: con ~134 preguntas de muestra, un tema de 12
# casos se mueve unas ±3 preguntas. Basta para decir quién está en el grupo de
# cabeza, no para ordenar dentro de él.
MARGEN_PREGUNTAS = 3


def pesos_por_tema(ruta_referencia: Path) -> tuple[dict[int, dict], dict]:
    """Proyecta la frecuencia observada de cada tema sobre las 80 del examen.

    La muestra es la clasificación revisada a mano: es la única medición del
    reparto real, porque el corpus completo mezcla comunidades con temarios
    distintos y sobrerrepresenta a quien más exámenes publica.
    """
    from collections import Counter

    referencia = json.loads(ruta_referencia.read_text(encoding="utf-8"))
    temas = [r["tema"] for r in referencia if r.get("tema")]
    especificos = Counter(t for t in temas if t > TEMA_MAX_GENERAL)
    generales = Counter(t for t in temas if t <= TEMA_MAX_GENERAL)
    n_esp, n_gen = sum(especificos.values()), sum(generales.values())

    # Suavizado de Laplace. Un tema que no salió en la muestra no es un tema que
    # no caiga: es uno que cae poco, y darle 0 lo excluiría del todo mientras que
    # darle el reparto uniforme lo sobrevalora. Con alfa 0,5 recibe una fracción
    # pequeña y, sobre todo, el reparto suma exactamente 65 + 15 = 80 preguntas.
    # Sin esto la suma daba 92,2 y la proyección de nota salía inflada un 15 %.
    ALFA = 0.5
    pesos: dict[int, dict] = {}
    for temas_bloque, cuenta, n_bloque, total_temas, n_preguntas in (
            (range(TEMA_MAX_GENERAL + 1, 45), especificos, n_esp, 33, N_ESPECIFICO),
            (range(1, TEMA_MAX_GENERAL + 1), generales, n_gen, TEMA_MAX_GENERAL, N_GENERAL)):
        denominador = n_bloque + ALFA * total_temas
        for tema in temas_bloque:
            n = cuenta.get(tema, 0)
            pesos[tema] = {"n": n,
                           "esp": round((n + ALFA) / denominador * n_preguntas, 2)}

    meta = {
        "nEsp": n_esp,
        "nGen": n_gen,
        "uniformeEsp": round(N_ESPECIFICO / 33, 2),
        "uniformeGen": round(N_GENERAL / TEMA_MAX_GENERAL, 2),
        "margen": MARGEN_PREGUNTAS,
        "nExamen": N_GENERAL + N_ESPECIFICO,
    }
    return pesos, meta


def cargar_autonomico(ruta: Path) -> list[dict]:
    """Trae el bloque autonómico del SESPA 2025 al esquema del corpus.

    Viene con su propio formato (opciones en diccionario, respuesta en minúscula)
    porque es un entregable aparte; aquí se traduce sin tocar el fichero original.
    Es el material de más valor del corpus: mismo organismo, misma legislación
    autonómica vigente y del ciclo OPE en curso, y ninguna otra comunidad lo cubre.
    """
    if not ruta.is_file():
        return []
    salida = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        r = json.loads(linea)
        letras = ["a", "b", "c", "d"]
        salida.append({
            "id": r["id"],
            "org": "SESPA",
            "ccaa": "Asturias",
            "fecha": r.get("fecha_examen"),
            "turno": None,
            "num": 0,
            "bloque": "general",
            "q": r["enunciado"],
            "opts": [r["opciones"].get(l, "") for l in letras],
            "resp": (r.get("respuesta_correcta") or "").upper(),
            "resp_verificada": True,
            "conf": 1.0,
            "origen": "ocr",
            "penalizacion": 0.0,       # la convocatoria de 2025 no penaliza
            "reserva": False,
            "revisar": False,
            "ambito": "autonomico",
            "categoria_origen": r.get("categoria"),
            "tema_primario": int(str(r["tema"]).lstrip("T")) if r.get("tema") else None,
            "tema_secundario": None,
            "tema_evidencia": f"bloque autonómico · {r.get('categoria')} "
                              f"{r.get('fecha_examen')}",
        })
    return salida


def compactar(r: dict, fam_de_id: dict[str, int]) -> dict:
    fila = {
        "id": r["id"],
        "q": r["q"],
        "o": r["opts"],
        "r": r["resp"],
        "tema": r.get("tema_primario"),
        "fam": fam_de_id.get(r["id"]),
        "org": r["org"],
        "a": str(r.get("fecha") or "")[:4] or None,
    }
    if r.get("ambito"):
        fila["amb"] = r["ambito"]
    if r.get("categoria_origen"):
        # De qué categoría salió: no se lee igual fallar una de Enfermería 2025
        # que una de Fisioterapia.
        fila["cat"] = r["categoria_origen"]
    ctx = r.get("contexto")
    if ctx:
        fila["ctx"] = ctx[:MAX_CONTEXTO]
    return fila


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clasificacion", type=Path,
                    default=RAIZ / "corpus" / "clasificacion.jsonl")
    ap.add_argument("--familias", type=Path, default=RAIZ / "corpus" / "familias.json")
    ap.add_argument("--plantilla", type=Path, default=RAIZ / "trainer_template.html")
    ap.add_argument("--out", type=Path, default=RAIZ / "trainer.html")
    ap.add_argument("--temario", type=Path, default=RAIZ / "docs" / "temario_44.md")
    ap.add_argument("--referencia", type=Path,
                    default=RAIZ / "docs" / "clasificacion_150_v2.json")
    ap.add_argument("--autonomico", type=Path,
                    default=RAIZ / "corpus" / "corpus_autonomico_sespa2025.jsonl")
    ap.add_argument("--sin-familias", action="store_true")
    args = ap.parse_args()

    registros = [json.loads(l) for l in
                 args.clasificacion.read_text(encoding="utf-8").splitlines() if l.strip()]
    registros += cargar_autonomico(args.autonomico)
    # Sin respuesta no hay nada que entrenar.
    registros = [r for r in registros if r.get("resp") in ("A", "B", "C", "D")]

    familias_js: dict[str, dict] = {}
    fam_de_id: dict[str, int] = {}
    if not args.sin_familias and args.familias.is_file():
        for f in json.loads(args.familias.read_text(encoding="utf-8")):
            fid = f["familia_id"]
            familias_js[str(fid)] = {
                "n": f["tamano"],
                "c": f["n_convocatorias"],
                # Recencia MEDIA por miembro, entre 0 y 1: 1 = todas de este año,
                # 0,5 = de hace ocho años. La suma bruta crecía con el tamaño de
                # la familia, así que mezclaba "es reciente" con "es grande" y
                # daba cifras como 12,99 imposibles de comparar con el resto.
                "rm": round(f["peso_recencia"] / max(f["tamano"], 1), 3),
                "d": f["convocatorias"][:MAX_CONVOCATORIAS_CHIP],
            }
            for mid in f["miembros"]:
                fam_de_id[mid] = fid

    preguntas = [compactar(r, fam_de_id) for r in registros]
    temas = nombres_de_temas(args.temario)
    pesos, pesos_meta = pesos_por_tema(args.referencia)

    # Ranking por preguntas esperadas: es el orden en que hay que atacar el temario.
    orden = sorted(pesos.items(), key=lambda kv: -kv[1]["esp"])
    for puesto, (tema, datos_tema) in enumerate(
            (t for t in orden if t[0] > TEMA_MAX_GENERAL), start=1):
        datos_tema["rank"] = puesto

    datos = {
        "preguntas": preguntas,
        "familias": familias_js,
        "temas": {str(k): v for k, v in sorted(temas.items())},
        "pesos": {str(k): v for k, v in sorted(pesos.items())},
        "pesosMeta": pesos_meta,
        "meta": {
            "n": len(preguntas),
            "con_tema": sum(1 for p in preguntas if p["tema"]),
            "con_familia": sum(1 for p in preguntas if p["fam"] is not None),
            "familias": len(familias_js),
        },
    }

    plantilla = args.plantilla.read_text(encoding="utf-8")
    marca = ('/*__DATOS__*/{"preguntas":[],"familias":{},"temas":{},'
             '"pesos":{},"pesosMeta":{},"meta":{}}')
    if marca not in plantilla:
        raise SystemExit("la plantilla no tiene el marcador de datos")

    # separators sin espacios: en 3.000 preguntas cada byte cuenta.
    json_datos = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    # `</script>` dentro de una cadena JSON cerraría el bloque del navegador.
    json_datos = json_datos.replace("</", "<\\/")

    args.out.write_text(plantilla.replace(marca, json_datos), encoding="utf-8")

    kb = args.out.stat().st_size / 1024
    print(f"{args.out}  ({kb:.0f} KB)")
    print(f"  preguntas   : {datos['meta']['n']}")
    print(f"  con tema    : {datos['meta']['con_tema']}")
    print(f"  con familia : {datos['meta']['con_familia']} "
          f"en {datos['meta']['familias']} familias")
    generales = sum(1 for p in preguntas if p["tema"] and p["tema"] <= 11)
    print(f"  parte general: {generales} · específico: "
          f"{sum(1 for p in preguntas if p['tema'] and p['tema'] > 11)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
