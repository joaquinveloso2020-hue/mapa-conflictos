"""Prepara los datos geográficos estáticos del proyecto (se ejecuta una sola vez).

Fuente: Natural Earth (dominio público), repositorio oficial
https://github.com/nvkelso/natural-earth-vector (rama master).

Genera:
  web/geo/paises.geojson        polígonos simplificados de países (1:50m)
  web/geo/zonas.geojson         zonas de disputa de soberanía seleccionadas (1:10m)
  colector/recursos/paises.json códigos, nombres multilingües y punto de etiqueta
  colector/recursos/lugares.json  ciudades y provincias para geolocalizar menciones

Uso:
  python scripts/preparar_geodatos.py --origen /ruta/con/geojson   (opcional)
Requiere: npx mapshaper (npm) para simplificar geometrías.
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

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
CAPAS = {
    "paises": "ne_50m_admin_0_countries.geojson",
    "disputas": "ne_10m_admin_0_disputed_areas.geojson",
    "ciudades": "ne_10m_populated_places_simple.geojson",
    "provincias": "ne_10m_admin_1_states_provinces.geojson",
}
IDIOMAS = ["ar", "de", "en", "es", "fa", "fr", "he", "hi", "id", "it", "ja", "ko",
           "nl", "pl", "pt", "ru", "sv", "tr", "uk", "ur", "vi", "zh"]

# Correcciones de códigos FIPS 10-4 (usados por GDELT) que Natural Earth deja en -99.
FIPS_MANUAL = {
    "ISR": ["IS"], "SSD": ["OD"], "PSE": ["WE", "GZ"], "NOR": ["NO"], "FRA": ["FR"],
    "SOL": ["SO"], "CYN": ["CY"], "KOS": ["KV"], "ESH": ["WI"], "TWN": ["TW"],
    "SRB": ["RI"], "MNE": ["MJ"], "CUW": ["UC"], "SXM": ["NN"], "BES": ["NL"],
}

# Nombres en español más usuales que los de Natural Earth.
NOMBRES_ES = {"TWN": "Taiwán", "MMR": "Myanmar (Birmania)", "CYN": "Chipre del Norte",
              "COD": "RD del Congo", "SWZ": "Esuatini", "ESH": "Sáhara Occidental"}

# Zonas de disputa de soberanía incluidas (nombre BRK_NAME de Natural Earth).
# Se excluyen a propósito polígonos que representan líneas de control o entidades
# desactualizadas (p. ej. "Donetsk/Luhansk People's Republic", "Artsakh"), porque
# mostrarían frentes o control territorial sin una fuente actual adecuada.
ZONAS_INCLUIDAS = {
    "Jammu and Kashmir": "Cachemira administrada por India (reclamada por Pakistán)",
    "Azad Kashmir": "Azad Cachemira (administrada por Pakistán, reclamada por India)",
    "Gilgit-Baltistan": "Gilgit-Baltistán (administrado por Pakistán, reclamado por India)",
    "Siachen Glacier": "Glaciar de Siachen (reclamado por India y Pakistán)",
    "Aksai Chin": "Aksai Chin (administrado por China, reclamado por India)",
    "Shaksam Valley": "Valle de Shaksgam (administrado por China, reclamado por India)",
    "Arunachal Pradesh": "Arunachal Pradesh (administrado por India, reclamado por China)",
    "Abyei": "Abyei (administrado por Sudán, reclamado por Sudán del Sur)",
    "Golan Heights": "Altos del Golán (administrados por Israel, reclamados por Siria)",
    "Shebaa Farms": "Granjas de Shebaa (administradas por Israel, reclamadas por Líbano)",
    "W. Sahara": "Sáhara Occidental (territorio en disputa entre Marruecos y el Frente Polisario)",
    "N. Cyprus": "Norte de Chipre (autoadministrado, reclamado por Chipre)",
    "Kosovo": "Kosovo (independencia no reconocida por Serbia)",
    "Abkhazia": "Abjasia (autoadministrada, reclamada por Georgia)",
    "South Ossetia": "Osetia del Sur (autoadministrada, reclamada por Georgia)",
    "Transnistria": "Transnistria (autoadministrada, reclamada por Moldavia)",
    "Crimea": "Crimea (administrada por Rusia desde 2014, reclamada por Ucrania)",
    "Somaliland": "Somalilandia (autoadministrada, reclamada por Somalia)",
    "West of Essequibo River": "Guayana Esequiba (administrada por Guyana, reclamada por Venezuela)",
    "Falkland Is.": "Islas Malvinas (administradas por Reino Unido, reclamadas por Argentina)",
    "S. Georgia": "Georgias del Sur (administradas por Reino Unido, reclamadas por Argentina)",
    "S. Sandwich Is.": "Sandwich del Sur (administradas por Reino Unido, reclamadas por Argentina)",
    "Taiwan": "Taiwán (autoadministrado, reclamado por China)",
    "Spratly Is.": "Islas Spratly (reclamadas por China, Taiwán, Malasia, Filipinas y Brunéi)",
    "Paracel Is.": "Islas Paracelso (administradas por China, reclamadas por Vietnam y Taiwán)",
    "Scarborough Reef": "Bajo de Masinloc / arrecife Scarborough (disputado entre China y Filipinas)",
    "Pinnacle Is.": "Islas Senkaku/Diaoyu (administradas por Japón, reclamadas por China y Taiwán)",
    "Kuril Is.": "Kuriles del Sur (administradas por Rusia, reclamadas por Japón)",
    "Ilemi Triangle": "Triángulo de Ilemi (administrado por Kenia, reclamado por Sudán del Sur)",
    "Halayib Triangle": "Triángulo de Hala'ib (administrado por Egipto, reclamado por Sudán)",
    "Abu Musa I.": "Abu Musa (administrada por Irán, reclamada por EAU)",
    "East Jerusalem": "Jerusalén Este (administrada por Israel, reclamada por Palestina)",
}


def descargar(nombre: str, destino: str, origen_local: str | None) -> str:
    ruta = os.path.join(destino, nombre)
    if origen_local and os.path.exists(os.path.join(origen_local, nombre)):
        return os.path.join(origen_local, nombre)
    print("Descargando", nombre, file=sys.stderr)
    urllib.request.urlretrieve(BASE_URL + nombre, ruta)
    return ruta


def simplificar(entrada: str, salida: str, porcentaje: str, campos: str) -> None:
    cmd = ["npx", "--yes", "mapshaper@0.6", entrada, "-filter-fields", campos,
           "-simplify", porcentaje, "keep-shapes", "-o", "format=geojson",
           "precision=0.001", salida]
    subprocess.run(cmd, check=True)


def id_pais(p: dict) -> str:
    for clave in ("ISO_A3_EH", "ISO_A3", "ADM0_A3"):
        v = p.get(clave)
        if v and v != "-99":
            return v
    return p["ADM0_A3"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origen", help="Carpeta con los GeoJSON de Natural Earth ya descargados")
    args = ap.parse_args()
    tmp = tempfile.mkdtemp()
    rutas = {k: descargar(v, tmp, args.origen) for k, v in CAPAS.items()}
    hoy = date.today().isoformat()

    # ---- Países -------------------------------------------------------------
    datos = json.load(open(rutas["paises"], encoding="utf-8"))
    paises = {}
    for f in datos["features"]:
        p = f["properties"]
        pid = id_pais(p)
        nombre_es = NOMBRES_ES.get(pid) or p.get("NAME_ES") or p.get("NAME")
        f["properties"] = {"id": pid, "nombre": nombre_es}
        fips = [p["FIPS_10"]] if p.get("FIPS_10") not in (None, "-99") else []
        fips = FIPS_MANUAL.get(pid, fips)
        nombres = {i: p.get("NAME_" + i.upper()) for i in IDIOMAS if p.get("NAME_" + i.upper())}
        for extra in (p.get("NAME"), p.get("NAME_LONG"), p.get("ADMIN"), p.get("FORMAL_EN")):
            if extra:
                nombres.setdefault("otros", [])
                if extra not in nombres["otros"]:
                    nombres["otros"].append(extra)
        paises[pid] = {
            "id": pid,
            "iso2": p.get("ISO_A2_EH") if p.get("ISO_A2_EH") not in (None, "-99") else None,
            "fips": fips,
            "nombre": nombre_es,
            "nombres": nombres,
            "etiqueta": [round(p.get("LABEL_X"), 3), round(p.get("LABEL_Y"), 3)],
            "continente": p.get("CONTINENT"),
            "region": p.get("SUBREGION"),
        }
    tmp_paises = os.path.join(tmp, "paises_props.geojson")
    json.dump(datos, open(tmp_paises, "w", encoding="utf-8"), ensure_ascii=False)
    simplificar(tmp_paises, os.path.join(RAIZ, "web/geo/paises.geojson"), "12%", "id,nombre")

    # ---- Zonas de disputa ---------------------------------------------------
    datos = json.load(open(rutas["disputas"], encoding="utf-8"))
    elegidas = []
    vistos: dict[str, int] = {}
    for f in datos["features"]:
        p = f["properties"]
        nombre = (p.get("BRK_NAME") or "").strip().lstrip("﻿")
        if nombre not in ZONAS_INCLUIDAS:
            continue
        zid = "ne-" + nombre.lower().replace(" ", "-").replace(".", "")
        vistos[zid] = vistos.get(zid, 0) + 1
        if vistos[zid] > 1:
            zid = f"{zid}-{vistos[zid]}"
        f["properties"] = {
            "id": zid,
            "nombre": ZONAS_INCLUIDAS[nombre],
            "nota_original": p.get("NOTE_BRK"),
            "tipo_original": p.get("TYPE"),
            "fuente": "Natural Earth 1:10m – Admin 0 Disputed Areas (rama master, versión 5.2.0-pre)",
            "fuente_url": "https://github.com/nvkelso/natural-earth-vector",
            "fecha_consulta": hoy,
        }
        elegidas.append(f)
    tmp_zonas = os.path.join(tmp, "zonas.geojson")
    json.dump({"type": "FeatureCollection", "features": elegidas},
              open(tmp_zonas, "w", encoding="utf-8"), ensure_ascii=False)
    simplificar(tmp_zonas, os.path.join(RAIZ, "web/geo/zonas.geojson"), "20%",
                "id,nombre,nota_original,tipo_original,fuente,fuente_url,fecha_consulta")
    print(f"Zonas incluidas: {len(elegidas)}", file=sys.stderr)

    # ---- Lugares (ciudades y provincias) ------------------------------------
    lugares = []
    datos = json.load(open(rutas["ciudades"], encoding="utf-8"))
    for f in datos["features"]:
        p = f["properties"]
        nombres = {n for n in (p.get("name"), p.get("nameascii"), p.get("namealt")) if n}
        lugares.append({
            "t": "ciudad",
            "n": sorted(nombres),
            "pais": p.get("adm0_a3"),
            "c": [round(p["longitude"], 4), round(p["latitude"], 4)],
            "pob": p.get("pop_max") or 0,
        })
    datos = json.load(open(rutas["provincias"], encoding="utf-8"))
    for f in datos["features"]:
        p = f["properties"]
        nombres = set()
        for clave in ("name", "name_en", "name_es", "name_fr", "name_ar", "name_ru", "name_uk",
                      "name_zh", "name_fa", "name_tr", "name_pt", "name_de"):
            if p.get(clave):
                nombres.add(p[clave])
        if p.get("name_alt"):
            nombres.update(x.strip() for x in str(p["name_alt"]).split("|") if x.strip())
        if p.get("latitude") is None:
            continue
        lugares.append({
            "t": "provincia",
            "n": sorted(nombres),
            "pais": p.get("adm0_a3"),
            "c": [round(p["longitude"], 4), round(p["latitude"], 4)],
            "nombre_es": p.get("name_es") or p.get("name"),
        })
    os.makedirs(os.path.join(RAIZ, "colector/recursos"), exist_ok=True)
    json.dump({"fuente": "Natural Earth (dominio público)", "fecha_consulta": hoy,
               "paises": paises},
              open(os.path.join(RAIZ, "colector/recursos/paises.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    json.dump({"fuente": "Natural Earth 1:10m populated places + admin 1 (dominio público)",
               "fecha_consulta": hoy, "lugares": lugares},
              open(os.path.join(RAIZ, "colector/recursos/lugares.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"Países: {len(paises)}  Lugares: {len(lugares)}", file=sys.stderr)


if __name__ == "__main__":
    main()
