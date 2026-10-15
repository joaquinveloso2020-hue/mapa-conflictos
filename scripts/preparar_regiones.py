"""Prepara las capas de detalle del mapa (se ejecuta al cambiar los países escenario del registro).

Fuente: Natural Earth (dominio público), https://github.com/nvkelso/natural-earth-vector.

Genera:
  web/geo/regiones.geojson        provincias/estados (admin-1) de los países escenario de los
                                  conflictos armados del registro (simplificados)
  web/geo/mares.geojson           áreas marítimas con nombre que el registro puede citar
  web/geo/ciudades.geojson        ciudades principales para dar contexto al acercar el mapa
  colector/recursos/regiones.json índice de nombres -> código admin-1 para validar el registro

Las regiones son divisiones administrativas: el mapa las usa para (a) contar los acontecimientos
geolocalizados que caen en cada una y (b) mostrar las "regiones afectadas" que el registro
documenta con una fuente fechada. NO representan control territorial ni líneas de frente.

Uso:
  python scripts/preparar_regiones.py --origen /carpeta/con/geojson   (opcional)
Requiere: npx mapshaper (npm).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
CAPAS = {
    "provincias": "ne_10m_admin_1_states_provinces.geojson",
    "mares": "ne_10m_geography_marine_polys.geojson",
    "ciudades": "ne_10m_populated_places_simple.geojson",
}
CATEGORIAS_ARMADAS = {"guerra_estados", "guerra_civil", "otro_armado"}
# Código de país del proyecto -> código adm0_a3 de la capa admin-1 de Natural Earth.
A_NE = {"PSE": "PSX", "SSD": "SDS", "ESH": "SAH"}
DE_NE = {v: k for k, v in A_NE.items()}
# Áreas marítimas disponibles (nombre en Natural Earth -> id y nombre en español).
MARES = {
    "Red Sea": ("mar-rojo", "Mar Rojo"),
    "Bab el Mandeb": ("bab-el-mandeb", "Estrecho de Bab el-Mandeb"),
    "Gulf of Aden": ("golfo-de-aden", "Golfo de Adén"),
    "Persian Gulf": ("golfo-persico", "Golfo Pérsico"),
    "Gulf of Oman": ("golfo-de-oman", "Golfo de Omán"),
    "Taiwan Strait": ("estrecho-de-taiwan", "Estrecho de Taiwán"),
    "South China Sea": ("mar-de-china-meridional", "Mar de China Meridional"),
    "East China Sea": ("mar-de-china-oriental", "Mar de China Oriental"),
    "Black Sea": ("mar-negro", "Mar Negro"),
    "Sea of Azov": ("mar-de-azov", "Mar de Azov"),
}
# Nombres en español cuando Natural Earth repite o no distingue.
NOMBRES_ES = {"UKR-4826": "Kiev (ciudad)", "UKR-321": "Kiev (óblast)",
              "RUS-2364": "Moscú (óblast)", "RUS-2365": "Moscú (ciudad)",
              # Errores de nombre en Natural Earth (verificados con sus nombres alternativos).
              "ARE-344": "Fuyaira", "AFG-1753": "Daikundi", "AFG-1769": "Panjshir",
              "YEM-3498": "Saná (ciudad)", "YEM-3496": "Saná (gobernación)",
              "MOZ-5854": "Maputo (ciudad)", "MOZ-1927": "Maputo (provincia)",
              "GAZ+00?": "Franja de Gaza", "WEB+00?": "Cisjordania", "SDS-871": "Unidad",
              "SDS-865": "Ecuatoria Central", "SDS-869": "Alto Nilo", "SDS-870": "Jonglei",
              "KEN-893": "Nororiental (antigua provincia)", "KEN-1193": "Costa (antigua provincia)",
              "KWT-1663": "Capital (Al Asimah)", "PAK-1112": "Áreas tribales (FATA, hoy parte de Jaiber Pastunjuá)",
              "COD-1559": "Orientale (antigua provincia)"}
TIPOS_ES = {"Province": "provincia", "City": "ciudad", "Highly Urbanized City": "ciudad",
            "Independent Component City": "ciudad", "Federal City": "ciudad", "Region": "región",
            "Republic": "república", "Territory": "territorio", "Governorate": "gobernación",
            "Emirate": "emirato", "State": "estado", "Oblast": "óblast"}


def _clave(texto: str) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s'’`ʼ\-\.]", "", t)


def nombre_mostrado(p: dict) -> str:
    """name_es de Natural Earth tiene algunos errores (p. ej. Fujairah = "Zona neutral"): se usa
    solo si se parece a alguno de los otros nombres de la región; si no, el nombre original."""
    if p["adm1_code"] in NOMBRES_ES:
        return NOMBRES_ES[p["adm1_code"]]
    base = p.get("name") or p.get("name_en") or p.get("gn_name") or p["adm1_code"]
    es = p.get("name_es")
    if not es:
        return base
    otros = {p.get(k) for k in ("name", "name_en", "woe_name", "gn_name", "gns_name")}
    if p.get("name_alt"):
        otros.update(x.strip() for x in str(p["name_alt"]).split("|"))
    if any(o and _clave(o)[:4] == _clave(es)[:4] for o in otros):
        return es
    return base


def descargar(nombre: str, destino: str, origen_local: str | None) -> str:
    if origen_local and os.path.exists(os.path.join(origen_local, nombre)):
        return os.path.join(origen_local, nombre)
    ruta = os.path.join(destino, nombre)
    print("Descargando", nombre, file=sys.stderr)
    urllib.request.urlretrieve(BASE_URL + nombre, ruta)
    return ruta


def simplificar(entrada: str, salida: str, porcentaje: str, campos: str, precision: str = "0.001") -> None:
    cmd = ["npx", "--yes", "mapshaper@0.6", entrada, "-filter-fields", campos,
           "-simplify", porcentaje, "keep-shapes", "-o", "format=geojson",
           f"precision={precision}", salida]
    subprocess.run(cmd, check=True)


def paises_escenario_armados() -> set[str]:
    with open(os.path.join(RAIZ, "config", "conflictos.yaml"), encoding="utf-8") as f:
        datos = yaml.safe_load(f)
    paises = set()
    for c in datos["conflictos"]:
        if c.get("categoria") in CATEGORIAS_ARMADAS:
            paises.update(c.get("paises_escenario") or [])
    return paises


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origen", help="Carpeta con los GeoJSON de Natural Earth ya descargados")
    args = ap.parse_args()
    tmp = tempfile.mkdtemp()
    rutas = {k: descargar(v, tmp, args.origen) for k, v in CAPAS.items()}
    hoy = date.today().isoformat()
    paises = paises_escenario_armados()
    ne_codigos = {A_NE.get(p, p) for p in paises}

    # ---- Regiones (admin-1) -------------------------------------------------
    datos = json.load(open(rutas["provincias"], encoding="utf-8"))
    elegidas, indice = [], {}
    for f in datos["features"]:
        p = f["properties"]
        if p.get("adm0_a3") not in ne_codigos:
            continue
        pais = DE_NE.get(p["adm0_a3"], p["adm0_a3"])
        codigo = p["adm1_code"]
        nombre = nombre_mostrado(p)
        nombres = {p.get(k) for k in ("name", "name_es", "name_en", "woe_name", "gn_name", "gns_name")}
        if p.get("name_alt"):
            nombres.update(x.strip() for x in str(p["name_alt"]).split("|"))
        nombres = sorted(n for n in nombres if n)
        etiqueta = [round(p["longitude"], 3), round(p["latitude"], 3)] if p.get("longitude") is not None else None
        indice[codigo] = {"p": pais, "n": nombre, "nombres": nombres, "tipo": p.get("type_en")}
        f["properties"] = {"id": codigo, "n": nombre, "p": pais, "t": p.get("type_en") or "",
                           "lx": etiqueta[0] if etiqueta else None, "ly": etiqueta[1] if etiqueta else None}
        elegidas.append(f)
    # Nombres repetidos dentro de un país: se agrega el tipo de división (o el nombre original).
    from collections import Counter
    for _ in range(2):
        repetidos = Counter((r["p"], r["n"]) for r in indice.values())
        for codigo, r in indice.items():
            if repetidos[(r["p"], r["n"])] > 1:
                tipo = TIPOS_ES.get(r.get("tipo") or "", "")
                extra = f" ({tipo})" if tipo and f"({tipo})" not in r["n"] else f" – {r['nombres'][0]}"
                r["n"] = r["n"] + extra
    for f in elegidas:
        f["properties"]["n"] = indice[f["properties"]["id"]]["n"]
    tmp_reg = os.path.join(tmp, "regiones.geojson")
    json.dump({"type": "FeatureCollection", "features": elegidas}, open(tmp_reg, "w", encoding="utf-8"),
              ensure_ascii=False)
    simplificar(tmp_reg, os.path.join(RAIZ, "web/geo/regiones.geojson"), "7%", "id,n,p,t,lx,ly")
    print(f"Regiones: {len(elegidas)} en {len(paises)} países", file=sys.stderr)

    # ---- Mares --------------------------------------------------------------
    datos = json.load(open(rutas["mares"], encoding="utf-8"))
    mares = []
    for f in datos["features"]:
        nombre = (f["properties"].get("name") or "").strip()
        if nombre in MARES:
            mid, nes = MARES[nombre]
            f["properties"] = {"id": mid, "n": nes}
            mares.append(f)
    tmp_mar = os.path.join(tmp, "mares.geojson")
    json.dump({"type": "FeatureCollection", "features": mares}, open(tmp_mar, "w", encoding="utf-8"),
              ensure_ascii=False)
    simplificar(tmp_mar, os.path.join(RAIZ, "web/geo/mares.geojson"), "25%", "id,n")

    # ---- Ciudades -----------------------------------------------------------
    datos = json.load(open(rutas["ciudades"], encoding="utf-8"))
    ciudades = []
    for f in datos["features"]:
        p = f["properties"]
        capital = (p.get("featurecla") or "").startswith("Admin-0 capital")
        if not (capital or (p.get("scalerank") or 10) <= 3):
            continue
        ciudades.append({"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [round(p["longitude"], 3), round(p["latitude"], 3)]},
                         "properties": {"n": p.get("name"), "r": p.get("scalerank"), "cap": 1 if capital else 0}})
    with open(os.path.join(RAIZ, "web/geo/ciudades.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": ciudades}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Ciudades: {len(ciudades)}", file=sys.stderr)

    with open(os.path.join(RAIZ, "colector/recursos/regiones.json"), "w", encoding="utf-8") as f:
        json.dump({"fuente": "Natural Earth 1:10m admin-1 y áreas marítimas (dominio público)",
                   "fecha_consulta": hoy, "regiones": indice,
                   "mares": {mid: nes for mid, nes in MARES.values()}},
                  f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
