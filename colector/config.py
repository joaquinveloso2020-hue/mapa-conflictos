"""Carga de configuración: registro de conflictos, fuentes, vocabulario y datos geográficos."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date

import yaml

from .texto import Buscador

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_CONFIG = os.path.join(RAIZ, "config")
DIR_RECURSOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recursos")

UE = ["AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN",
      "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE"]
GRUPOS_PAISES = {"UE": UE}


def _cargar_yaml(nombre: str) -> dict:
    with open(os.path.join(DIR_CONFIG, nombre), encoding="utf-8") as f:
        return yaml.safe_load(f)


def expandir_paises(codigos: list[str] | None) -> list[str]:
    salida: list[str] = []
    for c in codigos or []:
        for x in GRUPOS_PAISES.get(c, [c]):
            if x not in salida:
                salida.append(x)
    return salida


@dataclass
class Conflicto:
    id: str
    nombre: str
    categoria: str
    estado: str
    revisado: str
    resumen: str
    actores: list[str]
    paises_escenario: list[str]
    paises_participantes: list[str]
    partes: list[dict]
    zonas: list[str]
    fuentes: list[dict]
    vocabulario: str
    fuertes: Buscador = field(repr=False, default=None)
    lugares: Buscador = field(repr=False, default=None)
    grupos: list[Buscador] = field(repr=False, default_factory=list)
    quitar: list[str] = field(default_factory=list)
    paises_gdelt: list[str] = field(default_factory=list)
    participantes_grupos: list[str] = field(default_factory=list)
    regiones: list[dict] = field(default_factory=list)

    @property
    def paises_partes(self) -> set[str]:
        return {p for parte in self.partes for p in parte.get("paises", [])}

    def parte_de_pais(self, pais: str | None) -> str | None:
        if not pais:
            return None
        for parte in self.partes:
            if pais in parte.get("paises", []):
                return parte["nombre"]
        return None

    def publico(self) -> dict:
        return {
            "id": self.id, "nombre": self.nombre, "categoria": self.categoria,
            "estado": self.estado, "revisado": self.revisado, "resumen": self.resumen,
            "actores": self.actores, "paises_escenario": self.paises_escenario,
            "paises_participantes": self.paises_participantes,
            "participantes_grupos": self.participantes_grupos,
            "partes": [p["nombre"] for p in self.partes], "zonas": self.zonas,
            "fuentes": self.fuentes, "regiones": self.regiones,
        }


@dataclass
class Configuracion:
    conflictos: list[Conflicto]
    categorias: dict
    vocabulario: dict[str, Buscador]
    marcadores: dict[str, Buscador]
    fuentes: dict
    paises: dict
    fips_a_iso: dict
    url_sitio: str

    def conflicto(self, cid: str) -> Conflicto | None:
        for c in self.conflictos:
            if c.id == cid:
                return c
        return None

    @property
    def usuario_agente(self) -> str:
        return self.fuentes["usuario_agente"].format(url_sitio=self.url_sitio)


def _nombres_pais(paises: dict, iso3: str) -> list[str]:
    p = paises.get(iso3)
    if not p:
        return []
    nombres = []
    for idioma, valor in p["nombres"].items():
        if idioma == "otros":
            nombres.extend(valor)
        elif valor:
            nombres.append(valor)
    # Evita nombres demasiado cortos o ambiguos.
    return sorted({n for n in nombres if len(n) >= 4 or not n.isascii()})


def _clave_region(texto: str) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s'’`ʼ\-.]", "", t)


def _fecha_texto(valor) -> str:
    return valor.isoformat() if isinstance(valor, date) else str(valor)


def _indice_regiones() -> dict:
    ruta = os.path.join(DIR_RECURSOS, "regiones.json")
    if not os.path.exists(ruta):
        # Se genera con scripts/preparar_regiones.py (en GitHub Actions, antes de cada ciclo).
        return {"regiones": {}, "mares": {}, "tabla": {}, "disponible": False}
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    tabla = {}
    for codigo, r in datos["regiones"].items():
        for n in [r["n"], *r["nombres"]]:
            if n:
                tabla.setdefault((r["p"], _clave_region(n)), codigo)
    datos["tabla"] = tabla
    datos["disponible"] = True
    return datos


def _resolver_regiones(cid: str, grupos: list | None, indice: dict) -> list[dict]:
    """Regiones afectadas documentadas en el registro: cada grupo exige al menos una fuente fechada.
    Los nombres se resuelven a divisiones admin-1 de Natural Earth (scripts/preparar_regiones.py)."""
    salida = []
    for g in grupos or []:
        fuentes = g.get("fuentes") or ([g["fuente"]] if g.get("fuente") else [])
        if not fuentes:
            raise ValueError(f"{cid}: grupo de regiones sin fuente")
        if not indice.get("disponible"):
            # Sin el índice no se pueden dibujar las regiones, pero el ciclo no debe fallar por eso.
            salida.append({"nota": g.get("nota", ""), "ids": [], "paises": [],
                           "nombres": [n for ns in (g.get("lugares") or {}).values() for n in ns],
                           "mares": [], "nombres_mares": list(g.get("mares") or []),
                           "precision": g.get("precision", ""), "sin_indice": True,
                           "fuentes": [{**f, "fecha": _fecha_texto(f.get("fecha"))} for f in fuentes]})
            continue
        ids = []
        for pais, nombres in (g.get("lugares") or {}).items():
            for n in nombres:
                codigo = indice["tabla"].get((pais, _clave_region(n)))
                if not codigo:
                    raise ValueError(f"{cid}: región desconocida {pais}/{n} (ver colector/recursos/regiones.json)")
                ids.append(codigo)
        for m in g.get("mares") or []:
            if m not in indice["mares"]:
                raise ValueError(f"{cid}: área marítima desconocida {m}")
        salida.append({
            "nota": g.get("nota", ""),
            "ids": ids,
            "nombres": [f"{indice['regiones'][i]['n']}" for i in ids],
            "paises": [indice["regiones"][i]["p"] for i in ids],
            "mares": list(g.get("mares") or []),
            "nombres_mares": [indice["mares"][m] for m in g.get("mares") or []],
            "precision": g.get("precision", ""),
            "fuentes": [{**f, "fecha": _fecha_texto(f.get("fecha"))} for f in fuentes],
        })
    return salida


def cargar(url_sitio: str | None = None) -> Configuracion:
    datos = _cargar_yaml("conflictos.yaml")
    categorias = _cargar_yaml("categorias.yaml")
    vocab = _cargar_yaml("vocabulario.yaml")
    fuentes = _cargar_yaml("fuentes.yaml")
    with open(os.path.join(DIR_RECURSOS, "paises.json"), encoding="utf-8") as f:
        paises = json.load(f)["paises"]
    fips_a_iso = {}
    for iso3, p in paises.items():
        for codigo in p.get("fips") or []:
            fips_a_iso.setdefault(codigo, iso3)

    vocabulario = {k: Buscador(vocab[k]) for k in ("armado", "disputa", "diplomatico", "economico")}
    vocabulario["no_conflicto"] = Buscador(vocab.get("no_conflicto") or [])
    marcadores = {k: Buscador(vocab[k]) for k in ("atribucion", "desmentido", "preliminar")}

    indice_regiones = _indice_regiones()
    conflictos = []
    for c in datos["conflictos"]:
        cat = c["categoria"]
        if cat not in categorias["categorias"]:
            raise ValueError(f"Categoría desconocida en {c['id']}: {cat}")
        co = c.get("coincidencias") or {}
        lugares = list(co.get("lugares") or [])
        for iso3 in co.get("paises_nombre") or []:
            lugares.extend(_nombres_pais(paises, iso3))
        participantes = c.get("paises_participantes") or []
        revisado = c.get("revisado")
        conflictos.append(Conflicto(
            id=c["id"], nombre=c["nombre"], categoria=cat, estado=c.get("estado", "activo"),
            revisado=revisado.isoformat() if isinstance(revisado, date) else str(revisado),
            resumen=" ".join(str(c.get("resumen", "")).split()),
            actores=c.get("actores") or [],
            paises_escenario=c.get("paises_escenario") or [],
            paises_participantes=expandir_paises(participantes),
            participantes_grupos=[x for x in participantes if x in GRUPOS_PAISES],
            partes=c.get("partes") or [], zonas=c.get("zonas") or [],
            fuentes=[{**f, "fecha": f["fecha"].isoformat() if isinstance(f.get("fecha"), date) else str(f.get("fecha"))}
                     for f in c.get("fuentes") or []],
            vocabulario=categorias["categorias"][cat]["vocabulario"],
            fuertes=Buscador(co.get("fuertes")), lugares=Buscador(lugares),
            grupos=[Buscador(g) for g in co.get("grupos") or []],
            quitar=co.get("quitar") or [], paises_gdelt=co.get("paises_gdelt") or [],
            regiones=_resolver_regiones(c["id"], c.get("regiones"), indice_regiones),
        ))
    return Configuracion(
        conflictos=conflictos, categorias=categorias, vocabulario=vocabulario,
        marcadores=marcadores, fuentes=fuentes, paises=paises, fips_a_iso=fips_a_iso,
        url_sitio=url_sitio or os.environ.get("URL_SITIO", "https://github.com/"),
    )
