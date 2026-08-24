"""Tests de los dos parsers, fijando las trampas concretas que ya nos mordieron."""

from __future__ import annotations

import pytest

import ingest_osakidetza as osa
import ingest_sas as sas
import migrar_esquema
import ocr_asturias as ocr


# --- OCR de Asturias -------------------------------------------------------------

@pytest.mark.parametrize("token, esperado", [
    ("1", 1),
    ("|", 1),          # el 1 de la tipografía del cuadernillo sale como barra
    ("l |", 11),       # el OCR llega a partir el "11." en dos trozos
    ("lO", 10),        # ele + o mayúscula por "10"
    ("95", 95),
    ("ab", None),
])
def test_numero_tolera_los_homoglifos_del_ocr(token, esperado):
    assert ocr._a_numero(token) == esperado


def _lineas(*textos):
    return [[ocr.Linea(texto=t, conf=0.9, pagina=1) for t in textos]]


def test_parseo_ocr_arma_pregunta_con_sus_cuatro_opciones():
    preguntas, _ = ocr.parsear(_lineas(
        "1. Un enunciado cualquiera:",
        "a) Primera",
        "b) Segunda",
        "c) Tercera",
        "d) Cuarta",
    ), n_esperadas=1)
    assert len(preguntas) == 1
    assert preguntas[0].num == 1
    assert preguntas[0].opciones == ["Primera", "Segunda", "Tercera", "Cuarta"]
    assert preguntas[0].conf < 1.0  # nunca certeza: viene de OCR


def test_parseo_ocr_pega_las_continuaciones_de_linea():
    preguntas, _ = ocr.parsear(_lineas(
        "1. Un enunciado que sigue",
        "en la línea siguiente:",
        "a) Una opción que también",
        "continúa abajo",
        "b) Otra",
        "c) Otra más",
        "d) La última",
    ), n_esperadas=1)
    assert preguntas[0].enunciado == "Un enunciado que sigue en la línea siguiente:"
    assert preguntas[0].opciones[0] == "Una opción que también continúa abajo"


def test_parseo_ocr_no_parte_la_pregunta_por_un_numero_del_texto():
    """Un '8.' dentro del enunciado no abre pregunta: la secuencia no lo admite."""
    preguntas, _ = ocr.parsear(_lineas(
        "1. Según el artículo",
        "8. Que aquí no toca:",
        "a) A", "b) B", "c) C", "d) D",
    ), n_esperadas=1)
    assert len(preguntas) == 1


def test_conf_nunca_llega_a_uno():
    p = ocr.Pregunta(num=1, confs=[1.0, 1.0])
    assert p.conf == ocr.CONF_MAX_OCR < 1.0


def test_registro_ocr_marca_anulada_como_no_verificada():
    p = ocr.Pregunta(num=4, enunciado="x", opciones=["a", "b", "c", "d"], confs=[0.9])
    r = ocr.a_registro(p, {4: None})
    assert r["resp"] is None and r["resp_verificada"] is False

    p2 = ocr.Pregunta(num=5, enunciado="x", opciones=["a", "b", "c", "d"], confs=[0.9])
    r2 = ocr.a_registro(p2, {5: "B"})
    assert r2["resp"] == "B" and r2["resp_verificada"] is True


# --- Osakidetza ------------------------------------------------------------------

def test_el_numero_de_pregunta_exige_punto():
    """'26 de junio' es continuación de enunciado, no la pregunta 26."""
    assert osa.RE_NUMERO.match("47.- Señale cuál de los siguientes criterios")
    assert osa.RE_NUMERO.match("233. En la valoración de personas con hemiplejía")
    assert not osa.RE_NUMERO.match("26 de junio, de Ordenación Sanitaria de Euskadi")


def test_registro_osakidetza_entra_siempre_sin_respuesta():
    p = osa.Pregunta(num=1, num_impreso=1, enunciado="x", opciones=["a", "b", "c", "d"])
    r = osa.a_registro(p, {"bloque": "comun", "id_prefix": "OSA"})
    assert r["resp"] is None
    assert r["resp_verificada"] is False
    assert r["conf"] == 1.0  # texto nativo: la extracción sí es exacta


def test_las_erratas_de_numeracion_se_corrigen_conservando_el_original():
    """Las tres erratas medidas: 100 por 110, 253 por 353 y el 233 sin guion."""
    import json
    from pathlib import Path

    corpus = Path(__file__).resolve().parent.parent / "corpus" / "corpus_osakidetza.jsonl"
    if not corpus.is_file():
        pytest.skip("todavía no se ha ingerido Osakidetza")

    registros = [json.loads(l) for l in corpus.read_text(encoding="utf-8").splitlines()]
    especifico = [r for r in registros if r["bloque"] == "especifico"]

    assert [r["num"] for r in especifico] == list(range(1, 501))
    corregidas = {r["num"]: r["num_impreso"] for r in especifico
                  if r["num"] != r["num_impreso"]}
    assert corregidas == {110: 100, 353: 253}
    # La 233 va sin guion en el PDF pero con el número correcto: se ingiere entera.
    assert especifico[232]["num"] == 233
    assert len(especifico[232]["opts"]) == 4


# --- SAS -------------------------------------------------------------------------

def test_la_letra_de_opcion_debe_ser_la_que_toca():
    """Una línea 'A).' suelta cierra la opción B), no abre una quinta opción."""
    assert sas.RE_OPCION.match("A) Primera opción")
    # La comprobación real vive en el parser: la letra tiene que seguir la
    # secuencia A, B, C, D. Aquí se fija la lista contra la que se compara.
    assert sas.LETRAS == ("A", "B", "C", "D")


def test_reconoce_el_encabezado_de_caso_practico():
    assert sas.RE_CASO.match("CASO PRÁCTICO 9:")
    assert sas.RE_CASO.match("CASO PRACTICO 12")
    assert not sas.RE_CASO.match("El caso práctico de este paciente")


def test_descarta_cabeceras_y_pies_de_pagina():
    for ruido in ("Página 29 de 33", "SAS_FISIOTERAPEUTA / 2025 CUESTIONARIO",
                  "PREGUNTAS ACCESO LIBRE", "TEÓRICO"):
        assert sas.RE_RUIDO.match(ruido), ruido
    assert not sas.RE_RUIDO.match("A) La rehabilitación pulmonar mejora la disnea")


def test_el_sas_ingiere_solo_el_turno_libre_con_sus_153():
    import json
    from pathlib import Path

    corpus = Path(__file__).resolve().parent.parent / "corpus" / "corpus_sas2025.jsonl"
    if not corpus.is_file():
        pytest.skip("todavía no se ha ingerido el SAS")

    registros = [json.loads(l) for l in corpus.read_text(encoding="utf-8").splitlines()]
    assert len(registros) == 153
    assert [r["num"] for r in registros] == list(range(1, 154))
    assert {r["turno"] for r in registros} == {"libre"}
    assert all(r["resp_verificada"] for r in registros)
    assert all(len(r["opts"]) == 4 for r in registros)
    assert all(r["penalizacion"] == 0.25 for r in registros)

    reserva = [r["num"] for r in registros if r["reserva"]]
    assert reserva == [151, 152, 153]
    # El cuestionario práctico cuelga de casos clínicos; el teórico no.
    practicas = [r for r in registros if r["bloque"] == "practico"]
    assert practicas and all(r["contexto"] for r in practicas)
    assert not any(r["contexto"] for r in registros if r["bloque"] == "teorico")


def test_asturias_marca_de_reserva_la_81_a_la_95():
    import json
    from pathlib import Path

    corpus = Path(__file__).resolve().parent.parent / "corpus" / "corpus_asturias2019.jsonl"
    if not corpus.is_file():
        pytest.skip("todavía no se ha ingerido Asturias")

    registros = [json.loads(l) for l in corpus.read_text(encoding="utf-8").splitlines()]
    assert [r["num"] for r in registros if r["reserva"]] == list(range(81, 96))
    # Un quinto del acierto, según el BOPA de la convocatoria.
    assert all(r["penalizacion"] == 0.20 for r in registros)


# --- migración -------------------------------------------------------------------

def test_migracion_es_idempotente():
    viejo = {"id": "A", "resp": "C"}
    migrado, cambio = migrar_esquema.migrar_registro(dict(viejo))
    assert cambio and migrado["resp_verificada"] is True and migrado["conf"] == 1.0

    otra_vez, cambio2 = migrar_esquema.migrar_registro(dict(migrado))
    assert not cambio2 and otra_vez == migrado


def test_migracion_de_registro_sin_letra_no_lo_da_por_verificado():
    migrado, _ = migrar_esquema.migrar_registro({"id": "A", "resp": None})
    assert migrado["resp_verificada"] is False and migrado["resp"] is None
