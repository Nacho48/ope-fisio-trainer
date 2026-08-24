#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clasificador por temas (44) del corpus OPE Fisioterapia.

Reglas-primero (deterministas, con evidencia), null si no hay señal fiable.
Matching con LÍMITES DE PALABRA (\\b). Sufijo '~' = prefijo (respiratori~ -> respiratoria/o/as).
PRIORIDAD AL ENUNCIADO: se clasifica sobre el enunciado; solo si el enunciado no da señal,
se mira enunciado+opciones (evita que una opción de una lista de técnicas robe el tema).

Orden de reglas (primera que dispara gana): norma -> tie-breaks -> instrumento -> keywords -> null.
"""
import json, re, unicodedata, os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REF_PATH = r'C:/Users/User/.claude/uploads/2ae26e2f-2d47-4420-ad17-3b3c5f461d87/3a6a82bf-clasificacion_150_v2.json'


def norm(s):
    s = s or ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def load_corpus():
    rows = [json.loads(l) for l in open(os.path.join(HERE, 'corpus', 'corpus.jsonl'), encoding='utf-8') if l.strip()]
    return [r for r in rows if r.get('resp_verificada')]


def stem_of(r):
    return norm(r.get('q') or '')


def full_of(r):
    return norm((r.get('q') or '') + ' || ' + ' | '.join(r.get('opts') or []))


_cache = {}
def _pat(kw):
    p = _cache.get(kw)
    if p is None:
        if kw.endswith('~'):
            p = re.compile(r'\b' + re.escape(kw[:-1]))          # prefijo
        else:
            p = re.compile(r'\b' + re.escape(kw) + r'\b')       # palabra completa
        _cache[kw] = p
    return p


def anyof(t, *kws):
    for k in kws:
        if _pat(k).search(t):
            return k
    return None


# ── 1. NORMAS (por materia, no por CCAA) ──────────────────────────────────────
NORMAS = [
    (1, ['constitucion espanola', 'constitucion de 1978', 'de la constitucion', 'constitucion', 'estatuto de autonomia']),
    (2, ['ley 14/1986', 'ley general de sanidad', 'general de sanidad', 'ley 41/2002', 'autonomia del paciente', 'decreto 51/2019', 'historia clinica']),
    (3, ['ley 16/2003', 'cohesion y calidad', 'ley 44/2003', 'ordenacion de las profesiones', 'profesiones sanitarias', 'competencias generales de los profesionales']),
    (4, ['5/2015', 'estatuto basico del empleado publico', 'ebep', 'empleado publico', '1/1995', 'estatuto de los trabajadores']),
    (5, ['ley 55/2003', 'estatuto marco', 'personal estatutario', '2/2011', 'seleccion de personal estatutario', 'trienios', '400/38239']),
    (6, ['ley 31/1995', 'prevencion de riesgos laborales', 'riesgos laborales', 'enfermedades profesionales', 'riesgo biologico']),
    (7, ['3/2018', 'proteccion de datos', 'derechos digitales', 'lopd']),
    (8, ['igualdad efectiva de mujeres', 'violencia de genero']),
    (9, ['ley 7/2019', 'sistema de salud del principado']),
    (10, ['decreto 189/2023']),
]


def rule_norma(t):
    for tema, kws in NORMAS:
        k = anyof(t, *kws)
        if k:
            return tema, f'norma/materia "{k}"'
    return None


# ── 2. TIE-BREAKS clínicos (orden importa) ────────────────────────────────────
def rule_tiebreaks(t):
    if anyof(t, 'paralisis cerebral', 'educacion conductiva', 'espina bifida', 'desarrollo psicomotor',
             'signo de alerta', 'deficiencia mental', 'prematur~', 'semanas de gestacion'):
        return 32, 'tie-break PC/desarrollo psicomotor -> 32'
    if anyof(t, 'protesis', 'ptr', 'ptc', 'protetizacion', 'encaje', 'amputa~', 'muñon', 'munon',
             'protesic~', 'pirogoff', 'mediotarsiana'):
        return 30, 'tie-break prótesis/amputación -> 30'
    if anyof(t, 'dolor', 'analgesi~') and anyof(t, 'escala', 'medicion', 'valoracion', 'cuestionario', 'eva'):
        return 26, 'tie-break escala de dolor -> 26'
    if anyof(t, 'actividades de la vida diaria', 'avd', 'abvd', 'barthel') and anyof(t, 'escala', 'indice', 'valoracion'):
        return 33, 'tie-break escala AVD -> 33'
    if anyof(t, 'traccion vertebral', 'traccion cervical', 'mesa de traccion'):
        return 36, 'tie-break tracción (aparato) -> 36'
    if anyof(t, 'respiratori~', 'ventilaci~', 'espiraci~', 'bronquial', 'pulmonar', 'espirometr~') and anyof(t, 'anciano', 'geriatr~', 'nino', 'ninos', 'pediatr~', 'lactante'):
        return 21, 'tie-break respiratoria peds/geri -> 21'
    if anyof(t, 'marcha'):
        return 19, 'tie-break marcha -> 19'
    if anyof(t, 'suspensioterapia', 'poleoterapia', 'peso-polea', 'peso polea', 'suspension', 'poleas'):
        return 37, 'tie-break suspensión/poleas -> 37'
    if anyof(t, 'espaldera~', 'escalera de dedos', 'bicicleta cinetica', 'mecanoterapia', 'mesa de mano', 'rampa~'):
        return 36, 'tie-break aparato mecanoterapia -> 36'
    return None


# ── 3. INSTRUMENTO nombrado -> 19 ─────────────────────────────────────────────
def rule_instrumento(t):
    k = anyof(t, 'par-q', 'goniometr~', 'balance muscular', 'balance articular',
              'coeficiente funcional de movilidad', 'escala de constant', 'test de constant',
              'constant-murley')
    if k:
        return 19, f'instrumento nombrado -> 19 "{k}"'
    k = anyof(t, 'escala', 'indice', 'cuestionario', 'goniometria', 'coeficiente funcional')
    if k:
        return 19, f'instrumento (escala/índice/cuestionario) -> 19 "{k}"'
    return None


# ── 4. KEYWORDS por tema (distintivas primero) ────────────────────────────────
KW = [
    # modalidades / técnicas (muy distintivas)
    (44, ['vendaje neuromuscular', 'vendaje funcional', 'kinesiotap~', 'tape', 'esparadrapo', 'vendaje mediante tape']),
    (43, ['jacobson', 'schultz', 'relajacion', 'entrenamiento autogeno']),
    (42, ['estiramiento~', 'facilitacion neuromuscular propioceptiva', 'fnp', 'miotendinos~', 'carga tensil', 'propiedad especifica del tejido muscular', 'propiedades del tejido muscular']),
    (39, ['electroterapia', 'iontoforesis', 'galvanic~', 'galvanica', 'onda corta', 'ultrasonid~', 'ultrasonoterapia', 'laser', 'magnetoterapia', 'tens', 'nmes', 'electroanalgesia', 'electroestimulacion', 'electrodo~', 'corriente galvanica', 'corrientes de baja', 'corrientes de alta', 'corriente bifasica', 'fototerapia', 'alta frecuencia', 'iontoforesis']),
    (38, ['crioterapia', 'termoterapia', 'hidroterapia', 'hidrocinesiterapia', 'parafina', 'termorregulacion', 'compresas', 'envolturas', 'baños calientes', 'estimulo termico']),
    (37, ['suspension', 'polea~']),
    (36, ['mecanoterapia', 'espaldera~', 'palanca~']),
    (35, ['drenaje linfatico', 'masoterapia', 'masaje', 'cyriax', 'friccion transversa', 'periostio', 'capas fasciales', 'maniobras de masaje']),
    # especialidades clínicas (respiratorio ANTES que cardio)
    (21, ['respiratori~', 'espirometr~', 'eltgol', 'desobstruccion bronquial', 'disnea', 'aerosol~', 'oxigenoterapia', 'ventilacion mecanica no invasiva', 'obstructiv~', 'restrictiv~', 'peet', 'capacidad pulmonar', 'estertor', 'musculatura respiratoria', 'presion espiratoria positiva', 'flujo espiratorio', 'inhalacion', 'destete', 'rehabilitacion respiratoria']),
    (24, ['escoliosis', 'cifosis', 'lordosis', 'deformidad~ de la columna', 'espondilolistesis', 'columna vertebral', 'respiracion escoliotica']),
    (27, ['reumatolog~', 'artritis reumatoide', 'espondilitis anquilosante', 'lupus', 'esclerodermia', 'polimiositis', 'dermatomiositis', 'osteoporosis', 'paget', 'condrocalcinosis', 'osteonecrosis', 'osteomalacia', 'ledderhose', 'artropatia~']),
    (28, ['neurolog~', 'bobath', 'esclerosis lateral amiotrofica', 'guillain', 'polineuropatia', 'hemiplej~', 'plexo braquial', 'par craneal', 'trigemino', 'mano del predicador', 'ictus', 'poliomielitis', 'nivel neurologico', 'reflejo', 'nervio mediano', 'nervio']),
    (22, ['cardiovascular', 'cardiac~', 'cardiopatia', 'isquemi~', 'linfedema', 'flebiti~', 'flebotrombosis', 'venosa', 'arterial', 'paciente critico', 'ventilacion mecanica', 'quemad~', 'trasplante', 'linfadenectomia', 'linfocele', 'cancer de mama', 'circulacion periferica']),
    (30, ['ortopedia', 'ortesis']),
    (29, ['malformacion~ congenita', 'pie equino varo', 'equino varo congenito', 'marfan', 'luxacion congenita', 'displasia']),
    (23, ['traumatolog~', 'fractura~', 'fisura', 'epifisiolisis', 'rigidez articular', 'secuela~', 'partes blandas', 'rotura', 'pauwels', 'ligamento cruzado', 'ligamento', 'tendin~']),
    (25, ['artrosis', 'osteoartr~', 'osteoarticular~']),
    (31, ['incontinencia', 'enuresis', 'prolapso', 'suelo pelvico', 'urologic~', 'preparacion al parto', 'gimnasia postnatal', 'vejiga', 'intravesical']),
    (26, ['algias cronicas', 'fibromialgia', 'puncion seca', 'dolor miofascial', 'sindrome de dolor', 'dolor cronico']),
    (32, ['conductiva', 'psicomotor']),
    (34, ['cinesiterapia', 'movilizacion pasiva', 'movilizacion activa', 'escapula alada', 'fortalecimiento muscular', 'cinesiterapic~', 'inmovilizacion']),
    (40, ['ergonomia', 'higiene postural', 'escuela de espalda', 'movilizacion de enfermos', 'ayudas tecnicas manuales', 'angulos de confort', 'wisner', 'levantar pesos', 'higienico postural~']),
    (41, ['lesion~ deportiva~', 'fisioterapia en el deporte', 'ejercicio fisico adaptado', 'recuperacion funcional tras lesion']),
    # teoría / gestión
    (18, ['wcpt', 'confederacion mundial de fisioterapia', 'atencion primaria', 'niveles de actuacion',
           'evolucion historica de la fisioterapia', 'criterio de exclusion', 'ambito de las ciencias']),
    (13, ['practica clinica basada en la evidencia', 'niveles de evidencia', 'guia~ de practica clinica', 'educacion para la salud', 'adherencia al tratamiento', 'via clinica', 'mapa de cuidados']),
    (14, ['metodologia de investigacion', 'epidemiolog~', 'estudio analitico', 'estudio descriptivo', 'estudio de investigacion', 'declaracion obligatoria', 'tipo de diseño', 'de tipo analitico', 'interrogatorio']),
    (15, ['salud publica', 'morbilidad', 'mortalidad', 'letalidad', 'esperanza de vida', 'plan integral de atencion a la accidentabilidad', 'accidentabilidad']),
    (16, ['auditoria~', 'programa~ de calidad', 'evaluacion de la calidad', 'estructura, proceso y resultado']),
    (17, ['antiseptic~', 'desinfectante~', 'higiene hospitalaria', 'aislamiento', 'infeccion~ hospitalaria~', 'prevencion primaria', 'ulcera~ por presion', 'jabon~', 'geles', 'factores de riesgo para la salud']),
    (12, ['bioetica', 'secreto profesional', 'deontolog~', 'eutanasia', 'responsabilidad profesional', 'dilema~ etico~']),
    (11, ['demografia sanitaria', 'mapa sanitario', 'indicadores demografic~', 'gestion por procesos', 'seguridad del paciente']),
    (19, ['exploracion fisica', 'entrevista clinica', 'valoracion funcional', 'valoracion analitica']),
]


def rule_keywords(t):
    for tema, kws in KW:
        k = anyof(t, *kws)
        if k:
            return tema, f'keyword T{tema} "{k}"'
    return None


RULES = [rule_norma, rule_tiebreaks, rule_instrumento, rule_keywords]


def classify(r):
    """Prioridad al enunciado: primero solo el enunciado; si no da señal, enunciado+opciones."""
    for scope, tag in ((stem_of(r), ''), (full_of(r), ' [opc]')):
        for rule in RULES:
            res = rule(scope)
            if res:
                return res[0], res[1] + tag
    return None, 'sin señal fiable'


def validate(show=25):
    verif = load_corpus()
    by_id = {r['id']: r for r in verif}
    ref = json.load(open(REF_PATH, encoding='utf-8'))
    ok = wrong = nullc = missing = 0
    errors = []
    for item in ref:
        r = by_id.get(item['id'])
        if r is None:
            missing += 1
            continue
        golds = {item['tema']} | ({item['tema2']} if item.get('tema2') else set())
        pred, ev = classify(r)
        if pred is None:
            nullc += 1
        elif pred in golds:
            ok += 1
        else:
            wrong += 1
            errors.append((item['id'], item['tema'], item.get('tema2'), pred, ev, (r.get('q') or '')[:66]))
    total = ok + wrong + nullc
    decided = ok + wrong
    print('=== ACUERDO vs 150 ===')
    print(f'  OK={ok} WRONG={wrong} NULL={nullc} (missing={missing})')
    print(f'  acuerdo sobre CLASIFICADAS: {ok}/{decided} = {100*ok/max(decided,1):.1f}%')
    print(f'  cobertura: {decided}/{total} = {100*decided/max(total,1):.1f}%')
    print(f'  acuerdo sobre TODAS (null=fallo): {ok}/{total} = {100*ok/max(total,1):.1f}%\n')
    print('=== confusiones (ref -> pred) ===')
    for (g, p), n in Counter((e[1], e[3]) for e in errors).most_common(20):
        print(f'  T{g} -> T{p}: {n}')
    print('\n=== detalle fallos ===')
    for eid, g, g2, p, ev, q in errors[:show]:
        print(f'  {eid} ref=T{g}{"/"+str(g2) if g2 else ""} pred=T{p} | {ev} | {q}')
    return ok, wrong, nullc, errors


if __name__ == '__main__':
    validate()
