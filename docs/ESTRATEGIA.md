# Estrategia probabilística — OPE Fisioterapeuta SESPA 2026

Documento maestro. Estado a 14-08-2026.

---

## 0. Datos duros verificados

| Dato | Valor | Fuente |
|---|---|---|
| Plazas | 33 (29 libre + 4 PI) | BOPA 13-V-2025 |
| Examen | **12-09-2026**, Fac. Economía, Campus del Cristo, Oviedo | COFISPA / Res. 4-VI-2026 |
| Estructura | 80 preguntas = **15 comunes + 65 específicas** | fisiooposiciones (⚠ no literal del BOPA) |
| Penalización | **Los fallos NO restan** | ídem ⚠ |
| Aprobado | 5/10 → **40 aciertos** | ídem ⚠ |
| Fase concurso | 50% (70% experiencia / 30% formación) | BOPA |
| Temario Anexo III | **44 temas: 11 generales + 33 específicos** | BOPA 13-V-2025 |
| Rectificación temario | **NO afecta a Fisioterapeuta** | BOPA 30-V-2025, Cód. 2025-04400 |

⚠ = pendiente de verificar contra el literal del BOPA (Cód. 2025-03471 y bases 2025-03458). Reserva y tiempo sin confirmar.

**Nota méritos** (fuera del examen): el punto Decimoséptimo del BOPA 30-V-2025 fija para Fisioterapeuta 0,04 pts/crédito CFC y 0,1 pts/crédito ECTS.

---

## 1. El modelo

### 1.1 Unidad de análisis
No es la pregunta: es el **hecho evaluado**. "Ángulo de Cobb = tangentes a los platillos de las vértebras límite" es un hecho, aunque aparezca redactado distinto en SESCAM y en Murcia. El corpus se deduplica a nivel de hecho. Sin esto las frecuencias se inflan por reciclaje de enunciado.

### 1.2 Estructura deductiva (dos niveles)
- **Nivel 1 — Tema Tₙ**: taxonomía **cerrada**, los 44 temas del Anexo III. No se inventan categorías.
- **Nivel 2 — Nodo Nₙ.ⱼ**: dentro de cada tema, los hechos concretos que el tribunal repite.

El temario fija el **prior**; el corpus solo lo **actualiza**. Dirichlet con α proporcional al peso del temario.

### 1.3 Restricción de representación
El tribunal muestrea **por temas**, no de un saco común. De ahí:

```
Tema general   → 15 ÷ 11 = 1,36 preguntas esperadas
Tema específico → 65 ÷ 33 = 1,97 preguntas esperadas
```

**Consecuencia crítica: el temario es casi plano.** 24 de los 33 temas específicos son áreas de un solo tema (~2 preguntas). No existe un área que acapare el 20% del examen. **Un Pareto clásico sobre áreas es matemáticamente imposible aquí.**

Corolario: el motor de mayo 2026, que asignaba "Cinesiterapia: 7 preguntas", era falso por construcción. Cinesiterapia es el TEMA 34, uno de 33.

### 1.4 Dónde vive el Pareto de verdad
**Dentro** del tema, no entre temas. El TEMA 24 (deformidades del raquis) vale ~2 preguntas y de sus mil hechos posibles siempre caen los mismos: Cobb, definición de escoliosis, Risser. El corpus sirve para **identificar qué nodo de cada tema repite el tribunal**, no para repesar áreas.

### 1.5 Verosimilitud ponderada
Cada pregunta del corpus pesa:

```
w = e^(−λ·Δaños) × κ(CCAA)
```

Decaimiento temporal (el temario deriva) × proximidad estructural a Asturias. λ y κ se calibran contra hold-out, no se fijan a ojo.

### 1.6 Criterio de orden — **E/c, no E**
Para cada tema: **Eₙ** = preguntas esperadas, **cₙ** = horas hasta dominarlo.

Se ordena por **Eₙ/cₙ**. Es un problema de mochila, no un Pareto. El 20% es dónde se corta, no cómo se ordena.

Con E≈2 fijo en casi todos los temas específicos, **el orden lo decide íntegramente el coste**:

| Tema | c | E/c |
|---|---|---|
| T43 Relajación (Jacobson, Schultz) | 1 h | 2,00 |
| T44 Vendaje funcional | 1 h | 2,00 |
| T37 Suspensioterapia / poleoterapia | 1 h | 2,00 |
| T40 Ergonomía / escuela de espalda | 1,5 h | 1,33 |
| T36 Mecanoterapia | 1,5 h | 1,33 |
| T34 Cinesiterapia | 3 h | 0,67 |
| T39 Electroterapia + láser + US + NMES | 6 h | 0,33 |
| T23 Traumatología | 8 h | 0,25 |
| **T28 Neurología** | **15 h** | **0,13 ← el peor** |

Neurología cuesta quince veces más que Relajación y paga lo mismo: 2 preguntas.

**La parte general es el mejor negocio del examen**: 11 temas, 15 preguntas, memorística y finita. Y es lo que casi nadie prioriza.

### 1.7 Función objetivo — sin penalización

```
Nota = 80 · [ C·a + (1−C)·g ]
```

- **C** = masa de preguntas cubierta por el estudio
- **a** = acierto en lo estudiado (~0,85)
- **g** = acierto adivinando (base 0,25 con 4 opciones)

Con g=0,25, a=0,85 y umbral 40/80: **C ≥ 0,42**. Cubriendo el 42% de la masa se aprueba. No el 80%.

**Nunca se deja nada en blanco.** Los fallos no restan.

### 1.8 Segundo estimador: subir g
El "sentido de examen" deja de ser intuición y pasa a parámetro medible. Del corpus se extrae: frecuencia de "todas son correctas" como correcta, sesgo de longitud de la opción correcta, comportamiento de los enunciados con "INCORRECTA", distribución posicional. Si g sube de 0,25 a 0,38 → **+10 preguntas gratis**. Con penalización esto no valdría nada; sin ella, es de lo más rentable.

### 1.9 Validación
Ajustar con exámenes hasta el año T, predecir T+1, medir aciertos esperados vs reales. Si el modelo no bate a "estudiar el temario uniformemente", se tira. Sin hold-out esto es un cuento.

---

## 2. Las tres fases

1. **Base de datos y parser** ← en curso
2. **Visualizador** — HTML: nº de preguntas configurable, cronómetro, y tras cada respuesta panel con ruta en el árbol, motivo de selección, Δnodo, Δárea, Δnota proyectada. Incorpora un **selector-stub** (solo frecuencia) para que la fase 3 lo sustituya sin tocar la interfaz.
3. **Algoritmo de selección** — el motor real que alimenta ese panel.

---

## 3. Fase 1 — arquitectura de ingesta

**Regla de oro: los ficheros pasan por disco, nunca por el contexto del chat.** Pegar un HTML en el chat cuesta ~25.000 tokens; adjuntarlo como fichero y parsearlo cuesta ~500.

### 3.1 Fuente
`elcelatagarrapata.blogspot.com` — 54 páginas de test de fisioterapeuta, 2002-2026, ~50 preguntas cada una. Techo ~2.700 preguntas. Índice completo en `indice_examenes.csv`.

### 3.2 Estructura del HTML (validada con sonda 14-08-2026)
Cada pregunta es un `<form name="preguntaNN">`. **La clave de respuestas viaja en el propio HTML**, en el atributo `onclick` de cada `<input type="radio">`:

```html
<form name="pregunta01">
  <p>1. Enunciado...<br /></p><blockquote>
  <input name="pregunta01" onclick="respuesta01('Incorrecto')" type="radio" />Opción A<br />
  <input name="pregunta01" onclick="respuesta01('Correcto')"   type="radio" />Opción B<br />
  ...
  Resultado: <input name="resultado" size="10" type="text" /></blockquote>
</form>
```

No hace falta cruzar con las plantillas oficiales en PDF.

### 3.3 Esquema de salida (JSONL, una pregunta por línea)

```json
{"id":"SESCAM2026-024","org":"SESCAM","ccaa":"Castilla-La Mancha",
 "fecha":"2026-03-15","turno":"libre+PI+discap","num":24,
 "bloque":"raquis","tema":null,"nodo":null,
 "q":"enunciado","opts":["A","B","C","D"],"resp":"A"}
```

`tema` y `nodo` se rellenan en fase 3. `bloque` es etiqueta provisional.

### 3.4 QA automático — el código valida, no yo leyendo
- Recuento por página, exactamente 4 opciones, exactamente una `Correcto`.
- **Distribución de la letra correcta ≈ 25% en A/B/C/D.** Es el detector de parser roto más barato y fiable que existe. Si sale 80% en una letra, el extractor falla.
- Opciones anormalmente cortas → HTML truncado.
- Hash normalizado entre exámenes: los duplicados **no son error, son la señal** (nodos que el tribunal repite).
- Muestreo humano de 3 preguntas al azar por examen (~5% del corpus).
- Un examen que falla el QA se marca `cuarentena` y **no entra en el cálculo de frecuencias**. Nunca un dato dudoso toca el prior.

---

## 4. Estado del corpus

| Fichero | Contenido | Estado |
|---|---|---|
| `indice_examenes.csv` | 54 fuentes catalogadas | ✅ |
| `corpus_sescam2026_p1.jsonl` | SESCAM 15-03-2026, preguntas 1-50, **con respuestas** | ✅ QA pasado (22/26/30/22 %) |

**Restante: 53 páginas.** A 5-6 por sesión, ~9 sesiones.

Orden de prioridad del lote 1: SESCAM 2026 P2 · RSM 2026 P1+P2 · SAS 2025 P1+P2.

Criterio de barrido: **a lo ancho** (un examen reciente por CCAA) antes que a lo hondo. El objetivo es predecir Asturias 2026, y lo ancho captura mejor qué se pregunta hoy en España.

---

## 5. Principios que no se negocian

1. **Cero frecuencias inventadas.** Si un número no sale del corpus o del BOPA, va marcado como hipótesis.
2. **El prior sale del temario oficial**, no del criterio de nadie.
3. **Se ordena por E/c**, nunca por E.
4. **Pareto dentro del tema**, jamás entre temas.
5. **Nada en blanco** el día del examen.
6. **Sin hold-out no hay modelo**, hay narrativa.
