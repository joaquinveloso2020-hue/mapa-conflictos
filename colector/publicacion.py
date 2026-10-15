"""Genera los archivos JSON públicos que consume la web (solo situación actual: 72 h)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from .agrupacion import resumir_evento

VENTANA_HORAS = 72
MAX_EVENTOS_CONFLICTO = 150
MAX_ARTICULOS_EVENTO = 10
CAMPOS_ARTICULO = ("k", "url", "titulo", "titulo_es", "idioma", "resumen", "resumen_es", "traduccion",
                   "fuente_nombre", "dominio", "organizacion", "agencia", "pais_medio", "tipo_fuente",
                   "propiedad", "pub", "detectado", "visto_gdelt", "fecha_hecho", "lugar",
                   "paises_mencionados", "marcas", "via", "fuente_estatal_de", "fuente_estatal_tipo",
                   "pub_descartada")


def _escribir(directorio: str, nombre: str, datos) -> None:
    os.makedirs(directorio, exist_ok=True)
    ruta = os.path.join(directorio, nombre)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ruta)


def articulo_publico(a: dict) -> dict:
    salida = {c: a.get(c) for c in CAMPOS_ARTICULO if a.get(c) not in (None, "", [], {})}
    if not a.get("extracto", True):
        salida.pop("resumen", None)
        salida.pop("resumen_es", None)
    return salida


def vistas_eventos(estado: dict, conf, ahora: datetime) -> list[dict]:
    limite = (ahora - timedelta(hours=VENTANA_HORAS)).isoformat()
    vistas = []
    for ev in estado["eventos"].values():
        arts = [estado["articulos"][k] for k in ev["articulos"] if k in estado["articulos"]]
        if not arts:
            continue
        conflicto = conf.conflicto(ev["conflicto"])
        v = resumir_evento(ev, arts, conflicto, None)
        if (v["referencia"] or "") < limite:
            continue
        v["creado"] = ev["creado"]
        v["articulos"] = [a["k"] for a in sorted(arts, key=lambda a: a.get("pub") or a.get("detectado") or "")]
        vistas.append(v)
    return vistas


def publicar(estado: dict, conf, vistas: list[dict], candidatos: dict, informe: dict,
             directorio: str, ahora: datetime, elecciones: dict | None = None) -> dict:
    hace24 = (ahora - timedelta(hours=24)).isoformat()
    por_conflicto: dict[str, list[dict]] = {}
    for v in vistas:
        por_conflicto.setdefault(v["conflicto"], []).append(v)
    eventos_pub, articulos_pub = [], {}
    stats = {}
    for cid, lista in por_conflicto.items():
        lista.sort(key=lambda v: v["referencia"] or "", reverse=True)
        importantes = [v for v in lista if v["fuentes_independientes"] >= 2]
        elegidos = {v["id"]: v for v in lista[:MAX_EVENTOS_CONFLICTO]}
        for v in importantes[:MAX_EVENTOS_CONFLICTO]:
            elegidos.setdefault(v["id"], v)
        stats[cid] = {
            "eventos_72h": len(lista),
            "eventos_24h": sum(1 for v in lista if (v["referencia"] or "") >= hace24),
            "ultima_noticia": lista[0]["referencia"] if lista else None,
            "articulos_72h": sum(v["n_articulos"] for v in lista),
        }
        for v in elegidos.values():
            keys = v["articulos"][-MAX_ARTICULOS_EVENTO:]
            if v["articulo_principal"] not in keys:
                keys = [v["articulo_principal"]] + keys[1:]
            v = {**v, "articulos": keys, "articulos_omitidos": max(0, v["n_articulos"] - len(keys))}
            eventos_pub.append(v)
            for k in keys:
                if k in estado["articulos"]:
                    articulos_pub[k] = articulo_publico(estado["articulos"][k])
    for c in conf.conflictos:
        stats.setdefault(c.id, {"eventos_72h": 0, "eventos_24h": 0, "ultima_noticia": None, "articulos_72h": 0})

    cand_pub = []
    for cand in candidatos.values():
        arts = [articulo_publico(estado["articulos"][k]) for k in cand["articulos"] if k in estado["articulos"]]
        cand_pub.append({**cand, "articulos": arts,
                         "etiqueta": conf.paises.get(cand["pais"], {}).get("etiqueta")})

    paises_nombres = {iso: p["nombre"] for iso, p in conf.paises.items()}
    conflictos_pub = []
    for c in conf.conflictos:
        d = c.publico()
        d["estadisticas"] = stats[c.id]
        try:
            revisado = datetime.fromisoformat(c.revisado + "T00:00:00+00:00")
            d["revision_pendiente"] = (ahora - revisado).days > 90
        except ValueError:
            d["revision_pendiente"] = True
        conflictos_pub.append(d)

    generado = ahora.isoformat()
    _escribir(directorio, "conflictos.json", {
        "generado": generado,
        "categorias": conf.categorias["categorias"],
        "conflictos": conflictos_pub,
        "paises": paises_nombres,
        "etiquetas_paises": {iso: p["etiqueta"] for iso, p in conf.paises.items()},
    })
    _escribir(directorio, "eventos.json", {
        "generado": generado, "ventana_horas": VENTANA_HORAS,
        "eventos": eventos_pub, "articulos": articulos_pub,
    })
    _escribir(directorio, "candidatos.json", {"generado": generado, "candidatos": cand_pub})
    if elecciones is not None:
        _escribir(directorio, "elecciones.json", elecciones)
    _escribir(directorio, "estado.json", informe)
    return {"eventos": len(eventos_pub), "articulos": len(articulos_pub), "candidatos": len(cand_pub),
            "elecciones": len((elecciones or {}).get("elecciones") or [])}
