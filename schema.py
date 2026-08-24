"""Esquema del corpus y carga con separación dura entre verificado y no verificado.

La regla que sostiene todo el análisis: **una pregunta sin respuesta oficial
comprobada no puede entrar en ningún cálculo que dependa de la respuesta.**

Las 700 preguntas de las baterías de Osakidetza vienen sin solucionario (lo
comprobamos: la negrita marca el enunciado, no la opción correcta, y los PDF no
traen plantilla). Si se colaran en la distribución de letras o en el sesgo de
longitud, contaminarían justo las métricas que alimentan el parámetro de acierto
por descarte.

Por eso el filtrado no es un argumento opcional que uno pueda olvidar, sino un
tipo aparte: `SoloVerificadas`. Las funciones de `stats.py` que tocan `resp` lo
exigen, y su constructor rechaza cualquier registro con `resp_verificada` falso.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

CAMPOS_OBLIGATORIOS = (
    "id", "org", "ccaa", "fecha", "turno", "num", "bloque",
    "q", "opts", "resp", "resp_verificada", "conf", "origen",
    "penalizacion", "reserva",
)

# Fracción del acierto que resta cada fallo, medida en la convocatoria de cada
# examen. No es un detalle: cambia el valor esperado de contestar sin saber, así
# que dos exámenes con penalización distinta no son comparables sin marcarlo.
#   SAS 2025   1/4 — portada del cuadernillo
#   Asturias   1/5 — BOPA 9-VIII-2018, pág. 7 ("el quinto del valor asignado")
#   SESCAM     0   — los fallos no restan
#   Osakidetza None — baterías de estudio, no un examen: no procede
PENALIZACIONES_CONOCIDAS = {"SAS": 0.25, "SESPA": 0.20, "SESCAM": 0.0}

LETRAS_VALIDAS = ("A", "B", "C", "D")


class CorpusInvalido(ValueError):
    """El corpus incumple el contrato del esquema."""


# Derivados que viven en `corpus/` pero no son partes: el export con todo junto,
# la cuarentena y la clasificación por tema (que es el corpus reanotado). Cargarlos
# junto a las partes duplicaría cada id.
# `corpus_autonomico_sespa2025.jsonl` es un entregable con formato propio
# (enunciado/opciones en vez de q/opts); el generador del trainer lo traduce.
DERIVADOS = {"corpus.jsonl", "clasificacion.jsonl", "cuarentena.jsonl",
             "corpus_autonomico_sespa2025.jsonl"}


def partes_del_corpus(directorio: Path) -> list[Path]:
    """Los JSONL que componen el corpus, sin los derivados."""
    return [p for p in sorted(Path(directorio).glob("*.jsonl"))
            if p.name not in DERIVADOS and "cuarentena" not in p.name]


def normalizar(texto: str) -> str:
    """Clave de comparación de enunciados: sin tildes, sin puntuación, colapsado."""
    s = unicodedata.normalize("NFKD", texto.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def validar_registro(r: dict[str, Any], origen: str = "") -> list[str]:
    """Devuelve la lista de incumplimientos de un registro (vacía si es válido)."""
    fallos = []
    donde = f"{origen}:{r.get('id', '¿sin id?')}"

    for campo in CAMPOS_OBLIGATORIOS:
        if campo not in r:
            fallos.append(f"{donde}: falta el campo '{campo}'")

    if not isinstance(r.get("resp_verificada"), bool):
        fallos.append(f"{donde}: 'resp_verificada' debe ser booleano")

    resp, verificada = r.get("resp"), r.get("resp_verificada")
    if verificada and resp not in LETRAS_VALIDAS:
        fallos.append(f"{donde}: marcada como verificada pero resp={resp!r}")
    if verificada is False and resp is not None:
        fallos.append(f"{donde}: no verificada pero trae resp={resp!r}")

    if not isinstance(r.get("opts"), list) or not r.get("opts"):
        fallos.append(f"{donde}: 'opts' vacío o no es lista")
    if not str(r.get("q", "")).strip():
        fallos.append(f"{donde}: enunciado vacío")

    conf = r.get("conf")
    if not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
        fallos.append(f"{donde}: 'conf' fuera de [0,1]: {conf!r}")

    # `penalizacion` admite None ("no consta") pero nunca un valor absurdo: un 0.0
    # inventado diría "este examen no penaliza", que es una afirmación, no un hueco.
    pena = r.get("penalizacion")
    if pena is not None and (not isinstance(pena, (int, float)) or not 0.0 <= float(pena) <= 1.0):
        fallos.append(f"{donde}: 'penalizacion' fuera de [0,1]: {pena!r}")

    if not isinstance(r.get("reserva"), bool):
        fallos.append(f"{donde}: 'reserva' debe ser booleano")

    return fallos


@dataclass(frozen=True)
class Corpus:
    """Todas las preguntas. Solo permite análisis que NO dependan de la respuesta."""

    registros: tuple[dict[str, Any], ...]

    @classmethod
    def cargar(cls, *rutas: Path, estricto: bool = True) -> "Corpus":
        registros: list[dict[str, Any]] = []
        fallos: list[str] = []
        vistos: dict[str, str] = {}

        for ruta in rutas:
            for n, linea in enumerate(Path(ruta).read_text(encoding="utf-8").splitlines(), 1):
                if not linea.strip():
                    continue
                try:
                    r = json.loads(linea)
                except json.JSONDecodeError as e:
                    fallos.append(f"{ruta.name}:{n}: JSON ilegible ({e})")
                    continue
                fallos += validar_registro(r, ruta.name)
                if r.get("id") in vistos:
                    fallos.append(f"{ruta.name}: id duplicado {r['id']} (ya en {vistos[r['id']]})")
                else:
                    vistos[str(r.get("id"))] = ruta.name
                registros.append(r)

        if fallos and estricto:
            raise CorpusInvalido(
                f"{len(fallos)} problemas en el corpus:\n  " + "\n  ".join(fallos[:20])
            )
        return cls(registros=tuple(registros))

    def __len__(self) -> int:
        return len(self.registros)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.registros)

    @property
    def sin_verificar(self) -> tuple[dict[str, Any], ...]:
        return tuple(r for r in self.registros if not r.get("resp_verificada"))

    def verificadas(self) -> "SoloVerificadas":
        """Única puerta de entrada a los cálculos que dependen de la respuesta."""
        return SoloVerificadas(
            registros=tuple(r for r in self.registros if r.get("resp_verificada"))
        )


@dataclass(frozen=True)
class SoloVerificadas:
    """Subconjunto con respuesta oficial comprobada.

    Tipo distinto a `Corpus` a propósito: las funciones que leen `resp` lo piden
    por firma, así que pasarles el corpus entero es un error visible, no un sesgo
    silencioso. El constructor vuelve a comprobar la invariante por si alguien
    construye la instancia a mano.
    """

    registros: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        intrusos = [r.get("id") for r in self.registros if not r.get("resp_verificada")]
        if intrusos:
            raise CorpusInvalido(
                f"SoloVerificadas contiene {len(intrusos)} registros sin verificar: "
                f"{intrusos[:5]}"
            )
        sin_letra = [r.get("id") for r in self.registros if r.get("resp") not in LETRAS_VALIDAS]
        if sin_letra:
            raise CorpusInvalido(f"registros verificados sin letra válida: {sin_letra[:5]}")

    def __len__(self) -> int:
        return len(self.registros)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.registros)
