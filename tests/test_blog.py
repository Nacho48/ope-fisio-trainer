"""Tests del parser del blog, incluida la regresión contra el corpus parseado a mano."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import parse_blog as blog

# Fragmento literal de una página del blog (el de la especificación).
FRAGMENTO = """
<form name="pregunta01">
   <p>1. Según se desprende del artículo 43.2 de la Constitución Española, la organización
y tutela de la salud pública se realiza a través de...<br />
   </p><blockquote>
   <input name="pregunta01" onclick="respuesta01('Incorrecto')" type="radio" />Medidas preventivas<br />
   <input name="pregunta01" onclick="respuesta01('Incorrecto')" type="radio" />Medidas preventivas y prestaciones<br />
   <input name="pregunta01" onclick="respuesta01('Correcto')" type="radio" />Medidas preventivas, prestaciones y servicios necesarios<br />
   <input name="pregunta01" onclick="respuesta01('Incorrecto')" type="radio" />Medidas preventivas, prestaciones, servicios necesarios y fomento de culturas saludables<br />
   Resultado: <input name="resultado" size="10" type="text" /></blockquote><p></p>
   </form>
"""

CORPUS_REFERENCIA = (
    Path(__file__).resolve().parent.parent / "corpus" / "corpus_sescam2026_p1.jsonl"
)


def test_extrae_la_pregunta_del_fragmento():
    preguntas = blog.extraer_preguntas(FRAGMENTO, "ejemplo.html")
    assert len(preguntas) == 1

    p = preguntas[0]
    assert p.num == 1
    assert p.resp == "C"  # la tercera opción es la marcada 'Correcto'
    assert p.fallos == []
    assert p.enunciado.startswith("Según se desprende del artículo 43.2")
    assert p.enunciado.endswith("a través de...")
    assert "\n" not in p.enunciado  # el salto interno se colapsa
    assert p.opciones == [
        "Medidas preventivas",
        "Medidas preventivas y prestaciones",
        "Medidas preventivas, prestaciones y servicios necesarios",
        "Medidas preventivas, prestaciones, servicios necesarios y fomento de "
        "culturas saludables",
    ]


def test_el_cuadro_resultado_no_se_cuela_como_opcion():
    """El `<input type="text" name="resultado">` no es una opción."""
    p = blog.extraer_preguntas(FRAGMENTO, "ejemplo.html")[0]
    assert len(p.opciones) == 4
    assert not any("Resultado" in o for o in p.opciones)


def test_regresion_contra_el_corpus_parseado_a_mano():
    """El parser debe reproducir exactamente lo que ya había en el corpus."""
    if not CORPUS_REFERENCIA.is_file():
        pytest.skip("no está el corpus de referencia")

    esperado = json.loads(CORPUS_REFERENCIA.read_text(encoding="utf-8").splitlines()[0])
    p = blog.extraer_preguntas(FRAGMENTO, "ejemplo.html")[0]

    assert p.enunciado == esperado["q"]
    assert p.opciones == esperado["opts"]
    assert p.resp == esperado["resp"]
    assert p.num == esperado["num"]


def _form(opciones: str, enunciado: str = "1. Un enunciado de prueba:") -> str:
    return f'<form name="pregunta01"><p>{enunciado}</p>{opciones}</form>'


def test_quita_los_prefijos_de_letra_cuando_los_trae():
    html = _form(
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />a) Primera<br />'
        '<input onclick="respuesta01(\'Correcto\')" type="radio" />b) Segunda<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />c) Tercera<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />d) Cuarta<br />'
    )
    p = blog.extraer_preguntas(html, "x.html")[0]
    assert p.opciones == ["Primera", "Segunda", "Tercera", "Cuarta"]
    assert p.resp == "B"


def test_decodifica_las_entidades_html():
    html = _form(
        '<input onclick="respuesta01(\'Correcto\')" type="radio" />&#191;Cu&aacute;l es&quot;?<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />Dolor &#8211; agudo<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />Tercera<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />Cuarta<br />',
        enunciado="1. &#191;Qu&eacute; ocurre&#160;aqu&iacute;?",
    )
    p = blog.extraer_preguntas(html, "x.html")[0]
    assert p.enunciado == "¿Qué ocurre aquí?"
    assert p.opciones[0] == '¿Cuál es"?'
    assert p.opciones[1] == "Dolor – agudo"


def test_marca_como_fallo_que_no_haya_exactamente_una_correcta():
    ninguna = _form(
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />A<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />B<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />C<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />D<br />'
    )
    p = blog.extraer_preguntas(ninguna, "x.html")[0]
    assert p.resp is None
    assert any("0 opciones marcadas" in f for f in p.fallos)

    dos = ninguna.replace("'Incorrecto'", "'Correcto'", 2)
    q = blog.extraer_preguntas(dos, "x.html")[0]
    assert q.resp is None
    assert any("2 opciones marcadas" in f for f in q.fallos)


def test_una_pregunta_con_fallos_no_puede_entrar_al_corpus_limpio():
    """Los fallos mandan a cuarentena; y sin letra, nunca sale verificada."""
    html = _form(
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />A<br />'
        '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />B<br />'
    )
    p = blog.extraer_preguntas(html, "x.html")[0]
    assert p.fallos
    registro = blog.a_registro(p, {"id_prefix": "T", "parte": "01", "org": "T",
                                   "ccaa": "T", "fecha": None, "turno": None,
                                   "penalizacion": None})
    assert registro["resp"] is None
    assert registro["resp_verificada"] is False


def test_ignora_los_formularios_que_no_son_preguntas():
    """Blogger mete formularios de búsqueda y suscripción alrededor."""
    html = ('<form name="buscar"><input type="text" name="q" /></form>' + FRAGMENTO
            + '<form action="/suscribir"><input type="submit" value="Ir" /></form>')
    assert len(blog.extraer_preguntas(html, "x.html")) == 1


def test_el_numero_sale_del_enunciado_y_avisa_si_discrepa_del_form():
    html = ('<form name="pregunta07"><p>9. Un enunciado cualquiera:</p>'
            '<input onclick="respuesta07(\'Correcto\')" type="radio" />Primera<br />'
            '<input onclick="respuesta07(\'Incorrecto\')" type="radio" />Segunda<br />'
            '<input onclick="respuesta07(\'Incorrecto\')" type="radio" />Tercera<br />'
            '<input onclick="respuesta07(\'Incorrecto\')" type="radio" />Cuarta<br /></form>')
    p = blog.extraer_preguntas(html, "x.html")[0]
    assert p.num == 9
    # Es un aviso, no un defecto: el form numera dentro de la página y el
    # enunciado conserva la numeración del examen. Mandarlo a cuarentena dejaba
    # fuera 1.567 preguntas correctas.
    assert any("el enunciado dice 9 y el form 7" in a for a in p.avisos)
    assert p.fallos == []


def test_soporta_inputs_sin_barra_de_cierre():
    """Regresión: `<input type="radio">` sin `/` hace que html.parser anide.

    Con la anidación, mirar los hermanos del input devuelve vacío y las opciones
    se pierden sin ruido. El parser recorre el documento en orden justo por esto.
    """
    html = ('<form name="pregunta01"><p>1. Un enunciado de prueba:</p><blockquote>'
            '<input name="pregunta01" onclick="respuesta01(\'Incorrecto\')" type="radio">Primera<br>'
            '<input name="pregunta01" onclick="respuesta01(\'Correcto\')" type="radio">Segunda<br>'
            '<input name="pregunta01" onclick="respuesta01(\'Incorrecto\')" type="radio">Tercera<br>'
            '<input name="pregunta01" onclick="respuesta01(\'Incorrecto\')" type="radio">Cuarta<br>'
            'Resultado: <input name="resultado" type="text"></blockquote></form>')
    p = blog.extraer_preguntas(html, "x.html")[0]
    assert p.opciones == ["Primera", "Segunda", "Tercera", "Cuarta"]
    assert p.resp == "B"
    assert p.fallos == []


def test_recoge_el_texto_aunque_venga_dentro_de_etiquetas():
    html = ('<form name="pregunta01"><p>1. Un enunciado de prueba:</p>'
            '<input onclick="respuesta01(\'Correcto\')" type="radio" /><b>En</b> <i>negrita</i><br />'
            '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />Normal<br />'
            '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />Otra<br />'
            '<input onclick="respuesta01(\'Incorrecto\')" type="radio" />Última<br /></form>')
    p = blog.extraer_preguntas(html, "x.html")[0]
    assert p.opciones[0] == "En negrita"


def test_el_organismo_no_se_parte_por_el_primer_espacio():
    """'Red Sanitaria Militar' daría ccaa='Sanitaria Militar' partiendo por espacio."""
    assert blog.ORGANISMOS["SESCAM CLM"] == ("SESCAM", "Castilla-La Mancha")
    assert blog.ORGANISMOS["Red Sanitaria Militar"][1] == "Estatal"
    assert blog.ORGANISMOS["Osakidetza"][1] == "País Vasco"
    # SCS son dos comunidades distintas: la sigla sola no basta.
    assert blog.ORGANISMOS["SCS Cantabria"][1] != blog.ORGANISMOS["SCS Canarias"][1]


def test_deduce_el_turno_del_titulo():
    titulo = ("<html><head><title>Test de FISIOTERAPEUTAS - OPEs 2023/24 SESCAM - "
              "Turno Libre, Promoción Interna y Discapacidad - 15-03-2026 - Parte 1"
              "</title></head><body></body></html>")
    assert blog.turno_del_titulo(titulo) == "libre+PI+discap"
    assert blog.turno_del_titulo("<html><head><title>Sin turnos</title></head></html>") is None


def test_casado_de_fichero_con_el_indice():
    indice = [{"ccaa_org": "SESCAM CLM", "ano_examen": "2026-03-15",
               "descripcion": "OPE 2023/24 Parte 1 [VOLCADO]",
               "slug_blog": "p/test-de-fisioterapeutas-opes-202324.html"}]
    fila = blog.casar_metadatos(Path("test-de-fisioterapeutas-opes-202324.html"), indice)
    assert fila is not None and fila["ccaa_org"] == "SESCAM CLM"
    assert blog.casar_metadatos(Path("otra-cosa-distinta.html"), indice) is None


def test_los_registros_del_blog_salen_autoverificados():
    p = blog.extraer_preguntas(FRAGMENTO, "x.html")[0]
    registro = blog.a_registro(p, {"id_prefix": "SESCAM2026", "parte": "01",
                                   "org": "SESCAM", "ccaa": "Castilla-La Mancha",
                                   "fecha": "2026-03-15", "turno": "libre",
                                   "penalizacion": 0.0})
    # El id lleva la parte: organismo y año no identifican una página, y sin ese
    # discriminante dos partes del mismo examen generan los mismos ids.
    assert registro["id"] == "SESCAM2026-01-001"
    assert registro["resp_verificada"] is True
    assert registro["conf"] == 1.0
    assert registro["origen"] == "html"


def _pagina_sescam_parte1() -> Path | None:
    directorio = Path(__file__).resolve().parent.parent / "fuentes" / "blog"
    if not directorio.is_dir():
        return None
    for candidato in sorted(directorio.glob("*opes-202324*")):
        if "0964609991" not in candidato.name:  # esa es la parte 2
            return candidato
    return None


def _solapamiento(a: str, b: str) -> float:
    """Fracción de palabras del texto más corto que aparecen en el más largo."""
    pa = set(blog.normalizar_hash(a).split())
    pb = set(blog.normalizar_hash(b).split())
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / min(len(pa), len(pb))


def test_regresion_estructural_contra_el_corpus_de_referencia():
    """Contrasta el parseo del HTML real con el corpus que se hizo a mano.

    No se exige texto idéntico y no es un descuido: comprobado sobre la página
    real, el corpus de referencia está **parafraseado** ("Castilla-La Mancha" ->
    "CLM", "La historia clínica es el conjunto de documentos…" -> "Es el conjunto
    de documentos…"), mientras que el parser copia lo que dice el HTML. Exigir
    igualdad literal obligaría a degradar el parser para reproducir un resumen.

    Lo que sí tiene que cuadrar clavado es la parte que no admite interpretación:
    cuántas preguntas hay, su número, y qué letra es la correcta. Un fallo del
    mapeo posición -> letra saldría aquí inmediatamente.
    """
    pagina = _pagina_sescam_parte1()
    if pagina is None or not CORPUS_REFERENCIA.is_file():
        pytest.skip("falta la página HTML del SESCAM parte 1 en fuentes/blog/")

    esperados = [json.loads(l) for l in
                 CORPUS_REFERENCIA.read_text(encoding="utf-8").splitlines() if l.strip()]
    obtenidas = blog.extraer_preguntas(blog.leer(pagina), pagina.name)

    assert len(obtenidas) == len(esperados)
    for p, esperado in zip(obtenidas, esperados):
        assert p.num == esperado["num"]
        assert p.resp == esperado["resp"], f"respuesta distinta en {esperado['id']}"
        assert len(p.opciones) == len(esperado["opts"]), f"nº opciones en {esperado['id']}"
        assert not p.fallos, f"{esperado['id']}: {p.fallos}"
        # Deben seguir siendo la misma pregunta, aunque esté redactada más corta:
        # un solapamiento bajo delataría que las listas se han desalineado.
        assert _solapamiento(p.enunciado, esperado["q"]) >= 0.6, (
            f"{esperado['id']}: el enunciado no se parece al de referencia")


def test_el_texto_del_html_es_mas_completo_que_el_del_corpus_manual():
    """Fija el hallazgo: el corpus de referencia resume, el HTML no.

    Importa para las recurrencias: si esas 50 preguntas se quedaran con el texto
    parafraseado, sus hashes no casarían con los de las otras páginas y los
    enunciados repetidos —la señal que se busca— no aparecerían.
    """
    pagina = _pagina_sescam_parte1()
    if pagina is None or not CORPUS_REFERENCIA.is_file():
        pytest.skip("falta la página HTML del SESCAM parte 1 en fuentes/blog/")

    esperados = [json.loads(l) for l in
                 CORPUS_REFERENCIA.read_text(encoding="utf-8").splitlines() if l.strip()]
    obtenidas = blog.extraer_preguntas(blog.leer(pagina), pagina.name)

    del_html = sum(len(p.enunciado) for p in obtenidas)
    del_manual = sum(len(e["q"]) for e in esperados)
    assert del_html > del_manual
