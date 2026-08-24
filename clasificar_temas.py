"""Clasifica las preguntas del corpus contra los 44 temas del BOPA 2025.

Estrategia: reglas de desempate primero, léxico después. Las reglas son las que
fijó el usuario revisando a mano 150 preguntas, y ganan siempre sobre el léxico
porque codifican el criterio del tribunal, que es rígido en el encaje temático
(una pregunta que no cuadra con el temario es impugnable).

Orden de las reglas, de más específica a más general — el orden importa: "escala
de dolor" tiene que resolverse como T26 antes de que la regla genérica de
instrumentos la mande a T19.

Ante la duda, `tema_primario` queda a None: el usuario prefiere un 25 % sin
clasificar a una clasificación equivocada, porque un error silencioso contamina
todo el análisis posterior.

    python clasificar_temas.py --evaluar          # solo mide contra las 150
    python clasificar_temas.py --out corpus/clasificacion.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def norm(texto: str) -> str:
    """Minúsculas sin tildes, para que los patrones no dependan de la acentuación."""
    s = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# --- Reglas de desempate ---------------------------------------------------------
# (nombre, patrón, tema). Se evalúan en orden y la primera que dispara decide.

REGLAS: list[tuple[str, str, int]] = [
    # 1. Normas con nombre y número: es el encaje más determinista que existe.
    ("ley 55/2003 estatuto marco", r"\b55/2003\b|estatuto marco", 5),
    ("ley 44/2003 profesiones", r"\b44/2003\b|ordenacion de las profesiones sanitarias", 3),
    ("ley 16/2003 cohesion", r"\b16/2003\b|cohesion y calidad", 3),
    ("ley 41/2002 autonomia paciente", r"\b41/2002\b|autonomia del paciente", 2),
    ("ley 14/1986 general sanidad", r"\b14/1986\b|ley general de sanidad", 2),
    ("decreto 51/2019 historia clinica", r"\b51/2019\b", 2),
    ("constitucion", r"constitucion espanola|\b1978\b", 1),
    ("estatuto autonomia", r"estatuto de autonomia", 1),
    ("ebep", r"\b5/2015\b|estatuto basico del empleado publico|ebep", 4),
    ("prevencion riesgos", r"\b31/1995\b|prevencion de riesgos laborales|riesgo biologico", 6),
    ("proteccion datos", r"\b3/2018\b|proteccion de datos", 7),
    ("igualdad", r"\b2/2011\b|igualdad efectiva|violencia de genero", 8),
    ("ley 7/2019 salud asturias", r"\b7/2019\b", 9),
    ("decreto 189/2023", r"\b189/2023\b", 10),
    ("decreto 7/2013 jornada", r"\b7/2013\b", 5),

    # Normativa asturiana. Va aquí porque son las preguntas que solo aparecen en
    # exámenes del SESPA y ninguna otra comunidad cubre; sin estos patrones se
    # quedaban sin clasificar y se perdía justo lo que se venía a buscar.
    ("estructura organica del sespa", r"estructura organica|direccion gerencia"
                                      r"|organos de direccion y gestion", 10),
    ("ley de salud del principado", r"ley de salud del principado"
                                    r"|consejo de salud del principado"
                                    r"|area(s)? sanitaria(s)? del principado"
                                    r"|sistema de salud del principado"
                                    r"|sistema sanitario publico del principado", 9),
    ("junta general del principado", r"junta general del principado"
                                     r"|consejo de gobierno del principado", 1),
    ("mapa sanitario asturiano", r"mapa sanitario|areas? sanitarias? de asturias"
                                 r"|zona basica de salud", 11),

    # 2. Escalas: el sistema al que miden manda sobre la regla de instrumentos.
    ("escala de dolor", r"(escala|cuestionario|indice)[^.]{0,40}(dolor|eva|analogica|mcgill|lattinen)"
                        r"|escala visual analogica", 26),
    ("escala de AVD", r"(escala|indice|cuestionario)[^.]{0,40}"
                      r"(actividades de la vida diaria|avd|abvd|barthel|katz|lawton|tinetti)"
                      r"|independencia de las personas mayores", 33),

    # 3. Encajes fijos del temario.
    ("paralisis cerebral", r"paralisis cerebral|paralitico cerebral|\bpc\b|educacion conductiva", 32),
    ("protesis", r"protesi|protetiza|\bptr\b|\bptc\b|encaje|amputa", 30),
    ("marcha", r"\bmarcha\b|deambulacion", 19),
    ("respiratoria en nino o anciano", r"(respiratori|pulmonar|bronqui|ventilacion)[^.]{0,60}"
                                       r"(nino|infantil|pediatr|anciano|geriatr)"
                                       r"|(nino|pediatr|anciano|geriatr)[^.]{0,60}(respiratori|pulmonar)", 21),

    # 4. Aparatos: el BOPA los reparte literalmente entre T36 y T37.
    ("suspension y poleas", r"suspension|poleo|polea|peso-polea", 37),
    ("aparatos de mecanoterapia", r"traccion (vertebral|cervical|lumbar)|bicicleta|espaldera"
                                  r"|escalera de dedos|mesa de mano|rampa|mecanoterapia", 36),

    # 5. Instrumento nombrado, ya sin las excepciones anteriores.
    ("instrumento nombrado", r"\b(test|prueba|maniobra|signo de|escala|indice|cuestionario|goniometr"
                             r"|balance (articular|muscular)|medicion|valoracion funcional)\b", 19),
]

REGLAS_COMPILADAS = [(n, re.compile(p), t) for n, p, t in REGLAS]


# --- Léxico por tema -------------------------------------------------------------
# Términos que aparecen en el enunciado y delatan el tema. Peso 2 = muy específico.

LEXICO: dict[int, list[tuple[str, int]]] = {
    11: [("demografia", 2), ("mapa sanitario", 2), ("indicadores de salud", 2),
         ("gestion por procesos", 2), ("seguridad del paciente", 2), ("calidad", 1)],
    12: [("bioetica", 2), ("secreto profesional", 2), ("consentimiento informado", 2),
         ("deontolog", 2), ("etic", 1), ("eutanasia", 2), ("responsabilidad profesional", 2)],
    13: [("evidencia", 2), ("guia de practica clinica", 2), ("revision bibliografica", 2),
         ("educacion para la salud", 2), ("docencia", 2), ("adherencia al tratamiento", 2),
         ("nivel de evidencia", 2), ("grado de recomendacion", 2)],
    14: [("investigacion", 2), ("epidemiolog", 2), ("estudio", 1), ("muestra", 1),
         ("variable", 1), ("cualitativ", 2), ("cuantitativ", 2), ("declaracion obligatoria", 2),
         ("incidencia", 1), ("prevalencia", 2), ("cohorte", 2), ("casos y controles", 2)],
    15: [("salud publica", 2), ("morbilidad", 2), ("mortalidad", 2), ("letalidad", 2),
         ("esperanza de vida", 2), ("priorizacion", 2), ("plan integral", 2),
         ("problemas de salud", 1)],
    16: [("calidad", 2), ("auditoria", 2), ("evaluacion de la calidad", 2),
         ("programas de calidad", 2), ("acreditacion", 2)],
    17: [("higiene hospitalaria", 2), ("antiseptic", 2), ("desinfectante", 2),
         ("infeccion", 2), ("aislamiento", 2), ("prevencion primaria", 2),
         ("ulcera por presion", 2), ("lavado de manos", 2), ("jabon", 2), ("esteriliza", 2)],
    18: [("atencion primaria", 2), ("fisioterapia en atencion primaria", 2),
         ("wcpt", 2), ("confederacion mundial", 2), ("historia de la fisioterapia", 2),
         ("funciones del fisioterapeuta", 2), ("atencion especializada", 2),
         ("criterio de exclusion", 1), ("definicion de fisioterapia", 2)],
    19: [("valoracion funcional", 2), ("capacidad funcional", 2), ("exploracion fisica", 1),
         ("entrevista clinica", 1), ("coeficiente funcional", 2), ("amplitud articular", 2)],
    20: [("plan de actuacion", 2), ("objetivos de fisioterapia", 1), ("planificacion", 1),
         ("metodologia de intervencion", 2)],
    21: [("respiratori", 2), ("bronqui", 2), ("espirometr", 2), ("disnea", 2), ("tos", 2),
         ("oxigenoterapia", 2), ("ventilacion mecanica", 2), ("aerosol", 2), ("epoc", 2),
         ("drenaje postural", 2), ("eltgol", 2), ("peep", 2), ("pep", 2), ("asma", 2),
         ("pulmonar", 1), ("torac", 1), ("fibrosis quistica", 2), ("atelectasia", 2),
         ("capacidad pulmonar", 2), ("volumen", 1), ("secrecion", 1), ("peet", 2)],
    22: [("cardiac", 2), ("cardiovascular", 2), ("linfedema", 2), ("drenaje linfatico", 1),
         ("venos", 2), ("arterial", 2), ("isquemi", 2), ("infarto", 2), ("uci", 2),
         ("paciente critico", 2), ("quemadura", 2), ("flebitis", 2), ("trombosis", 2),
         ("circulatori", 2), ("mastectomia", 2), ("linfadenectomia", 2), ("rehabilitacion cardiaca", 2)],
    23: [("fractura", 2), ("traumatolog", 2), ("traumatismo", 2), ("luxacion", 2),
         ("esguince", 2), ("epifisiolisis", 2), ("rigidez articular", 2), ("callo oseo", 2),
         ("inmovilizacion", 1), ("rotura de fibras", 2), ("fisura", 2), ("osteosintesis", 2)],
    24: [("escoliosis", 2), ("cifosis", 2), ("lordosis", 2), ("columna vertebral", 2),
         ("espondilolistesis", 2), ("deformidad de la columna", 2), ("cobb", 2)],
    25: [("artrosis", 2), ("osteoarticular", 2), ("articulacion", 1), ("hombro doloroso", 2),
         ("atm", 2), ("capsulitis", 2), ("menisco", 2), ("condromalacia", 2)],
    26: [("dolor", 2), ("algia", 2), ("fibromialgia", 2), ("lumbalgia", 2), ("cervicalgia", 2),
         ("miofascial", 2), ("punto gatillo", 2), ("puncion seca", 2), ("dolor cronico", 2)],
    27: [("reumatolog", 2), ("artritis reumatoide", 2), ("espondilitis", 2), ("lupus", 2),
         ("esclerodermia", 2), ("polimiositis", 2), ("dermatomiositis", 2), ("osteoporosis", 2),
         ("paget", 2), ("osteomalacia", 2), ("condrocalcinosis", 2), ("ledderhose", 2),
         ("dupuytren", 2), ("bambu", 2), ("gota", 2)],
    28: [("neurolog", 2), ("hemiplej", 2), ("ictus", 2), ("bobath", 2), ("esclerosis multiple", 2),
         ("parkinson", 2), ("medular", 2), ("nervio", 2), ("plexo", 2), ("guillain", 2),
         ("polineuropatia", 2), ("espasticidad", 2), ("par craneal", 2), ("reflejo", 2),
         ("esclerosis lateral", 2), ("perfetti", 2), ("kabat", 2), ("vojta", 2),
         ("sistema nervioso", 2), ("neurona", 2), ("miastenia", 2)],
    29: [("malformacion congenita", 2), ("congenit", 2), ("marfan", 2), ("pie equino varo", 2),
         ("displasia", 2), ("torticolis congenita", 2), ("artrogriposis", 2)],
    30: [("ortesis", 2), ("ayudas tecnicas", 1), ("muñon", 2), ("pirogoff", 2), ("syme", 2)],
    31: [("suelo pelvico", 2), ("incontinencia", 2), ("urolog", 2), ("ginecolog", 2),
         ("obstetric", 2), ("parto", 2), ("embarazo", 2), ("prolapso", 2), ("enuresis", 2),
         ("perine", 2), ("postnatal", 2), ("miccion", 2), ("vejiga", 2)],
    32: [("desarrollo psicomotor", 2), ("espina bifida", 2), ("nino", 1), ("pediatr", 1),
         ("lactante", 2), ("prematur", 2), ("deficiencia mental", 2), ("signo de alerta", 2),
         ("neonat", 2), ("sedestacion", 1)],
    33: [("anciano", 2), ("geriatr", 2), ("envejecimiento", 2), ("fragilidad", 2),
         ("caidas", 2), ("discapacidad", 1), ("dependencia", 1), ("vida diaria", 1)],
    34: [("cinesiterapia", 2), ("movilizacion", 2), ("fortalecimiento muscular", 2),
         ("contraccion", 2), ("isometric", 2), ("isotonic", 2), ("musculo", 1),
         ("ejercicio activo", 2), ("ejercicio pasivo", 2), ("resistencia manual", 2),
         ("escapula alada", 2), ("flexion del tronco", 2), ("potenciar", 1)],
    35: [("masaje", 2), ("masoterapia", 2), ("cyriax", 2), ("friccion transversa", 2),
         ("drenaje linfatico manual", 2), ("amasamiento", 2), ("percusion", 1),
         ("tejido conjuntivo", 2), ("fascia", 2), ("periostio", 2)],
    36: [("mecanoterapia", 2), ("palanca", 2), ("poleoterapia", 1)],
    37: [("suspensioterapia", 2)],
    38: [("termoterapia", 2), ("crioterapia", 2), ("hidroterapia", 2), ("calor", 2),
         ("frio", 2), ("parafina", 2), ("infrarrojo", 2), ("bano", 2), ("compresa", 2),
         ("hidrocinesiterapia", 2), ("piscina", 2), ("agua", 1), ("hielo", 2),
         ("contraste", 1), ("afusion", 2), ("envoltura", 2)],
    39: [("electroterapia", 2), ("corriente", 2), ("ultrasonido", 2), ("laser", 2),
         ("magnetoterapia", 2), ("iontoforesis", 2), ("galvanic", 2), ("tens", 2),
         ("onda corta", 2), ("microonda", 2), ("electrodo", 2), ("fototerapia", 2),
         ("electroestimulacion", 2), ("nmes", 2), ("frecuencia", 1), ("era", 1),
         ("electroanalgesia", 2), ("diadinamic", 2), ("interferencial", 2), ("farádic", 2)],
    40: [("ergonom", 2), ("higiene postural", 2), ("puesto de trabajo", 2),
         ("escuela de espalda", 2), ("levantar pesos", 2), ("postura viciosa", 2),
         ("movilizacion de pacientes", 2), ("wisner", 2), ("carga", 1)],
    41: [("deporte", 2), ("deportiv", 2), ("lesion deportiva", 2), ("ligamento cruzado", 2),
         ("readaptacion", 2), ("ejercicio fisico adaptado", 2), ("calentamiento", 2)],
    42: [("estiramiento", 2), ("elongacion", 2), ("facilitacion neuromuscular", 2),
         ("propioceptiva", 2), ("tejido muscular", 2), ("flexibilidad", 2), ("tension", 1)],
    43: [("relajacion", 2), ("jacobson", 2), ("schultz", 2), ("autogeno", 2)],
    44: [("vendaje", 2), ("tape", 2), ("kinesiotape", 2), ("neuromuscular", 1),
         ("strapping", 2)],
}

# `` delante de cada término: sin él "tos" casa dentro de "objetivos", "era"
# dentro de "manera" y "tens" dentro de "extensión". No se pone al final para que
# los prefijos sigan cubriendo el género y el número ("respiratori" -> "respiratoria").
LEXICO_COMPILADO = {t: [(re.compile(r"\b" + re.escape(p)), w) for p, w in ps]
                    for t, ps in LEXICO.items()}

# Por debajo de esta puntuación no hay evidencia suficiente y se deja sin clasificar.
UMBRAL_MINIMO = 2
# Si el segundo tema queda pegado al primero, tampoco hay decisión clara.
MARGEN_MINIMO = 1


def clasificar(enunciado: str, opciones: list[str] | None = None
               ) -> tuple[int | None, int | None, str]:
    """Devuelve (tema_primario, tema_secundario, evidencia).

    Las reglas miran SOLO el enunciado. Es deliberado: una pregunta de fisioterapia
    cardiovascular puede listar escalas en sus opciones, y si la regla de
    instrumentos leyera ahí, se la llevaría a T19 por una palabra que ni siquiera
    es lo que se pregunta. El léxico sí mira las opciones, con la mitad de peso,
    porque ahí el vocabulario ayuda a desambiguar sin decidir por sí solo.
    """
    t = norm(enunciado)
    t_opts = norm(" ".join(opciones or []))

    for nombre, patron, tema in REGLAS_COMPILADAS:
        m = patron.search(t)
        if m:
            ini = max(0, m.start() - 25)
            fragmento = enunciado[ini:m.end() + 45].strip()
            return tema, None, f"regla «{nombre}»: …{fragmento}…"

    puntos: Counter = Counter()
    aciertos: dict[int, list[str]] = {}
    for tema, patrones in LEXICO_COMPILADO.items():
        for patron, peso in patrones:
            if patron.search(t):
                puntos[tema] += peso
                aciertos.setdefault(tema, []).append(patron.pattern.replace("\\", ""))
            elif peso >= 2 and patron.search(t_opts):
                # En las opciones el término orienta, pero no decide por sí solo.
                puntos[tema] += 1
                aciertos.setdefault(tema, []).append(
                    patron.pattern.replace("\\", "") + " (en opciones)")

    if not puntos:
        return None, None, "sin coincidencias"

    orden = puntos.most_common()
    mejor, punt = orden[0]
    segundo, punt2 = orden[1] if len(orden) > 1 else (None, 0)

    if punt < UMBRAL_MINIMO:
        return None, None, f"evidencia débil ({punt} pts en T{mejor})"
    if punt - punt2 < MARGEN_MINIMO:
        return None, segundo, f"empate T{mejor}={punt} / T{segundo}={punt2}"

    return mejor, segundo, "léxico: " + ", ".join(aciertos[mejor][:4])


def cargar_corpus(ruta: Path) -> list[dict]:
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def texto_de(r: dict) -> tuple[str, list[str]]:
    """El enunciado manda; las opciones ayudan cuando el enunciado es genérico."""
    return r["q"], (r.get("opts") or [])


def evaluar(corpus: list[dict], referencia: list[dict]) -> dict:
    por_id = {r["id"]: r for r in corpus}
    aciertos = fallos = sin_clasificar = 0
    aciertos_con_t2 = 0
    detalle_fallos: list[tuple] = []

    for ref in referencia:
        r = por_id.get(ref["id"])
        if r is None:
            continue
        primario, secundario, evidencia = clasificar(*texto_de(r))
        esperado, esperado2 = ref.get("tema"), ref.get("tema2")

        if primario is None:
            sin_clasificar += 1
            continue
        if primario == esperado:
            aciertos += 1
            aciertos_con_t2 += 1
        elif esperado2 and primario == esperado2:
            aciertos_con_t2 += 1
            detalle_fallos.append((ref["id"], esperado, primario, "coincide con tema2",
                                   ref["q"][:60], evidencia))
        else:
            fallos += 1
            detalle_fallos.append((ref["id"], esperado, primario, "", ref["q"][:60], evidencia))

    clasificadas = aciertos + fallos + (aciertos_con_t2 - aciertos)
    return {
        "total": len(referencia),
        "clasificadas": clasificadas,
        "sin_clasificar": sin_clasificar,
        "aciertos": aciertos,
        "aciertos_con_t2": aciertos_con_t2,
        "acuerdo": aciertos / clasificadas if clasificadas else 0.0,
        "acuerdo_con_t2": aciertos_con_t2 / clasificadas if clasificadas else 0.0,
        "fallos": detalle_fallos,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=RAIZ / "corpus" / "corpus.jsonl")
    ap.add_argument("--referencia", type=Path,
                    default=RAIZ / "docs" / "clasificacion_150_v2.json")
    ap.add_argument("--out", type=Path, default=RAIZ / "corpus" / "clasificacion.jsonl")
    ap.add_argument("--evaluar", action="store_true", help="solo mide contra la referencia")
    ap.add_argument("--ver-fallos", type=int, default=0, help="muestra N fallos")
    args = ap.parse_args()

    corpus = cargar_corpus(args.corpus)
    referencia = json.loads(args.referencia.read_text(encoding="utf-8"))

    res = evaluar(corpus, referencia)
    print(f"REFERENCIA: {res['total']} preguntas revisadas a mano")
    print(f"  clasificadas   : {res['clasificadas']}")
    print(f"  sin clasificar : {res['sin_clasificar']} "
          f"({100*res['sin_clasificar']/res['total']:.0f} %)")
    print(f"  ACUERDO exacto : {100*res['acuerdo']:.1f} %  ({res['aciertos']}/{res['clasificadas']})")
    print(f"  aceptando tema2: {100*res['acuerdo_con_t2']:.1f} %")

    if args.ver_fallos:
        print("\n--- fallos ---")
        for id_, esp, obt, nota, q, ev in res["fallos"][:args.ver_fallos]:
            print(f"  {id_}: esperaba T{esp}, dice T{obt} {nota}")
            print(f"      q: {q}")
            print(f"      {ev[:110]}")

    peores = Counter(f"T{esp}->T{obt}" for _, esp, obt, nota, _, _ in res["fallos"] if not nota)
    if peores:
        print("\nconfusiones más frecuentes: " +
              ", ".join(f"{k}({v})" for k, v in peores.most_common(8)))

    if args.evaluar:
        return 0

    verificadas = [r for r in corpus if r.get("resp_verificada")]
    salida = []
    for r in verificadas:
        primario, secundario, evidencia = clasificar(*texto_de(r))
        salida.append({**r, "tema_primario": primario,
                       "tema_secundario": secundario, "tema_evidencia": evidencia})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in salida:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    con_tema = sum(1 for r in salida if r["tema_primario"])
    print(f"\nclasificadas {con_tema}/{len(salida)} verificadas "
          f"({100*con_tema/len(salida):.0f} %) -> {args.out}")
    reparto = Counter(r["tema_primario"] for r in salida if r["tema_primario"])
    print("temas más frecuentes: " +
          ", ".join(f"T{k}={v}" for k, v in reparto.most_common(10)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
