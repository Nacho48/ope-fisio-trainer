# Prompt para Claude Code

Copia todo lo que hay debajo de la línea.

---

Necesito un parser en Python que extraiga preguntas de examen de oposición desde páginas HTML guardadas del blog `elcelatagarrapata.blogspot.com`, y las vuelque a JSONL con un informe de control de calidad.

## Contexto

Estoy construyendo un corpus de ~2.500 preguntas reales de oposiciones de Fisioterapeuta del sistema sanitario español, para un análisis de frecuencias que oriente mi estudio. Las fuentes son 54 páginas HTML, cada una con ~50 preguntas tipo test de un examen oficial concreto.

Trabajo con contexto de LLM limitado, así que **el script debe hacer todo el trabajo y emitir solo un informe corto**. Nunca debe volcar el contenido de las preguntas a stdout salvo en el muestreo explícito.

## Estructura del HTML de entrada

Cada pregunta es un `<form>`. La respuesta correcta está codificada en el atributo `onclick` de cada `<input type="radio">`. Ejemplo literal:

```html
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
```

Detalles reales que he verificado y que hay que manejar:

- El enunciado va dentro del `<p>` inicial del form, empieza con `N. ` (número y punto) y puede llevar **saltos de línea internos** que hay que colapsar a espacios simples.
- Las opciones son el texto que va **después** de cada `<input>` y antes del `<br />`.
- Hay entidades HTML sin decodificar: `&#191;` (¿), `&#8211;` (–), `&quot;`, `&#160;`. Decodifícalas todas.
- **Algunas opciones vienen prefijadas con `a) `, `b) `, `c) `, `d) `** y otras no. Normaliza: quita ese prefijo si existe.
- El HTML tiene ~2.500 líneas de menús, barra lateral y widgets de Blogger alrededor. Solo interesa lo que hay dentro de los `<form name="preguntaNN">`.
- El fichero puede venir guardado como `.html` o como `.txt` (código fuente pegado). Acepta ambos.
- La página lleva en el `<title>` la identificación del examen, p. ej.: `Test de FISIOTERAPEUTAS - OPEs 2023/24 SESCAM - SERVICIO DE SALUD DE CASTILLA-LA MANCHA - Turno Libre, Promoción Interna y Discapacidad - 15-03-2026 - Parte 1`. Extrae de ahí lo que puedas, pero **los metadatos definitivos vienen de un CSV**, no del título.

Usa `BeautifulSoup` (`html.parser`, sin dependencias externas más allá de bs4). No uses regex para parsear la estructura HTML; sí puedes usar regex para limpiar texto.

## Metadatos

Existe un `indice_examenes.csv` con columnas: `prio,ccaa_org,ano_examen,descripcion,slug_blog`. El script debe casar cada fichero de entrada con su fila del índice. Permite pasar los metadatos también por CLI (`--org`, `--ccaa`, `--fecha`, `--turno`, `--id-prefix`) para cuando el índice no cubra un fichero.

## Esquema de salida

JSONL, una pregunta por línea, UTF-8 sin escapar (`ensure_ascii=False`):

```json
{"id":"SESCAM2026-024","org":"SESCAM","ccaa":"Castilla-La Mancha","fecha":"2026-03-15","turno":"libre+PI+discap","num":24,"bloque":null,"tema":null,"nodo":null,"q":"enunciado limpio","opts":["opción A","opción B","opción C","opción D"],"resp":"A"}
```

- `resp` es la **letra** (A/B/C/D) según la posición de la opción marcada `Correcto`.
- `id` = `{id_prefix}-{num:03d}`.
- `bloque`, `tema`, `nodo` van a `null`; se rellenan en otra fase.

El script debe poder **acumular**: si el JSONL de salida ya existe, añade sin duplicar por `id`, y avisa de colisiones.

## Control de calidad (esto es lo importante)

Tras parsear, emite un informe de **máximo 20 líneas** con:

1. Nº de preguntas extraídas por fichero, y esperadas si se conoce.
2. **Distribución de la letra correcta (A/B/C/D) en % con recuento.** Es el detector principal de parser roto: debe rondar 25% cada una. Si alguna letra supera el 45%, marca `SOSPECHOSO`.
3. Preguntas con nº de opciones ≠ 4.
4. Preguntas con 0 o >1 opción marcada `Correcto`.
5. Enunciados u opciones vacías, o opciones de menos de 3 caracteres (posible truncamiento).
6. Numeración con huecos o saltos.
7. Duplicados por hash del enunciado normalizado (minúsculas, sin tildes, sin puntuación, espacios colapsados) **entre todos los exámenes del corpus acumulado**. Los duplicados NO son error: son la señal que busco. Repórtalos aparte, como `RECURRENCIAS`, indicando en qué exámenes aparece cada uno.
8. **Muestreo**: imprime 3 preguntas al azar por fichero, completas con sus opciones y la respuesta, para revisión humana.

Si un fichero falla cualquier check de los puntos 3-6, márcalo `CUARENTENA` y **escríbelo a un JSONL aparte**, no al corpus principal.

## Interfaz

```
python parse_tests.py entrada1.html entrada2.txt ... \
    --indice indice_examenes.csv \
    --out corpus.jsonl \
    --cuarentena cuarentena.jsonl \
    --informe informe_qa.txt
```

Acepta también un directorio y procesa todo lo que haya dentro.

## Además del parser

Escribe un segundo script, `stats.py`, que lea el corpus acumulado y saque:

- Total de preguntas, por CCAA y por año.
- Distribución global de la letra correcta.
- **Frecuencia de la opción "todas son correctas" / "todas son ciertas" / "ninguna de las anteriores", y con qué probabilidad esa opción es la correcta cuando aparece.**
- **Sesgo de longitud**: ¿es la opción correcta sistemáticamente más larga que las demás? Da la diferencia media en caracteres y un test estadístico sencillo.
- Frecuencia de enunciados que contienen "INCORRECTA" vs "CORRECTA", y si la tasa de acierto posicional cambia entre ambos tipos.
- Top 30 de enunciados recurrentes (por el hash normalizado).

Estas métricas alimentan un parámetro del modelo: la probabilidad de acierto adivinando sin estudiar. Como en este examen **los fallos no restan**, subir ese parámetro de 0,25 a 0,38 valen ~10 preguntas gratis sobre 80.

## Estilo

Python 3.11+, tipado, sin frameworks. Prioriza legibilidad y mensajes de error claros sobre elegancia. Incluye un `--dry-run` que parsea y da el informe sin escribir nada. Añade tests con el fragmento HTML de ejemplo de arriba.
