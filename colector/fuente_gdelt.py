"""Ingesta de los archivos de 15 minutos de GDELT 2.0 (Eventos y GKG, inglés y translingual).

Campos verificados con los libros de códigos oficiales:
  - Eventos 2.0 (61 columnas): ActionGeo_* = lugar donde ocurrió la acción (país FIPS 10-4,
    tipo de precisión 1=país, 2=estado EE.UU., 3=ciudad EE.UU., 4=ciudad, 5=provincia), Day,
    EventRootCode, IsRootEvent, DATEADDED y SOURCEURL.
  - GKG 2.1 (27 columnas): V2DOCUMENTIDENTIFIER (URL), V2SOURCECOMMONNAME, V2.1DATE (momento en
    que GDELT procesó el artículo), V1THEMES, V2ENHANCEDLOCATIONS (lugares mencionados),
    V2.1TRANSLATIONINFO (srclc: idioma original) y V2EXTRASXML con <PAGE_TITLE> y
    <PAGE_PRECISEPUBTIMESTAMP> (fecha de publicación, cuando GDELT la extrae).
GDELT NO entrega el texto completo ni una traducción del título: solo metadatos.
"""
from __future__ import annotations

import html
import io
import logging
import re
import zipfile
from datetime import datetime, timedelta, timezone

from . import urls
from .red import ErrorRed, obtener

log = logging.getLogger(__name__)

FLUJOS = {
    "export": "{ts}.export.CSV.zip",
    "gkg": "{ts}.gkg.csv.zip",
    "t_export": "{ts}.translation.export.CSV.zip",
    "t_gkg": "{ts}.translation.gkg.csv.zip",
}

TEMAS_ARMADOS = (
    "ARMEDCONFLICT", "KILL", "MILITARY", "TERROR", "REBELLION", "CEASEFIRE", "PEACEKEEPING",
    "SEIGE", "WOUND", "BLOCKADE", "TAX_FNCACT_MILITANTS", "TAX_FNCACT_REBELS", "TAX_FNCACT_SOLDIERS",
    "TAX_FNCACT_INSURGENTS", "TAX_FNCACT_GUNMEN", "TAX_WEAPONS", "WB_2433_CONFLICT_AND_VIOLENCE",
    "WB_2432_FRAGILITY_CONFLICT_AND_VIOLENCE", "CRISISLEX_T03_DEAD", "CRISISLEX_C07_SAFETY",
    "SECURITY_SERVICES", "KIDNAP", "MANMADE_DISASTER_IMPLIED", "SUICIDE_ATTACK", "AMBUSH",
    "UNREST_", "MILITARY_COOPERATION", "REFUGEES", "DISPLACED",
)
TEMAS_OTROS = ("SANCTIONS", "ECON_TRADE", "TAX_FNCACT_DIPLOMAT", "GOV_DIPLOMACY", "EXILE",
               "TERRITORIAL", "SOVEREIGNTY", "BORDER", "MARITIME", "ARMS_CONTROL", "NUCLEAR",
               "WMD", "ECON_SANCTIONS", "EPU_CATS_TRADE", "TRADE_DISPUTE")

IDIOMAS_639_2 = {
    "ara": "ar", "fra": "fr", "fre": "fr", "rus": "ru", "ukr": "uk", "zho": "zh", "chi": "zh",
    "spa": "es", "por": "pt", "deu": "de", "ger": "de", "ita": "it", "tur": "tr", "fas": "fa",
    "per": "fa", "heb": "he", "jpn": "ja", "kor": "ko", "hin": "hi", "urd": "ur", "ind": "id",
    "pol": "pl", "nld": "nl", "dut": "nl", "swe": "sv", "ces": "cs", "cze": "cs", "ron": "ro",
    "rum": "ro", "hun": "hu", "ell": "el", "gre": "el", "bul": "bg", "fin": "fi", "dan": "da",
    "nor": "nb", "nob": "nb", "slk": "sk", "slo": "sk", "slv": "sl", "hrv": "hr", "srp": "sr",
    "ben": "bn", "tha": "th", "vie": "vi", "msa": "ms", "may": "ms", "swa": "sw", "aze": "az",
    "kat": "ka", "geo": "ka", "hye": "hy", "arm": "hy", "kaz": "kk", "uzb": "uz", "amh": "am",
    "som": "so", "hau": "ha", "pus": "ps", "kur": "ku", "tam": "ta", "tel": "te", "mar": "mr",
    "cat": "ca", "glg": "gl", "eus": "eu", "baq": "eu", "est": "et", "lav": "lv", "lit": "lt",
    "sqi": "sq", "alb": "sq", "mkd": "mk", "mac": "mk", "bos": "bs", "bel": "be", "mya": "my",
    "bur": "my", "khm": "km", "lao": "lo", "sin": "si", "nep": "ne", "tgl": "tl", "fil": "tl",
}

_RE_TITULO = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)
_RE_PUB = re.compile(r"<PAGE_PRECISEPUBTIMESTAMP>(\d{14})</PAGE_PRECISEPUBTIMESTAMP>")
_RE_SRCLC = re.compile(r"srclc:([a-z]{3})")

PRECISION_TIPO = {1: "pais", 2: "provincia", 3: "ciudad", 4: "ciudad", 5: "provincia"}


def _ts(texto: str) -> str | None:
    try:
        return datetime.strptime(texto, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def franjas(ahora: datetime, ventana_horas: float, margen_min: int = 6) -> list[str]:
    """Marcas de tiempo de los archivos de 15 min esperables en la ventana (más reciente primero)."""
    limite = ahora - timedelta(minutes=margen_min)
    minuto = (limite.minute // 15) * 15
    actual = limite.replace(minute=minuto, second=0, microsecond=0)
    salida = []
    inicio = ahora - timedelta(hours=ventana_horas)
    while actual >= inicio:
        salida.append(actual.strftime("%Y%m%d%H%M%S"))
        actual -= timedelta(minutes=15)
    return salida


def _descomprimir(contenido: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        nombre = z.namelist()[0]
        return z.read(nombre).decode("utf-8", errors="replace")


def _f(valor: str) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def parsear_eventos(texto: str, fips_a_iso: dict) -> tuple[dict, dict, int]:
    """Devuelve (geo_por_url, conteo_descubrimiento, filas_invalidas)."""
    geo: dict[str, dict] = {}
    descubrimiento: dict[str, set] = {}
    invalidas = 0
    for linea in texto.splitlines():
        c = linea.rstrip("\r").split("\t")
        if len(c) < 61:
            if linea.strip():
                invalidas += 1
            continue
        url = c[60].strip()
        if not url.startswith("http"):
            continue
        raiz = c[28][:2]
        try:
            tipo = int(c[51] or 0)
        except ValueError:
            tipo = 0
        pais = fips_a_iso.get(c[53]) if c[53] else None
        lat, lon = _f(c[56]), _f(c[57])
        es_raiz = c[25] == "1"
        conflictivo = raiz in ("14", "15", "16", "17", "18", "19", "20")
        if raiz in ("18", "19", "20") and pais:
            descubrimiento.setdefault(pais, set()).add(urls.dominio(url))
        if tipo == 0 or not pais or lat is None or lon is None:
            continue
        candidato = {
            "nombre": (c[52] or "").split(",")[0].strip() or c[52], "pais": pais, "coord": [round(lon, 4), round(lat, 4)],
            "precision": PRECISION_TIPO.get(tipo, "pais"), "tipo": tipo,
            "fecha_hecho": f"{c[1][:4]}-{c[1][4:6]}-{c[1][6:8]}" if len(c[1]) == 8 else None,
            "codigo": c[26], "_puntaje": (es_raiz, conflictivo, tipo in (3, 4), tipo in (2, 5)),
        }
        clave = urls.clave(url)
        previo = geo.get(clave)
        if previo is None or candidato["_puntaje"] > previo["_puntaje"]:
            geo[clave] = candidato
    for v in geo.values():
        v.pop("_puntaje", None)
    return geo, {k: sorted(v) for k, v in descubrimiento.items()}, invalidas


def _temas_relevantes(temas: str) -> list[str]:
    salida = []
    for t in temas.split(";"):
        if not t:
            continue
        if t.startswith(TEMAS_ARMADOS) or t.startswith(TEMAS_OTROS):
            salida.append(t)
    return salida


def parsear_gkg(texto: str, fips_a_iso: dict, prefiltro, traducido: bool) -> tuple[list[dict], int, int]:
    """Devuelve (artículos preseleccionados, filas_totales, filas_invalidas)."""
    salida = []
    total = invalidas = 0
    for linea in texto.splitlines():
        c = linea.rstrip("\r").split("\t")
        if len(c) < 27:
            if linea.strip():
                invalidas += 1
            continue
        total += 1
        if c[2] != "1":  # 1 = WEB
            continue
        url = c[4].strip()
        if not url.startswith("http"):
            continue
        extras = c[26]
        m = _RE_TITULO.search(extras)
        titulo = html.unescape(m.group(1)).strip() if m else ""
        titulo = " ".join(titulo.split())[:400]
        if not titulo:
            continue
        temas = _temas_relevantes(c[7])
        lugares: dict[str, dict] = {}
        for bloque in c[10].split(";"):
            partes = bloque.split("#")
            if len(partes) < 9:
                continue
            iso = fips_a_iso.get(partes[2])
            if not iso:
                continue
            clave = partes[7] or partes[1]
            entrada = lugares.setdefault(clave, {
                "nombre": partes[1], "pais": iso, "tipo": int(partes[0] or 0),
                "coord": [_f(partes[6]), _f(partes[5])], "n": 0})
            entrada["n"] += 1
        paises: dict[str, int] = {}
        for l in lugares.values():
            paises[l["pais"]] = paises.get(l["pais"], 0) + l["n"]
        if not (temas or prefiltro(titulo)):
            continue
        idioma = "en"
        if traducido:
            ms = _RE_SRCLC.search(c[25])
            idioma = IDIOMAS_639_2.get(ms.group(1), ms.group(1)) if ms else None
        mp = _RE_PUB.search(extras)
        principales = sorted(lugares.values(), key=lambda x: -x["n"])[:6]
        salida.append({
            "url": url, "titulo": titulo, "resumen": "", "idioma": idioma,
            "pub": _ts(mp.group(1)) if mp else None,
            "visto_gdelt": _ts(c[1]),
            "dominio": urls.dominio(url), "fuente_id": "gdelt",
            "fuente_nombre": c[3] or urls.dominio(url), "tipo_fuente": "medio",
            "pais_medio": None, "propiedad": None, "via": "gdelt",
            "temas": temas[:12],
            "lugares_mencionados": [{k: v for k, v in l.items() if k != "n"} for l in principales],
            "paises_mencionados": sorted(paises, key=lambda p: -paises[p])[:8],
        })
    return salida, total, invalidas


def recopilar(conf, sesion, estado: dict, ahora: datetime, prefiltro) -> tuple[list[dict], dict, dict]:
    """Descarga los archivos pendientes de la ventana. Devuelve (artículos, geo_por_url, informe)."""
    cfg = conf.fuentes["gdelt"]
    base = cfg["url_base"]
    procesados = estado.setdefault("procesados", {k: {} for k in FLUJOS})
    for k in FLUJOS:
        procesados.setdefault(k, {})
    ventana = franjas(ahora, cfg.get("ventana_horas", 3))
    tope = cfg.get("max_archivos_por_ciclo", 8)
    articulos: list[dict] = []
    geo: dict = {}
    descubrimiento = estado.setdefault("descubrimiento", {})
    informe = {"archivos_ok": 0, "archivos_pendientes": 0, "archivos_faltantes": 0, "errores": [],
               "filas_invalidas": 0, "registros_gkg": 0, "ultimo_archivo": estado.get("ultimo_archivo")}
    # Primero eventos (para unir lugar del hecho con los artículos), luego GKG.
    for flujo in ("export", "t_export", "gkg", "t_gkg"):
        hechos = 0
        for ts in ventana:
            if procesados[flujo].get(ts) == "ok":
                continue
            if hechos >= tope:
                informe["archivos_pendientes"] += 1
                continue
            url = base + FLUJOS[flujo].format(ts=ts)
            try:
                r = obtener(sesion, url, timeout=60, max_bytes=80_000_000)
            except ErrorRed as e:
                if e.codigo == 404:
                    edad = ahora - datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                    if edad > timedelta(hours=cfg.get("ventana_horas", 3) - 0.25):
                        procesados[flujo][ts] = "faltante"
                        informe["archivos_faltantes"] += 1
                    else:
                        informe["archivos_pendientes"] += 1
                    continue
                informe["errores"].append(f"{flujo} {ts}: {e}")
                if len(informe["errores"]) >= 6:
                    break
                continue
            hechos += 1
            try:
                texto = _descomprimir(r.content)
            except (zipfile.BadZipFile, IndexError) as e:
                informe["errores"].append(f"{flujo} {ts}: zip inválido ({e})")
                continue
            if flujo.endswith("export"):
                g, desc, inval = parsear_eventos(texto, conf.fips_a_iso)
                geo.update(g)
                franja = descubrimiento.setdefault(ts, {})
                for pais, dominios in desc.items():
                    franja[pais] = sorted(set(franja.get(pais, [])) | set(dominios))
            else:
                arts, total, inval = parsear_gkg(texto, conf.fips_a_iso, prefiltro, flujo == "t_gkg")
                informe["registros_gkg"] += total
                articulos.extend(arts)
            informe["filas_invalidas"] += inval
            procesados[flujo][ts] = "ok"
            informe["archivos_ok"] += 1
            if not informe["ultimo_archivo"] or ts > informe["ultimo_archivo"]:
                informe["ultimo_archivo"] = ts
    estado["ultimo_archivo"] = informe["ultimo_archivo"]
    # Limpieza: conserva marcas de 48 h y descubrimiento de 72 h.
    corte = (ahora - timedelta(hours=48)).strftime("%Y%m%d%H%M%S")
    for flujo in procesados:
        procesados[flujo] = {k: v for k, v in procesados[flujo].items() if k >= corte}
    corte_desc = (ahora - timedelta(hours=72)).strftime("%Y%m%d%H%M%S")
    estado["descubrimiento"] = {k: v for k, v in descubrimiento.items() if k >= corte_desc}
    return articulos, geo, informe
