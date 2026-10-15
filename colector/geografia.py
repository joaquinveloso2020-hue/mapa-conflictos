"""Geolocalización responsable.

Se distinguen tres cosas:
  - lugar del hecho: dónde ocurrió, según la codificación de eventos de GDELT (ActionGeo), un lugar
    que el geocodificador de GDELT (GKG) identificó en el artículo y que el titular nombra, o una
    ciudad/provincia del país escenario nombrada en el titular. Con su precisión declarada.
  - países mencionados: los que aparecen en el texto o en los metadatos de GDELT.
  - país del medio: dónde tiene sede la fuente (configuración de fuentes o dominio nacional).
Si solo se conoce el país, la precisión es "pais" y NO se inventa una coordenada exacta: el mapa
lo dibuja como un indicador a nivel país, distinto de los puntos con ubicación.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

from .texto import normalizar

DIR_RECURSOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recursos")
_PALABRAS = re.compile(r"[\w'’-]+", re.UNICODE)
NOMBRES_AMBIGUOS = {normalizar(x) for x in [
    "Mobile", "Victoria", "Santa", "Union", "Independence", "Liberty", "March", "May", "Hope",
    "Salvador", "Concord", "Reading", "Bath", "Split", "Nice", "Male", "Mary", "Asia", "Europe",
    "Africa", "America", "Center", "Central", "North", "South", "East", "West", "Capital",
    "Washington", "Jordan", "Georgia", "Chad", "Niger", "Guinea", "Sudan", "Congo", "Israel",
    "Lebanon", "Palestine", "Gaza", "Taiwan", "China", "India", "Peace", "Hamas", "Military",
]}
# Homónimos: el diccionario (Natural Earth) solo tiene el lugar de otro país que el que suele
# aparecer en las noticias (Pokrovsk de Yakutia, Rusia, frente a Pokrovsk de Donetsk, Ucrania).
# No se usan desde el diccionario; sí desde el geocodificador de GDELT, que ya los desambiguó.
HOMONIMOS = {normalizar(x) for x in ["Pokrovsk"]}
# Lugares que en los titulares suelen nombrar a un gobierno, no al sitio de un hecho.
METONIMIAS = {normalizar(x) for x in ["Kremlin", "White House", "Pentagon", "Capitol", "Downing Street",
                                      "Elysee", "Élysée", "Vatican", "Wall Street", "Brussels", "Bruselas"]}


def _clave_lugar(texto: str) -> str:
    """Normaliza un nombre de lugar para compararlo con el titular (sin apóstrofos ni guiones)."""
    return re.sub(r"['’ʼ`-]", "", normalizar(texto or "")).strip()
CCTLD = {"ua": "UKR", "ru": "RUS", "il": "ISR", "ir": "IRN", "sa": "SAU", "pk": "PAK", "in": "IND",
         "af": "AFG", "sy": "SYR", "iq": "IRQ", "lb": "LBN", "ye": "YEM", "eg": "EGY", "sd": "SDN",
         "et": "ETH", "ng": "NGA", "ke": "KEN", "so": "SOM", "za": "ZAF", "cn": "CHN", "tw": "TWN",
         "jp": "JPN", "kr": "KOR", "kp": "PRK", "ph": "PHL", "vn": "VNM", "th": "THA", "kh": "KHM",
         "mm": "MMR", "id": "IDN", "my": "MYS", "ar": "ARG", "br": "BRA", "mx": "MEX", "co": "COL",
         "ve": "VEN", "ec": "ECU", "pe": "PER", "cl": "CHL", "uk": "GBR", "fr": "FRA", "de": "DEU",
         "es": "ESP", "it": "ITA", "pl": "POL", "tr": "TUR", "gr": "GRC", "rs": "SRB", "ba": "BIH",
         "ge": "GEO", "am": "ARM", "az": "AZE", "by": "BLR", "kz": "KAZ", "qa": "QAT", "ae": "ARE",
         "kw": "KWT", "bh": "BHR", "om": "OMN", "jo": "JOR", "ma": "MAR", "dz": "DZA", "tn": "TUN",
         "ly": "LBY", "ml": "MLI", "bf": "BFA", "ne": "NER", "cm": "CMR", "cd": "COD", "rw": "RWA",
         "ug": "UGA", "tz": "TZA", "mz": "MOZ", "ht": "HTI", "cu": "CUB", "au": "AUS", "nz": "NZL",
         "ca": "CAN", "ie": "IRL", "nl": "NLD", "be": "BEL", "ch": "CHE", "at": "AUT", "se": "SWE",
         "no": "NOR", "fi": "FIN", "dk": "DNK", "ee": "EST", "lv": "LVA", "lt": "LTU", "ro": "ROU",
         "bg": "BGR", "hu": "HUN", "cz": "CZE", "sk": "SVK", "md": "MDA", "bd": "BGD", "lk": "LKA",
         "np": "NPL", "gy": "GUY", "uy": "URY", "py": "PRY", "bo": "BOL", "cy": "CYP", "hk": "CHN"}


class Geografia:
    def __init__(self, paises: dict):
        self.paises = paises
        with open(os.path.join(DIR_RECURSOS, "lugares.json"), encoding="utf-8") as f:
            lugares = json.load(f)["lugares"]
        self.indice: dict[str, list[dict]] = {}
        for l in lugares:
            for n in l["n"]:
                nn = normalizar(n)
                if len(nn) < 4 or nn in NOMBRES_AMBIGUOS or nn in HOMONIMOS:
                    continue
                self.indice.setdefault(nn, []).append(l)
        self.indice_paises: dict[str, str] = {}
        for iso3, p in paises.items():
            nombres = [v for k, v in p["nombres"].items() if k != "otros" and v]
            nombres += p["nombres"].get("otros", [])
            for n in nombres:
                nn = normalizar(n)
                if len(nn) >= 4 or not nn.isascii():
                    self.indice_paises.setdefault(nn, iso3)
        self.max_ngrama = 4

    def _ngramas(self, texto: str):
        palabras = [normalizar(p) for p in _PALABRAS.findall(texto or "")]
        for i in range(len(palabras)):
            for n in range(self.max_ngrama, 0, -1):
                if i + n <= len(palabras):
                    yield i, " ".join(palabras[i:i + n]).strip("'’-")

    def paises_en_texto(self, *textos: str) -> list[str]:
        vistos: list[str] = []
        for t in textos:
            for _, g in self._ngramas(t):
                iso = self.indice_paises.get(g)
                if iso and iso not in vistos:
                    vistos.append(iso)
        return vistos

    def lugar_en_texto(self, textos: list[str], paises_permitidos: set[str]) -> dict | None:
        """Busca ciudad/provincia de los países permitidos nombrada en los textos."""
        if not paises_permitidos:
            return None
        mejores = []
        for t in textos:
            for pos, g in self._ngramas(t):
                for l in self.indice.get(g, []):
                    if l["pais"] in paises_permitidos:
                        rango = 0 if l["t"] == "ciudad" else 1
                        mejores.append((rango, pos, -(l.get("pob") or 0), l, g))
            if mejores:
                break
        if not mejores:
            return None
        mejores.sort(key=lambda x: x[:3])
        l = mejores[0][3]
        nombre = l.get("nombre_es") or l["n"][0]
        return {"nombre": nombre, "pais": l["pais"], "coord": l["c"],
                "precision": "ciudad" if l["t"] == "ciudad" else "provincia",
                "metodo": "titular"}

    def lugar_gkg_en_titular(self, art: dict, textos: list[str], paises_permitidos: set[str]) -> dict | None:
        """Lugar que GDELT (GKG) geocodificó en el artículo y que además nombra el titular."""
        candidatos = [l for l in art.get("lugares_mencionados") or []
                      if l.get("tipo") in (2, 3, 4, 5) and l.get("coord") and None not in l["coord"]
                      and (not paises_permitidos or l.get("pais") in paises_permitidos)]
        if not candidatos:
            return None
        posiciones: dict[str, int] = {}
        for t in textos:
            for pos, g in self._ngramas(t):
                posiciones.setdefault(_clave_lugar(g), pos)
        hallados = []
        for l in candidatos:
            nombre = (l.get("nombre") or "").split(",")[0].strip()
            clave = _clave_lugar(nombre)
            if (len(clave) >= 4 and clave in posiciones and clave not in NOMBRES_AMBIGUOS
                    and clave not in METONIMIAS):
                hallados.append((posiciones[clave], nombre, l))
        if not hallados:
            return None
        _, nombre, l = min(hallados, key=lambda x: x[0])
        return {"nombre": nombre, "pais": l["pais"], "coord": l["coord"],
                "precision": "ciudad" if l.get("tipo") in (3, 4) else "provincia",
                "metodo": "gkg_titular"}

    def pais_de_dominio(self, dominio: str) -> str | None:
        tld = (dominio or "").rsplit(".", 1)[-1]
        return CCTLD.get(tld)

    def etiqueta(self, iso3: str) -> list[float] | None:
        p = self.paises.get(iso3)
        return p["etiqueta"] if p else None

    def nombre(self, iso3: str) -> str:
        p = self.paises.get(iso3)
        return p["nombre"] if p else iso3


def ubicar_articulo(art: dict, geo_evento: dict | None, escenario: set[str], g: Geografia) -> dict:
    """Determina el lugar del hecho de un artículo según reglas explícitas y documentadas."""
    textos = [art.get("titulo") or "", art.get("titulo_es") or "", art.get("titulo_en") or ""]
    if geo_evento and (not escenario or geo_evento["pais"] in escenario):
        return {**{k: geo_evento[k] for k in ("nombre", "pais", "coord", "precision")},
                "metodo": "gdelt_evento"}
    # Primero el diccionario (Natural Earth); si no encuentra nada, lo que GDELT geocodificó.
    lugar = g.lugar_en_texto(textos, escenario) or g.lugar_gkg_en_titular(art, textos, escenario)
    if lugar:
        return lugar
    mencionados = [p for p in (art.get("paises_mencionados") or []) + g.paises_en_texto(*textos)
                   if p in escenario]
    if mencionados:
        pais = Counter(mencionados).most_common(1)[0][0]
        return {"nombre": g.nombre(pais), "pais": pais, "coord": None, "precision": "pais",
                "metodo": "pais_mencionado"}
    if len(escenario) == 1:
        pais = next(iter(escenario))
        return {"nombre": g.nombre(pais), "pais": pais, "coord": None, "precision": "pais",
                "metodo": "pais_del_conflicto"}
    return {"nombre": None, "pais": None, "coord": None, "precision": "desconocida", "metodo": None}


def ubicar_evento(articulos: list[dict]) -> dict:
    """Ubicación del acontecimiento: la más precisa en la que coinciden más artículos."""
    precisos = [a["lugar"] for a in articulos if a.get("lugar") and a["lugar"].get("coord")]
    if precisos:
        conteo = Counter((l["nombre"], l["pais"]) for l in precisos)
        (nombre, pais), n = conteo.most_common(1)[0]
        elegido = next(l for l in precisos if l["nombre"] == nombre and l["pais"] == pais)
        otros = sorted({l["nombre"] for l in precisos if l["nombre"] != nombre})[:4]
        return {**elegido, "coincidencias": n, "otros_lugares": otros}
    paises = [a["lugar"]["pais"] for a in articulos if a.get("lugar") and a["lugar"].get("pais")]
    if paises:
        pais, n = Counter(paises).most_common(1)[0]
        nombre = next(a["lugar"]["nombre"] for a in articulos
                      if a.get("lugar") and a["lugar"].get("pais") == pais)
        return {"nombre": nombre, "pais": pais, "coord": None, "precision": "pais",
                "metodo": "pais", "coincidencias": n, "otros_lugares": []}
    return {"nombre": None, "pais": None, "coord": None, "precision": "desconocida", "metodo": None,
            "coincidencias": 0, "otros_lugares": []}
