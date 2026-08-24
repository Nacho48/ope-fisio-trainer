"""La garantía central: una pregunta sin respuesta oficial no entra en los cálculos.

No basta con que hoy el código filtre bien. Estos tests fijan que *no se pueda*
colar una pregunta sin verificar en una métrica de respuesta ni por descuido ni
por un futuro refactor.
"""

from __future__ import annotations

import json

import pytest

import stats
from schema import Corpus, CorpusInvalido, SoloVerificadas, validar_registro

BASE = {
    "id": "X-001", "org": "X", "ccaa": "Y", "fecha": None, "turno": None,
    "num": 1, "bloque": None, "q": "Un enunciado suficientemente largo:",
    "opts": ["a", "b", "c", "d"], "resp": "A", "resp_verificada": True,
    "conf": 1.0, "origen": "test", "penalizacion": 0.0, "reserva": False,
}


def registro(**cambios):
    return {**BASE, **cambios}


def test_solo_verificadas_rechaza_las_no_verificadas():
    sin_verificar = registro(id="X-002", resp=None, resp_verificada=False)
    with pytest.raises(CorpusInvalido, match="sin verificar"):
        SoloVerificadas(registros=(sin_verificar,))


def test_solo_verificadas_rechaza_verificada_sin_letra():
    with pytest.raises(CorpusInvalido, match="letra válida"):
        SoloVerificadas(registros=(registro(resp="Z"),))


def test_corpus_verificadas_filtra():
    c = Corpus(registros=(
        registro(id="A"),
        registro(id="B", resp=None, resp_verificada=False),
    ))
    assert len(c) == 2
    assert len(c.verificadas()) == 1
    assert len(c.sin_verificar) == 1


@pytest.mark.parametrize("metrica", [
    stats.distribucion_letra,
    stats.acierto_comodines,
    stats.sesgo_longitud,
    stats.enunciados_negativos,
    stats.acierto_por_descarte,
])
def test_las_metricas_de_respuesta_rechazan_el_corpus_entero(metrica):
    """Pasar el corpus completo es un error ruidoso, no un número sesgado."""
    c = Corpus(registros=(registro(),))
    with pytest.raises(TypeError, match="SoloVerificadas"):
        metrica(c)


def test_las_metricas_de_respuesta_aceptan_el_subconjunto():
    c = Corpus(registros=(
        registro(id="A", resp="A"),
        registro(id="B", resp="B"),
        registro(id="C", resp=None, resp_verificada=False),
    ))
    salida = "\n".join(stats.distribucion_letra(c.verificadas()))
    assert "n=2" in salida  # la tercera no cuenta


# El ranking solo mira enunciados de 80+ caracteres, así que los de prueba tienen
# que serlo de verdad; y "recurrencia" es aparecer en dos convocatorias distintas.
ENUNCIADO_LARGO = ("¿Cuál de las siguientes afirmaciones sobre el tratamiento "
                   "fisioterápico del hombro doloroso es la correcta?")


def test_las_no_verificadas_si_cuentan_en_recurrencias():
    """Sin solucionario, el enunciado sigue siendo prueba de que se repite."""
    c = Corpus(registros=(
        registro(id="A", q=ENUNCIADO_LARGO, org="X", fecha="2015-01-01",
                 resp=None, resp_verificada=False),
        registro(id="B", q=ENUNCIADO_LARGO, org="Y", fecha="2020-01-01",
                 resp=None, resp_verificada=False),
    ))
    assert "en 2 convocatorias" in "\n".join(stats.recurrencias(c))


def test_una_pregunta_repetida_en_la_misma_convocatoria_no_es_recurrencia():
    """Estar en el PDF oficial y en el blog es solapamiento de fuentes, no señal."""
    c = Corpus(registros=(
        registro(id="A", q=ENUNCIADO_LARGO, org="SAS", fecha="2025-01-01",
                 origen="pdf_texto"),
        registro(id="B", q=ENUNCIADO_LARGO, org="SAS", fecha="2025-06-30",
                 origen="html"),
    ))
    salida = "\n".join(stats.recurrencias(c))
    assert "en 2 convocatorias" not in salida
    assert "1 repetidos dentro de una misma" in salida


def test_las_formulas_de_redaccion_no_entran_en_el_ranking():
    """"Señale la respuesta correcta" se repite sin decir nada del temario."""
    c = Corpus(registros=(
        registro(id="A", q="Señale la respuesta CORRECTA:", org="X", fecha="2015-01-01"),
        registro(id="B", q="Señale la respuesta CORRECTA:", org="Y", fecha="2020-01-01"),
    ))
    assert "en 2 convocatorias" not in "\n".join(stats.recurrencias(c))


def test_penalizacion_admite_none_pero_no_valores_absurdos():
    """None es "no consta"; un 0.0 inventado afirmaría que el examen no penaliza."""
    assert not [f for f in validar_registro(registro(penalizacion=None))
                if "penalizacion" in f]
    assert any("'penalizacion' fuera de" in f
               for f in validar_registro(registro(penalizacion=7)))


def test_reserva_debe_ser_booleano():
    assert any("'reserva' debe ser booleano"
               in f for f in validar_registro(registro(reserva="sí")))


def test_las_de_reserva_cuentan_como_evidencia_de_tema():
    """No puntuaron, pero salieron del mismo banco: siguen contando en frecuencias."""
    c = Corpus(registros=(
        registro(id="A", q=ENUNCIADO_LARGO, org="X", fecha="2015-01-01", reserva=True),
        registro(id="B", q=ENUNCIADO_LARGO, org="Y", fecha="2020-01-01", reserva=False),
    ))
    assert "en 2 convocatorias" in "\n".join(stats.recurrencias(c))


def test_el_acierto_se_desglosa_por_regimen_de_penalizacion():
    """Mezclar exámenes que penalizan con los que no daría un número sin sentido."""
    c = Corpus(registros=(
        registro(id="A", resp="A", penalizacion=0.0),
        registro(id="B", resp="B", penalizacion=0.25),
    ))
    salida = "\n".join(stats.acierto_por_descarte(c.verificadas()))
    assert "sin penalización" in salida and "penalización 0.25" in salida


def test_validar_detecta_incoherencias():
    assert any("verificada pero resp" in f
               for f in validar_registro(registro(resp=None)))
    assert any("no verificada pero trae resp" in f
               for f in validar_registro(registro(resp_verificada=False)))
    assert any("'conf' fuera de" in f for f in validar_registro(registro(conf=1.5)))


def test_carga_estricta_rechaza_corpus_incoherente(tmp_path):
    malo = tmp_path / "malo.jsonl"
    malo.write_text(json.dumps(registro(resp=None)) + "\n", encoding="utf-8")
    with pytest.raises(CorpusInvalido):
        Corpus.cargar(malo)


def test_el_corpus_real_carga_y_respeta_la_invariante():
    """Guardarraíl sobre los ficheros de verdad, no solo sobre datos de juguete."""
    from pathlib import Path

    from schema import partes_del_corpus
    rutas = partes_del_corpus(Path(__file__).resolve().parent.parent / "corpus")
    if not rutas:
        pytest.skip("todavía no hay corpus generado")
    c = Corpus.cargar(*rutas)
    verificadas = c.verificadas()
    assert len(verificadas) + len(c.sin_verificar) == len(c)
    assert all(r["resp"] in ("A", "B", "C", "D") for r in verificadas)
    assert all(r["resp"] is None for r in c.sin_verificar)
    # Las baterías PDF de Osakidetza no traen solucionario: ninguna puede figurar
    # como verificada. Sus preguntas del blog sí, porque allí la respuesta viene
    # marcada en el HTML, así que la condición es sobre el origen, no el organismo.
    assert not [r for r in verificadas
                if r["org"] == "Osakidetza" and r["origen"] == "pdf_texto"]
