"""Estado interno persistente (rama "estado" del repositorio).

Todo lo guardado aquí es público (repositorio público) salvo las preferencias de Telegram, que se
guardan cifradas. No se guardan tokens ni identificadores privados en texto plano.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta

ARCHIVOS_GZ = ("articulos", "eventos", "traducciones", "vistos")
ARCHIVOS_JSON = ("fuentes", "gdelt", "robots", "avisos", "telegram", "ciclos", "candidatos", "informe", "meta",
                 "elecciones")
CAMPOS_PRIVADOS_ARTICULO = ("resumen_privado",)


def cargar(directorio: str) -> dict:
    estado: dict = {}
    os.makedirs(directorio, exist_ok=True)
    for nombre in ARCHIVOS_GZ:
        ruta = os.path.join(directorio, f"{nombre}.json.gz")
        try:
            with gzip.open(ruta, "rt", encoding="utf-8") as f:
                estado[nombre] = json.load(f)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            estado[nombre] = {}
    for nombre in ARCHIVOS_JSON:
        ruta = os.path.join(directorio, f"{nombre}.json")
        try:
            with open(ruta, encoding="utf-8") as f:
                estado[nombre] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            estado[nombre] = {} if nombre != "ciclos" else []
    ruta_pref = os.path.join(directorio, "preferencias.enc")
    estado["preferencias_cifradas"] = open(ruta_pref, encoding="utf-8").read().strip() \
        if os.path.exists(ruta_pref) else None
    return estado


def guardar(directorio: str, estado: dict) -> None:
    os.makedirs(directorio, exist_ok=True)
    for nombre in ARCHIVOS_GZ:
        datos = estado.get(nombre, {})
        if nombre == "articulos":
            datos = {k: {c: v for c, v in a.items() if c not in CAMPOS_PRIVADOS_ARTICULO}
                     for k, a in datos.items()}
        ruta = os.path.join(directorio, f"{nombre}.json.gz")
        tmp = ruta + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, ruta)
    for nombre in ARCHIVOS_JSON:
        ruta = os.path.join(directorio, f"{nombre}.json")
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(estado.get(nombre, {}), f, ensure_ascii=False, indent=1)
        os.replace(tmp, ruta)
    if estado.get("preferencias_cifradas"):
        with open(os.path.join(directorio, "preferencias.enc"), "w", encoding="utf-8") as f:
            f.write(estado["preferencias_cifradas"])
    with open(os.path.join(directorio, "LEEME.md"), "w", encoding="utf-8") as f:
        f.write("# Estado interno del colector\n\nRama generada automáticamente en cada ciclo. "
                "No editar a mano. Las preferencias de Telegram están cifradas.\n")


def podar(estado: dict, ahora: datetime, dias_articulos: int = 7, dias_vistos: int = 30) -> None:
    lim_art = (ahora - timedelta(days=dias_articulos)).isoformat()
    estado["articulos"] = {k: a for k, a in estado["articulos"].items()
                           if (a.get("detectado") or "") >= lim_art}
    vivos = set(estado["articulos"])
    eventos = {}
    for eid, ev in estado["eventos"].items():
        ev["articulos"] = [k for k in ev["articulos"] if k in vivos]
        if ev["articulos"] and (ev.get("actualizado") or "") >= lim_art:
            eventos[eid] = ev
    estado["eventos"] = eventos
    lim_v = (ahora - timedelta(days=dias_vistos)).isoformat()
    estado["vistos"] = {k: t for k, t in estado["vistos"].items() if t >= lim_v}
    estado["ciclos"] = (estado.get("ciclos") or [])[-60:]
