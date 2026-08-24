# Trainer OPE Fisioterapeuta SESPA 2025

Entrenador de test para el concurso-oposición de Fisioterapeuta del Servicio de
Salud del Principado de Asturias. Examen: **12 de septiembre de 2026**, 80
preguntas (15 de la parte general + 65 de la específica), 100 minutos, sin
penalización por fallo.

## Cómo usarlo

`trainer.html` es un **único fichero autocontenido**: lleva dentro las 3.204
preguntas, los pesos por tema y las familias del canon. No pide ningún recurso
externo — cero `fetch`, cero CDN, cero fuentes remotas.

**Descárgalo y ábrelo en el navegador.** Funciona desde el sistema de archivos,
también en el móvil, y sin conexión.

> GitHub **no ejecuta** el HTML: al abrirlo aquí se ve el código. Tampoco sirve
> `raw.githubusercontent.com`, que lo entrega como texto plano. Hay que
> descargarlo, o servirlo desde algún sitio que lo entregue como HTML.

El progreso se guarda en `localStorage`, o sea **por navegador y por origen**: el
historial de la copia local y el de una copia servida en web son distintos y no
se sincronizan. Conviene elegir una y usar siempre esa.

## Qué hay dentro

| | |
|---|---|
| Preguntas | 3.204, todas con respuesta verificada |
| Clasificadas por tema | 2.014 contra los 44 temas del Anexo del BOPA |
| Familias del canon | 540 (preguntas que interrogan el mismo hecho con otra redacción) |
| Bloque autonómico | 4 del SESPA 2025 + 94 de exámenes del SESPA/ERA |

Modos: como el examen (15/65), canon, Top 7 temas, solo autonómico, solo
Asturias, temas flojos y aleatorio.

## El pipeline

Los `.py` reconstruyen el corpus desde cero. Orden:

```bash
python descargar_blog.py            # 54 páginas del blog
python parse_blog.py fuentes/blog/ --indice indice_examenes.csv \
       --out corpus/corpus_blog.jsonl --cuarentena corpus/cuarentena.jsonl
python ocr_asturias.py              # cuadernillo escaneado de Asturias 2019
python ingest_osakidetza.py         # baterías de Osakidetza
python ingest_sas.py                # SAS 2025, turno libre
python descargar_sespa2025.py       # exámenes SESPA nov-2025
python ocr_sespa2025.py --columnas  # vienen escaneados y a dos columnas
python ingest_sespa2025.py --generales 15
python exportar_corpus.py           # une las partes en corpus/corpus.jsonl
python clasificar_temas.py          # clasifica contra los 44 temas
.venv_emb/Scripts/python clustering_canon.py --umbral 0.25
python generar_trainer.py           # produce trainer.html
python -m pytest                    # 54 tests
```

Las fuentes descargadas (109 MB de PDF y HTML) no están versionadas: las
recuperan los tres scripts de descarga.

## Requisitos

- Python 3.11, `pdfplumber`, `pypdf`, `beautifulsoup4`, `scipy`, `scikit-learn`
- Tesseract con el idioma español, y poppler (para `pdf2image`)
- Un venv aparte para los embeddings, porque `sentence-transformers` no importa
  con la versión de `transformers` del sistema y la 4.57 no es compatible con
  torch 2.3. Ver `.gitignore`.

Las rutas del stack de OCR están en `ocr_config.py` y admiten variables de
entorno para moverlo a otra máquina.
