"""Calendario de elecciones nacionales de los próximos 12 meses.

Fuente: los artículos "<año> national electoral calendar" de la Wikipedia en inglés (texto bajo
licencia CC BY-SA 4.0), leídos con la API pública de MediaWiki, sin clave ni costo. De cada renglón
se toma la fecha, el país, qué se elige, el artículo de esa elección y las fuentes que cita.

Wikipedia no es una fuente oficial: la web lo dice y enlaza la fuente citada para verificar.
Las páginas se consultan como mucho cada REFRESCO_HORAS; si la consulta falla, se conserva el
último calendario obtenido y se informa la antigüedad.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote

from . import red
from .texto import normalizar

API = "https://en.wikipedia.org/w/api.php"
PAGINA = "{anio}_national_electoral_calendar"
URL_PAGINA = "https://en.wikipedia.org/wiki/{titulo}"
HORIZONTE_DIAS = 365
REFRESCO_HORAS = 6
LICENCIA = "CC BY-SA 4.0"

MESES = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
# Secciones del artículo que no son meses.
SECCIONES_SIN_FECHA = ("unknown", "unscheduled", "to be determined", "tbd", "date unknown", "undated")
SECCIONES_FIN = ("see also", "references", "notes", "external links", "footnotes")

# Nombres del artículo que no coinciden con los de la base de países.
ALIAS_PAISES = {
    "gambia": "GMB", "the gambia": "GMB", "cape verde": "CPV", "czech republic": "CZE",
    "republic of the congo": "COG", "congo": "COG", "democratic republic of the congo": "COD",
    "dr congo": "COD", "micronesia": "FSM", "timor-leste": "TLS", "east timor": "TLS",
    "united states": "USA", "united kingdom": "GBR", "ivory coast": "CIV", "côte d'ivoire": "CIV",
    "eswatini": "SWZ", "swaziland": "SWZ", "são tomé and príncipe": "STP", "sao tome and principe": "STP",
    "north korea": "PRK", "south korea": "KOR", "palestine": "PSE", "state of palestine": "PSE",
    "vatican city": "VAT", "northern cyprus": "CYN", "western sahara": "ESH", "somaliland": "SOL",
    "kosovo": "KOS", "taiwan": "TWN", "bahamas": "BHS", "the bahamas": "BHS", "netherlands": "NLD",
    "the netherlands": "NLD", "philippines": "PHL", "the philippines": "PHL", "federated states of micronesia": "FSM",
    "hong kong": "HKG", "macau": "MAC", "macao": "MAC", "brunei": "BRN", "laos": "LAO", "syria": "SYR",
    "russia": "RUS", "iran": "IRN", "bolivia": "BOL", "venezuela": "VEN", "tanzania": "TZA", "vietnam": "VNM",
    "moldova": "MDA", "south sudan": "SSD", "north macedonia": "MKD", "bosnia and herzegovina": "BIH",
}

# Traducción de lo que se elige (frases más largas primero).
CARGOS = [
    ("President of the State Affairs", "Presidente de Asuntos de Estado"),
    ("Constitutional referendums", "Referendos constitucionales"),
    ("Constitutional referendum", "Referendo constitucional"),
    ("House of Representatives", "Cámara de Representantes"),
    ("Chamber of Deputies", "Cámara de Diputados"),
    ("Congress of Deputies", "Congreso de los Diputados"),
    ("Council of States", "Consejo de los Estados"),
    ("National Council", "Consejo Nacional"),
    ("National Assembly", "Asamblea Nacional"),
    ("Legislative Assembly", "Asamblea Legislativa"),
    ("Legislative Council", "Consejo Legislativo"),
    ("House of Councillors", "Cámara de Consejeros"),
    ("House of Commons", "Cámara de los Comunes"),
    ("House of Keys", "Cámara de las Llaves"),
    ("House of Assembly", "Cámara de la Asamblea"),
    ("People's Assembly", "Asamblea Popular"),
    ("Supreme People's Assembly", "Asamblea Popular Suprema"),
    ("State Duma", "Duma Estatal"),
    ("Federal Council", "Consejo Federal"),
    ("Supreme Leader", "Líder Supremo"),
    ("Vice President", "Vicepresidente"),
    ("Prime Minister", "Primer ministro"),
    ("Presidency", "Presidencia"),
    ("President", "Presidente"),
    ("Parliament", "Parlamento"),
    ("Congress", "Congreso"),
    ("Senate", "Senado"),
    ("Assembly", "Asamblea"),
    ("Referendums", "Referendos"),
    ("Referendum", "Referendo"),
    ("Knesset", "Knéset"),
    ("1st round", "1.ª vuelta"),
    ("2nd round", "2.ª vuelta"),
    ("first round", "1.ª vuelta"),
    ("second round", "2.ª vuelta"),
    ("runoff", "segunda vuelta"),
    ("1st phase", "1.ª fase"),
    ("2nd phase", "2.ª fase"),
    ("3rd phase", "3.ª fase"),
    ("series 2", "serie 2"),
]
_CARGOS_RE = re.compile("|".join(re.escape(en) for en, _ in CARGOS), re.IGNORECASE)
_CARGOS_ES = {en.lower(): es for en, es in CARGOS}

_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
_REF_COMPLETO = re.compile(r"<ref(?P<attr>[^>]*?)(?<!/)>(?P<cuerpo>.*?)</ref>", re.S | re.I)
_REF_VACIO = re.compile(r"<ref(?P<attr>[^>]*?)/>", re.I)
_NOMBRE_REF = re.compile(r"""name\s*=\s*["']?([^"'/>]+?)["']?\s*(?:/|$|group)""", re.I)
_URL = re.compile(r"\burl\s*=\s*(https?://[^\s|}<]+)|(https?://[^\s|}\]<]+)", re.I)
_COMENTARIO = re.compile(r"<!--.*?-->", re.S)
_PLANTILLA = re.compile(r"\{\{[^{}]*\}\}")
_DIA_MES = re.compile(r"(\d{1,2})(?:\s*[–—-]\s*(\d{1,2}))?\s+([A-Za-z]+)")


# ----------------------------------------------------------------------------- análisis del texto
def _nombre_ref(attr: str) -> str | None:
    m = _NOMBRE_REF.search(attr.strip() + " ")
    return m.group(1).strip() if m else None


def _urls(cuerpo: str) -> list[str]:
    salida = []
    for m in _URL.finditer(cuerpo):
        u = (m.group(1) or m.group(2) or "").strip().rstrip(".,;)")
        if u and u not in salida:
            salida.append(u)
    return salida[:2]


def referencias_nombradas(texto: str) -> dict[str, list[str]]:
    """Referencias con nombre definidas en cualquier parte de la página (se reutilizan con <ref name=x/>)."""
    nombres: dict[str, list[str]] = {}
    for m in _REF_COMPLETO.finditer(texto):
        n = _nombre_ref(m.group("attr"))
        if n and n not in nombres:
            nombres[n] = _urls(m.group("cuerpo"))
    return nombres


def _quitar_refs(linea: str, nombradas: dict[str, list[str]]) -> tuple[str, list[str]]:
    fuentes: list[str] = []

    def completo(m):
        fuentes.extend(_urls(m.group("cuerpo")))
        return ""

    def vacio(m):
        n = _nombre_ref(m.group("attr"))
        fuentes.extend(nombradas.get(n, []) if n else [])
        return ""

    linea = _REF_COMPLETO.sub(completo, linea)
    linea = _REF_VACIO.sub(vacio, linea)
    return linea, list(dict.fromkeys(fuentes))[:3]


def _fechas(texto: str, anio: int) -> list[dict]:
    """'3 October', '9–10 October', '30 November – 1 December', 'October',
    '16 March, 18 June, and 16 October'. Devuelve una o más fechas con su precisión."""
    t = texto.strip().strip(":").strip()
    tl = t.lower()
    if tl in MESES:
        return [{"fecha": date(anio, MESES[tl], 1).isoformat(), "fin": None, "precision": "mes"}]
    # Rango entre meses: "30 November – 1 December".
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s*[–—-]\s*(\d{1,2})\s+([A-Za-z]+)", t)
    if m and m.group(2).lower() in MESES and m.group(4).lower() in MESES:
        try:
            return [{"fecha": date(anio, MESES[m.group(2).lower()], int(m.group(1))).isoformat(),
                     "fin": date(anio, MESES[m.group(4).lower()], int(m.group(3))).isoformat(), "precision": "dia"}]
        except ValueError:
            return []
    salida = []
    for m in _DIA_MES.finditer(t):
        mes = MESES.get(m.group(3).lower())
        if not mes:
            continue
        try:
            inicio = date(anio, mes, int(m.group(1)))
            fin = date(anio, mes, int(m.group(2))) if m.group(2) else None
        except ValueError:
            continue
        salida.append({"fecha": inicio.isoformat(), "fin": fin.isoformat() if fin else None, "precision": "dia"})
    return salida


def _pais_desde_link(destino: str, visible: str | None) -> str:
    nombre = (visible or destino).strip()
    if not visible:
        nombre = re.sub(r"^(Elections in|Politics of|Elections of)\s+", "", nombre, flags=re.I)
    return re.sub(r"^the\s+", "", nombre, flags=re.I).strip()


def _item(texto: str, nombradas: dict[str, list[str]]) -> dict | None:
    """'[[Elections in Brazil|Brazil]], [[2026 Brazilian general election|President (1st round), ...]]'"""
    territorio = "''" in texto
    texto, fuentes = _quitar_refs(texto, nombradas)
    texto = _PLANTILLA.sub("", texto).replace("'''", "").replace("''", "").strip()
    links = list(_LINK.finditer(texto))
    if len(links) < 2:
        return None
    primero = links[0]
    pais_en = _pais_desde_link(primero.group(1), primero.group(2))
    resto = texto[primero.end():]
    articulos = [l.group(1).strip() for l in links[1:]]
    cargos_en = _LINK.sub(lambda l: (l.group(2) or l.group(1)).strip(), resto)
    cargos_en = re.sub(r"\s+", " ", cargos_en).strip(" ,;:")
    if not cargos_en:
        return None
    return {"pais_en": pais_en, "territorio": territorio, "cargos_en": cargos_en,
            "articulo": articulos[0], "fuentes": fuentes}


def _sin_dia(seccion, anio: int) -> dict:
    """Fecha sin día: el mes de la sección si se conoce; si no, solo el año."""
    if isinstance(seccion, int):
        return {"fecha": date(anio, seccion, 1).isoformat(), "fin": None, "precision": "mes"}
    return {"fecha": None, "fin": None, "precision": "anio"}


def parsear(wikitexto: str, anio: int) -> list[dict]:
    """Extrae las elecciones de un artículo "<año> national electoral calendar"."""
    nombradas = referencias_nombradas(wikitexto)
    texto = _COMENTARIO.sub("", wikitexto)
    salida: list[dict] = []
    seccion = None          # número de mes, "sin_fecha", "indirectas" o None (fuera de las listas)
    fechas_pendientes: list[dict] | None = None
    for crudo in texto.splitlines():
        linea = crudo.rstrip()
        cab = re.fullmatch(r"\s*(={2,})\s*(.+?)\s*\1\s*", linea)
        if cab:
            titulo = cab.group(2).strip().lower()
            fechas_pendientes = None
            if titulo in MESES:
                seccion = MESES[titulo]
            elif any(titulo.startswith(s) for s in SECCIONES_SIN_FECHA):
                seccion = "sin_fecha"
            elif titulo.startswith("indirect"):
                seccion = "indirectas"
            elif any(titulo.startswith(s) for s in SECCIONES_FIN):
                seccion = None
            continue
        if seccion is None or not linea.lstrip().startswith("*"):
            continue
        nivel = len(linea) - len(linea.lstrip("*"))
        contenido = linea.lstrip("*").strip()
        if nivel >= 2:
            if fechas_pendientes is None:
                continue
            fechas, cuerpo = fechas_pendientes, contenido
        else:
            fechas_pendientes = None
            # "fecha: elección" (la fecha no contiene enlaces).
            m = re.match(r"([^\[\]:]+?):\s*(.*)$", contenido)
            if m and seccion != "sin_fecha":
                fechas = _fechas(m.group(1), anio) or [dict(_sin_dia(seccion, anio), texto_fecha=m.group(1).strip())]
                cuerpo = m.group(2)
                if not cuerpo.strip():
                    fechas_pendientes = fechas
                    continue
            else:
                fechas = [_sin_dia(seccion, anio)]
                cuerpo = contenido
        item = _item(cuerpo, nombradas)
        if not item:
            continue
        for f in fechas:
            salida.append({**item, **f, "anio": anio, "indirecta": seccion == "indirectas"})
    return salida


# ----------------------------------------------------------------------------- países y cargos
class IndicePaises:
    def __init__(self, paises: dict):
        self.paises = paises
        self.indice: dict[str, str] = {}
        for iso3, p in paises.items():
            nombres = [p.get("nombre"), (p.get("nombres") or {}).get("en"), (p.get("nombres") or {}).get("es")]
            nombres += (p.get("nombres") or {}).get("otros") or []
            for n in nombres:
                if n:
                    self.indice.setdefault(normalizar(n), iso3)
        for n, iso3 in ALIAS_PAISES.items():
            if iso3 in paises:
                self.indice[normalizar(n)] = iso3

    def iso3(self, nombre_en: str) -> str | None:
        n = normalizar(re.sub(r"^the\s+", "", nombre_en or "", flags=re.I))
        return self.indice.get(n)


def traducir_cargos(texto_en: str) -> str:
    es = _CARGOS_RE.sub(lambda m: _CARGOS_ES[m.group(0).lower()], texto_en)
    return re.sub(r"\band\b", "y", es)


def tipos(texto_en: str) -> list[str]:
    t = texto_en.lower()
    salida = []
    if re.search(r"president|presidency|supreme leader|prime minister|federal council|state affairs", t):
        salida.append("ejecutivo")
    if re.search(r"parliament|senate|house|chamber|assembly|congress|knesset|duma|sejm|council of states|"
                 r"national council|legislat|diet|majlis|riigikogu", t):
        salida.append("legislativo")
    if "referend" in t or "plebiscit" in t:
        salida.append("referendo")
    return salida or ["otra"]


# ----------------------------------------------------------------------------- descarga
def url_api(anio: int) -> str:
    return (f"{API}?action=parse&page={quote(PAGINA.format(anio=anio))}&prop=wikitext%7Crevid"
            f"&format=json&formatversion=2&redirects=1")


def descargar(sesion, anio: int) -> dict | None:
    """Devuelve {"wikitexto", "revid", "titulo"} o None si la página no existe todavía."""
    r = red.obtener(sesion, url_api(anio), timeout=30, max_bytes=5_000_000)
    datos = json.loads(r.content) if r is not None else {}
    if "error" in datos:
        if (datos["error"] or {}).get("code") == "missingtitle":
            return None
        raise red.ErrorRed(f"Wikipedia: {(datos['error'] or {}).get('code')}", reintentable=True)
    p = datos.get("parse") or {}
    if not p.get("wikitext"):
        raise red.ErrorRed("Wikipedia: respuesta sin texto")
    return {"wikitexto": p["wikitext"], "revid": p.get("revid"), "titulo": p.get("title") or PAGINA.format(anio=anio)}


def actualizar(cache: dict, sesion, ahora: datetime, forzar: bool = False) -> dict:
    """Refresca el calendario guardado (como mucho cada REFRESCO_HORAS). Devuelve un informe."""
    informe = {"consultado": False, "errores": []}
    ultimo = cache.get("consultado")
    if not forzar and ultimo and datetime.fromisoformat(ultimo) > ahora - timedelta(hours=REFRESCO_HORAS) \
            and str(ahora.year) in (cache.get("anios") or {}):
        return informe
    anios = cache.setdefault("anios", {})
    informe["consultado"] = True
    cache["consultado"] = ahora.isoformat()
    for anio in (ahora.year, ahora.year + 1):
        try:
            pagina = descargar(sesion, anio)
        except (red.ErrorRed, ValueError) as e:
            informe["errores"].append(f"{anio}: {e}")
            continue
        if pagina is None:
            anios.pop(str(anio), None)
            continue
        entradas = parsear(pagina["wikitexto"], anio)
        anios[str(anio)] = {"revid": pagina["revid"], "titulo": pagina["titulo"], "obtenido": ahora.isoformat(),
                            "entradas": entradas}
    # Años que ya pasaron no se guardan.
    for clave in [a for a in anios if int(a) < ahora.year]:
        anios.pop(clave)
    if informe["errores"]:
        # Ante un fallo se reintenta en una hora, no en REFRESCO_HORAS.
        cache["consultado"] = (ahora - timedelta(hours=REFRESCO_HORAS - 1)).isoformat()
    else:
        cache["ultimo_ok"] = ahora.isoformat()
    return informe


# ----------------------------------------------------------------------------- duplicados
ORDEN_PRECISION = {"dia": 0, "mes": 1, "anio": 2}


def _clave_proceso(e: dict) -> tuple:
    """Mismo proceso electoral: mismo país, mismo artículo de Wikipedia, mismo cargo (con su vuelta o fase),
    mismo año y mismo tipo de votación."""
    return (normalizar(e["pais_en"]), normalizar(e["articulo"].replace("_", " ")), normalizar(e["cargos_en"]),
            int(e["anio"]), bool(e.get("indirecta")))


def _cubre(precisa: dict, vaga: dict) -> bool:
    """La entrada precisa fecha la misma elección que la vaga: el día cae en ese mes, o el día o el mes en
    ese año (la clave ya exige el mismo año)."""
    if vaga["precision"] == "mes":
        return precisa["precision"] == "dia" and (precisa.get("fecha") or "")[:7] == (vaga.get("fecha") or "")[:7]
    if vaga["precision"] == "anio":
        return precisa["precision"] in ("dia", "mes")
    return False


def deduplicar(entradas: list[dict]) -> tuple[list[dict], int]:
    """Wikipedia a veces lista la misma elección con fecha y otra vez en "fecha desconocida" (o solo con el
    mes). Se conserva la entrada más precisa con sus fuentes; si la vaga citaba otras, se agregan después.
    No se fusionan cargos distintos (1.ª y 2.ª vuelta), fechas distintas (fases o elecciones sucesivas del
    mismo órgano) ni años distintos; si la entrada vaga podría corresponder a más de una precisa, se
    conservan todas. Devuelve copias: no modifica la caché."""
    entradas = [dict(e) for e in entradas]
    grupos: dict[tuple, list[int]] = {}
    for i, e in enumerate(entradas):
        grupos.setdefault(_clave_proceso(e), []).append(i)
    descartadas: set[int] = set()
    for indices in grupos.values():
        if len(indices) < 2:
            continue
        # Primero las de solo mes (contra las de día) y después las de solo año, así una elección con mes,
        # día y "fecha desconocida" termina en una única entrada.
        for i in sorted((k for k in indices if entradas[k]["precision"] != "dia"),
                        key=lambda k: ORDEN_PRECISION[entradas[k]["precision"]]):
            vaga = entradas[i]
            candidatas = [j for j in indices if j != i and j not in descartadas and _cubre(entradas[j], vaga)]
            if len(candidatas) != 1:
                continue
            precisa = entradas[candidatas[0]]
            precisa["fuentes"] = list(dict.fromkeys((precisa.get("fuentes") or []) + (vaga.get("fuentes") or [])))[:3]
            descartadas.add(i)
    return [e for i, e in enumerate(entradas) if i not in descartadas], len(descartadas)


# ----------------------------------------------------------------------------- publicación
def _id(e: dict) -> str:
    base = f"{e.get('pais') or e['pais_en']}-{e.get('fecha') or e['anio']}-{e['cargos_en']}"
    return re.sub(r"[^a-z0-9]+", "-", normalizar(base)).strip("-")[:90]


def publicables(cache: dict, paises: dict, ahora: datetime) -> tuple[list[dict], list[str], int]:
    """Elecciones desde hoy hasta HORIZONTE_DIAS, ordenadas por fecha, sin duplicados. También devuelve los
    nombres de países que no se pudieron ubicar en el mapa (se publican igual, con ficha pero sin símbolo)
    y la cantidad de duplicados omitidos."""
    indice = IndicePaises(paises)
    hoy = ahora.date()
    tope = hoy + timedelta(days=HORIZONTE_DIAS)
    todas = []
    for anio, datos in sorted((cache.get("anios") or {}).items()):
        titulo = datos.get("titulo") or PAGINA.format(anio=anio)
        todas.extend({**e, "_calendario": titulo} for e in datos.get("entradas") or [])
    # Antes de recortar por fecha: la entrada precisa puede caer fuera del horizonte y aun así fechar la vaga.
    todas, duplicados = deduplicar(todas)
    salida, sin_pais, vistos = [], [], set()
    for e in todas:
        titulo = e["_calendario"]
        if e["precision"] == "dia":
            inicio = date.fromisoformat(e["fecha"])
            fin = date.fromisoformat(e["fin"]) if e.get("fin") else inicio
            if fin < hoy or inicio > tope:
                continue
        elif e["precision"] == "mes":
            inicio = date.fromisoformat(e["fecha"])
            ultimo_dia = (inicio.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            if ultimo_dia < hoy or inicio > tope:
                continue
        elif int(e["anio"]) < hoy.year or int(e["anio"]) > tope.year:
            continue
        iso3 = indice.iso3(e["pais_en"])
        if not iso3 and e["pais_en"] not in sin_pais:
            sin_pais.append(e["pais_en"])
        p = paises.get(iso3) or {}
        pub = {
            "pais": iso3, "pais_nombre": p.get("nombre") or e["pais_en"], "pais_en": e["pais_en"],
            "territorio": bool(e.get("territorio")),
            "fecha": e.get("fecha"), "fin": e.get("fin"), "precision": e["precision"], "anio": int(e["anio"]),
            "texto_fecha": e.get("texto_fecha"),
            "cargos": traducir_cargos(e["cargos_en"]), "cargos_en": e["cargos_en"], "tipos": tipos(e["cargos_en"]),
            "indirecta": bool(e.get("indirecta")),
            "articulo": URL_PAGINA.format(titulo=quote(e["articulo"].replace(" ", "_"))),
            "calendario": URL_PAGINA.format(titulo=quote(titulo.replace(" ", "_"))),
            "fuentes": e.get("fuentes") or [],
        }
        pub["id"] = _id(pub)
        if pub["id"] in vistos:
            continue
        vistos.add(pub["id"])
        salida.append(pub)
    salida.sort(key=lambda x: (x["fecha"] or f"{x['anio']}-12-31", ORDEN_PRECISION[x["precision"]], x["pais_nombre"]))
    return salida, sin_pais, duplicados


def documento(cache: dict, paises: dict, ahora: datetime) -> dict:
    lista, sin_pais, duplicados = publicables(cache, paises, ahora)
    paginas = [{"anio": int(a), "titulo": d.get("titulo"), "revid": d.get("revid"), "obtenido": d.get("obtenido"),
                "url": URL_PAGINA.format(titulo=quote((d.get("titulo") or PAGINA.format(anio=a)).replace(" ", "_")))}
               for a, d in sorted((cache.get("anios") or {}).items())]
    return {
        "generado": ahora.isoformat(),
        "horizonte_dias": HORIZONTE_DIAS,
        "actualizado": cache.get("ultimo_ok"),
        "consultado": cache.get("consultado"),
        "fuente": {"nombre": "Wikipedia en inglés, calendarios electorales nacionales", "licencia": LICENCIA,
                   "paginas": paginas},
        "sin_ubicar": sin_pais,
        "duplicados_omitidos": duplicados,
        "elecciones": lista,
    }
