"""Métricas del corpus, con las preguntas sin respuesta verificada fuera de juego.

El corpus mezcla dos cosas muy distintas: exámenes con plantilla oficial (SESCAM,
Asturias) y baterías de preguntas sin solucionario publicado (Osakidetza, 700 de
las 845 actuales). Si esas 700 entraran en la distribución de letras o en el
sesgo de longitud, no sesgarían un poco: dominarían el resultado.

La separación es de tipos, no de disciplina. Todo lo que lee `resp` recibe
`SoloVerificadas`; todo lo que cuenta enunciados recibe `Corpus` entero. Pasarle
un `Corpus` a una función de respuesta es un `TypeError` en la primera línea, no
un número silenciosamente equivocado.

    python stats.py
    python stats.py --corpus corpus/corpus_asturias2019.jsonl
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from scipy import stats as sps

from schema import Corpus, SoloVerificadas, normalizar, partes_del_corpus

LETRAS = ("A", "B", "C", "D")

# Opciones "comodín" cuya frecuencia y acierto interesan para adivinar por descarte.
RE_COMODIN = re.compile(
    r"\b(todas (las anteriores |las opciones )?son (correctas|ciertas|verdaderas)"
    r"|ninguna (de las anteriores|es correcta|de las opciones)"
    r"|todas son falsas|a\) b\) y c\) son correctas)\b",
    re.IGNORECASE,
)


def _exigir_verificadas(c: object) -> SoloVerificadas:
    """Puerta de entrada de toda métrica que dependa de la respuesta."""
    if not isinstance(c, SoloVerificadas):
        raise TypeError(
            "esta métrica depende de la respuesta correcta y solo acepta "
            f"SoloVerificadas; ha recibido {type(c).__name__}. Use corpus.verificadas()."
        )
    return c


# --- métricas que NO dependen de la respuesta (todo el corpus) --------------------

def inventario(c: Corpus) -> list[str]:
    por_org = Counter(r["org"] for r in c)
    por_ccaa = Counter(r["ccaa"] for r in c)
    por_origen = Counter(r.get("origen", "?") for r in c)
    sin_verificar = Counter(r["org"] for r in c.sin_verificar)

    lineas = [f"preguntas en el corpus : {len(c)}"]
    lineas.append("  por organismo : " + ", ".join(f"{k}={v}" for k, v in por_org.most_common()))
    lineas.append("  por CCAA      : " + ", ".join(f"{k}={v}" for k, v in por_ccaa.most_common()))
    lineas.append("  por origen    : " + ", ".join(f"{k}={v}" for k, v in por_origen.most_common()))
    lineas.append(
        f"  SIN respuesta verificada: {len(c.sin_verificar)} "
        f"({', '.join(f'{k}={v}' for k, v in sin_verificar.most_common())})"
    )
    baja_conf = [r["id"] for r in c if float(r.get("conf", 1.0)) < 1.0]
    lineas.append(f"  procedentes de OCR (conf<1.0): {len(baja_conf)}")

    penas = Counter(
        "no consta" if r.get("penalizacion") is None else f"{r['penalizacion']:g}"
        for r in c
    )
    lineas.append("  penalización por fallo: "
                  + ", ".join(f"{k}={v}" for k, v in penas.most_common()))
    lineas.append(f"  preguntas de reserva  : {sum(1 for r in c if r.get('reserva'))} "
                  f"(no puntuaron, pero salieron del mismo banco)")
    return lineas


# Un enunciado corto no es un hecho, es una fórmula de redacción: "SEÑALE LA
# RESPUESTA CORRECTA" se repite nueve veces sin decir nada del temario. El ranking
# temático solo cuenta enunciados con contenido propio.
MIN_CARACTERES_RECURRENCIA = 80


def recurrencias(c: Corpus, top: int = 40,
                 min_caracteres: int = MIN_CARACTERES_RECURRENCIA) -> list[str]:
    """Enunciados repetidos entre exámenes. Cuenta TODO el corpus, verificado o no.

    Una pregunta de Osakidetza sin solucionario sigue siendo prueba de que ese
    enunciado se repite, que es justo lo que se quiere medir aquí.
    """
    grupos: dict[str, list[dict]] = {}
    descartados = 0
    for r in c:
        if len(r["q"]) < min_caracteres:
            descartados += 1
            continue
        grupos.setdefault(normalizar(r["q"]), []).append(r)

    def examenes(regs: list[dict]) -> list[str]:
        """Convocatorias distintas en que aparece el enunciado, sin repetir.

        La identidad de un examen es (organismo, año), no el fichero de origen:
        el examen del SAS 2025 está a la vez en su PDF oficial y en el blog, y
        contar eso como dos apariciones convertiría un duplicado de fuente en una
        recurrencia inexistente.
        """
        vistos: dict[str, None] = {}
        for r in sorted(regs, key=lambda x: (x["org"], str(x.get("fecha") or ""))):
            anio = str(r.get("fecha") or "")[:4] or "s/f"
            vistos.setdefault(f"{r['org']} {anio}", None)
        return list(vistos)

    repetidos = sorted(
        ((k, v) for k, v in grupos.items() if len(examenes(v)) > 1),
        key=lambda kv: (-len(examenes(kv[1])), kv[1][0]["q"]),
    )
    solo_una_fuente = sum(1 for v in grupos.values()
                          if len(v) > 1 and len(examenes(v)) == 1)

    lineas = [
        f"enunciados de {min_caracteres}+ caracteres en DOS O MÁS convocatorias: "
        f"{len(repetidos)}",
        f"  (descartados {descartados} enunciados más cortos, son fórmulas de "
        f"redacción; y {solo_una_fuente} repetidos dentro de una misma "
        f"convocatoria, que son solapamiento entre fuentes)",
    ]
    for i, (_, regs) in enumerate(repetidos[:top], start=1):
        donde = examenes(regs)
        lineas.append(f"{i:3d}. en {len(donde)} convocatorias  {regs[0]['q'][:92]}")
        lineas.append(f"        [{', '.join(donde)}]")
    return lineas


def aparicion_comodines(c: Corpus) -> list[str]:
    con_comodin = [r for r in c if any(RE_COMODIN.search(o) for o in r["opts"])]
    pct = 100 * len(con_comodin) / len(c) if len(c) else 0
    return [f"preguntas con opción comodín: {len(con_comodin)} ({pct:.1f} % del corpus)"]


# --- métricas que SÍ dependen de la respuesta (solo verificadas) ------------------

def distribucion_letra(c: SoloVerificadas) -> list[str]:
    c = _exigir_verificadas(c)
    cuenta = Counter(r["resp"] for r in c)
    total = sum(cuenta.values())
    lineas = [f"distribución de la letra correcta (n={total}):"]
    for letra in LETRAS:
        n = cuenta.get(letra, 0)
        pct = 100 * n / total if total else 0
        marca = "  <-- SOSPECHOSO" if pct > 45 else ""
        lineas.append(f"  {letra}: {n:4d}  {pct:5.1f} %{marca}")
    return lineas


def acierto_comodines(c: SoloVerificadas) -> list[str]:
    """¿Con qué probabilidad acierta quien marca la opción comodín cuando aparece?"""
    c = _exigir_verificadas(c)
    apariciones = aciertos = 0
    for r in c:
        indices = [i for i, o in enumerate(r["opts"]) if RE_COMODIN.search(o)]
        if not indices:
            continue
        apariciones += 1
        correcta = LETRAS.index(r["resp"])
        if correcta in indices:
            aciertos += 1

    if not apariciones:
        return ["opción comodín: no aparece en las preguntas verificadas"]
    pct = 100 * aciertos / apariciones
    return [
        f"opción comodín: aparece en {apariciones} preguntas verificadas y es "
        f"la correcta en {aciertos} ({pct:.1f} %; el azar daría 25 %)"
    ]


def sesgo_longitud(c: SoloVerificadas) -> list[str]:
    """¿Es la opción correcta más larga que las demás? t de Student pareada."""
    c = _exigir_verificadas(c)
    diferencias = []
    for r in c:
        if len(r["opts"]) != 4:
            continue
        correcta = LETRAS.index(r["resp"])
        larga = len(r["opts"][correcta])
        otras = [len(o) for i, o in enumerate(r["opts"]) if i != correcta]
        diferencias.append(larga - sum(otras) / len(otras))

    if len(diferencias) < 3:
        return ["sesgo de longitud: muestra insuficiente"]

    t, p = sps.ttest_1samp(diferencias, 0.0)
    media = sum(diferencias) / len(diferencias)
    veredicto = "SIGNIFICATIVO" if p < 0.05 else "no significativo"
    return [
        f"sesgo de longitud (n={len(diferencias)}): la correcta mide "
        f"{media:+.1f} caracteres frente a la media de las otras tres",
        f"  t={t:.2f}  p={p:.4f}  -> {veredicto}",
    ]


def enunciados_negativos(c: SoloVerificadas) -> list[str]:
    """¿Cambia la posición de la correcta entre preguntas en positivo y en negativo?"""
    c = _exigir_verificadas(c)
    grupos: dict[str, Counter] = {"NEGATIVO": Counter(), "POSITIVO": Counter()}
    for r in c:
        negativa = re.search(r"\b(INCORRECTA|FALSA|NO ES|EXCEPTO|FALSO)\b", r["q"], re.I)
        grupos["NEGATIVO" if negativa else "POSITIVO"][r["resp"]] += 1

    lineas = []
    for clave, cuenta in grupos.items():
        total = sum(cuenta.values())
        if not total:
            continue
        reparto = " ".join(f"{l}={100*cuenta.get(l,0)/total:4.1f}%" for l in LETRAS)
        lineas.append(f"  {clave:9} n={total:4d}  {reparto}")
    return ["posición de la correcta según el signo del enunciado:"] + lineas


def acierto_por_descarte(c: SoloVerificadas) -> list[str]:
    """Cota del parámetro que alimenta el modelo: acertar sin saber la materia.

    Se desglosa por régimen de penalización porque un mismo porcentaje de acierto
    vale cosas distintas: donde el fallo resta ¼, contestar a ciegas solo compensa
    si el acierto supera el 20 %. El valor esperado en unidades de "una respuesta
    correcta" es `p_acierto - (1 - p_acierto) * penalización`.
    """
    c = _exigir_verificadas(c)
    por_regimen: dict[float | None, Counter] = {}
    for r in c:
        por_regimen.setdefault(r.get("penalizacion"), Counter())[r["resp"]] += 1

    lineas = ["acierto marcando siempre la letra más frecuente:"]
    for pena, cuenta in sorted(por_regimen.items(), key=lambda kv: (kv[0] is None, kv[0])):
        total = sum(cuenta.values())
        mejor, n = cuenta.most_common(1)[0]
        acierto = n / total
        etiqueta = "sin penalización" if not pena else f"penalización {pena:g}"
        if pena:
            ev = acierto - (1 - acierto) * pena
            juicio = "compensa" if ev > 0 else "NO compensa"
            extra = f" -> valor esperado {ev:+.3f} por pregunta: {juicio}"
        else:
            extra = " -> contestar siempre es gratis"
        lineas.append(
            f"  {etiqueta:18} n={total:4d}  '{mejor}' acierta {100*acierto:.1f} %{extra}"
        )
    return lineas


def informe(c: Corpus) -> str:
    verificadas = c.verificadas()
    bloques = [
        ("INVENTARIO", inventario(c)),
        ("SIN DEPENDER DE LA RESPUESTA (corpus entero)", aparicion_comodines(c)),
        (f"DEPENDEN DE LA RESPUESTA (solo {len(verificadas)} verificadas)",
         distribucion_letra(verificadas)
         + acierto_comodines(verificadas)
         + sesgo_longitud(verificadas)
         + enunciados_negativos(verificadas)
         + acierto_por_descarte(verificadas)),
        ("RECURRENCIAS", recurrencias(c)),
    ]
    partes = []
    for titulo, lineas in bloques:
        partes.append(f"--- {titulo} " + "-" * max(0, 68 - len(titulo)))
        partes += lineas
    return "\n".join(partes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, nargs="*", default=None,
                    help="JSONL a analizar (por defecto, todos los de corpus/)")
    ap.add_argument("--informe", type=Path, default=None)
    args = ap.parse_args()

    rutas = args.corpus or partes_del_corpus(Path(__file__).parent / "corpus")
    if not rutas:
        print("no hay ningún JSONL que analizar")
        return 1

    texto = informe(Corpus.cargar(*rutas))
    print(texto)
    if args.informe:
        args.informe.write_text(texto, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
