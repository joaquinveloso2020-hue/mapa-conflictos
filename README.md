# Mapa de conflictos

Web con un mapa mundial de conflictos y tensiones geopolíticas **vigentes**, con novedades de las últimas 24 y 72 horas, fichas por conflicto, fuentes enlazadas y alertas privadas por Telegram. Funciona sola cada 15 minutos en GitHub, sin servidores propios y con costo de operación US$0.

> No captura todos los conflictos ni todas las noticias del mundo. La clasificación, la geolocalización y la traducción son automáticas y pueden fallar: cada dato muestra su fuente, su fecha y su nivel de corroboración.

## Cómo funciona

```
GitHub Actions (cada 15 min, cron)                       GitHub Pages
┌───────────────────────────────────────────────┐         ┌─────────────────────┐
│ 1. Lee el estado anterior (rama "estado")       │         │ index.html + MapLibre│
│ 2. Descarga GDELT (archivos de 15 min) y RSS    │         │ datos/*.json         │
│ 3. Deduplica, traduce (Argos, local), clasifica │ ──────▶ │ (solo últimas 72 h)  │
│ 4. Agrupa en acontecimientos y corrobora        │         └─────────────────────┘
│ 5. Detecta situaciones nuevas (candidatos)      │
│ 6. Telegram: comandos y resumen del ciclo       │ ──────▶  Tu chat privado
│ 7. Guarda estado y publica la web               │
└───────────────────────────────────────────────┘
```

| Pieza | Servicio | Costo | Límites relevantes |
|---|---|---|---|
| Recopilación programada | GitHub Actions (repo público) | US$0 | Gratis e ilimitado en repos públicos con runners estándar; mínimo 5 min entre ejecuciones; puede demorarse en horas pico; se desactiva tras 60 días sin actividad (cada ciclo guarda estado, lo que cuenta como actividad). |
| Web | GitHub Pages (`usuario.github.io/repo`) | US$0 | Sitio ≤ 1 GB, ~100 GB/mes de tráfico. La web es pública. |
| Mapa | MapLibre GL JS + Natural Earth (dominio público) | US$0 | Sin servidor de teselas: no hay cuota. Capa opcional OpenFreeMap: gratis, sin clave, sin garantía de servicio. |
| Noticias | GDELT 2.0 (archivos cada 15 min) + RSS | US$0 | GDELT: uso libre con cita; sin garantía de disponibilidad; solo titulares y metadatos. |
| Traducción | Argos Translate (modelos abiertos en el propio runner) | US$0 | Calidad intermedia; algunos idiomas sin modelo (se muestra el original). |
| Alertas | Bot API de Telegram | US$0 | ~1 mensaje/segundo por chat; nunca se usan difusiones pagas. |

**Cuentas necesarias:** GitHub (gratis) y un bot de Telegram creado con @BotFather.

## Usar la web

- **Período**: últimas 24 h o 72 h. **Categorías**: guerra entre Estados, guerra civil, otros conflictos armados, disputas territoriales, tensiones diplomáticas, sanciones/conflictos económicos. Los colores identifican categorías, no gravedad.
- **Capas**: países coloreados (relleno = escenario, borde = participa, rayado = varias categorías), acontecimientos (puntos agrupados al alejar), zonas en disputa (Natural Earth; no indican control militar), situaciones detectadas sin verificar y mapa base detallado.
- **Buscar** un país o conflicto en el cuadro de búsqueda. Clic en un país, punto o conflicto abre su **ficha**: qué está pasando (resumen del registro con fuentes), quiénes participan, países y últimas noticias con enlaces originales.
- **Etiquetas**: *Reporte preliminar* (un solo origen), *Varias fuentes independientes* (no significa "confirmado"), *Declaración de parte* (solo fuentes oficiales o estatales de una parte), *Versiones contrapuestas*.
- **Fechas**: se separan publicación, detección y (cuando existe) fecha del hecho.
- **Estado**: la pastilla superior muestra la última actualización exitosa; si la recopilación falla o se demora, lo indica (nunca dice "en vivo"). La pestaña *Fuentes y estado* detalla cada fuente.

## Alertas por Telegram

Comandos (se aplican en el próximo ciclo, hasta ~15 min):

| Comando | Qué hace |
|---|---|
| `/estado` | Configuración y última actualización |
| `/pausar` · `/pausar 6` | Pausa indefinida o por 6 horas (lo ocurrido durante la pausa no se envía después) |
| `/reanudar` | Reactiva los avisos |
| `/mundial` | Resumen mundial por ciclo (configuración inicial; mínimo 2 fuentes independientes) |
| `/paises AR UA SD` | Solo esos países (códigos o nombres) |
| `/conflictos sudan ucrania-rusia` | Solo esos conflictos (`/lista` muestra los ids) |
| `/agregar …` · `/quitar …` | Suma o quita países/conflictos |
| `/fuentes 1` | Mínimo de fuentes independientes (1–5) |
| `/desvincular` | Deja de enviar avisos |

Cada aviso incluye conflicto, novedad breve en español, fuente, fecha disponible, enlace original y etiqueta de verificación. Las novedades duplicadas se agrupan, se envía como máximo un resumen por ciclo (hasta 3 mensajes) y **solo si hay algo nuevo**. Lo anterior a la vinculación no se envía.

## Mantenimiento

- **Registro de conflictos**: `config/conflictos.yaml`. Cada entrada tiene categoría, actores, países, fuentes fechadas y fecha de revisión. Editalo desde la web de GitHub (lápiz ✏️) para agregar, actualizar o cerrar un conflicto. La web marca "revisión pendiente" a los 90 días. Un conflicto **no** se cierra solo por falta de noticias.
- **Candidatos**: la capa "Situaciones detectadas" muestra posibles situaciones nuevas según reglas explícitas. La ficha incluye un borrador para copiar al registro tras verificarlo.
- **Fuentes**: `config/fuentes.yaml` (RSS, GDELT y dominios oficiales/estatales). Si una fuente falla seguido, la pestaña *Fuentes y estado* lo muestra; se puede quitar o corregir su URL.
- **Ver qué pasó en un ciclo**: pestaña *Actions* del repositorio → "Actualizar mapa". El resumen de cada ejecución no contiene datos privados.
- **Ejecutar un ciclo a mano**: *Actions* → "Actualizar mapa" → *Run workflow*.
- **Si se desactiva el cron** (60 días sin actividad): *Actions* → "Actualizar mapa" → *Enable workflow*.

## Secretos (Settings → Secrets and variables → Actions)

| Secreto | Para qué |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot (de @BotFather). Nunca se guarda en el código ni en el navegador. |
| `TELEGRAM_CODIGO_VINCULACION` | Código de un solo uso para vincular tu chat (`/vincular CÓDIGO`). |
| `ESTADO_CLAVE` (opcional) | Clave para cifrar tus preferencias de alertas en la rama `estado`. Si no existe, se deriva del token del bot (si cambiás el token, hay que volver a vincular el chat). Generar con `python -m colector clave`. |

## Desarrollo local

```bash
pip install -r requirements-dev.txt
python -m colector validar
python -m pytest -q                       # pruebas con datos ficticios
python -m colector ciclo --estado /tmp/estado --salida web/datos   # ciclo real (requiere red)
```

## Créditos y licencias de datos

The GDELT Project (uso libre con cita), Natural Earth (dominio público), MapLibre GL JS (BSD-3), fuente Open Sans (Apache 2.0), Argos Translate (MIT; modelos con licencias abiertas), OpenFreeMap/OpenMapTiles/OpenStreetMap (capa opcional, atribución requerida). Los titulares y extractos pertenecen a cada medio; se muestran brevemente, atribuidos y con enlace al original.
