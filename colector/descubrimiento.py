"""Descubrimiento de situaciones nuevas (candidatos detectados automáticamente).

Un candidato NO es un conflicto del registro. Reglas explícitas:
  - Se consideran países que no son escenario de ningún conflicto armado activo del registro.
  - Señal A (GDELT Eventos): dominios distintos que reportan agresiones, combates o violencia
    masiva (códigos CAMEO raíz 18, 19, 20) con el lugar del hecho en ese país, en 72 h.
  - Señal B (artículos): artículos con temas o vocabulario de conflicto armado que no coinciden con
    ningún conflicto del registro y cuyo país principal es ese país; se cuentan orígenes independientes.
  - "Detectado": señal A ≥ 6 dominios en ≥ 3 franjas de 15 min, y señal B ≥ 3 orígenes,
    de los cuales ≥ 3 (y al menos un 30 %) son de medios con sede en otro país. La exigencia de
    cobertura internacional evita que la violencia criminal cubierta solo por medios locales
    (frecuente en países grandes) aparezca como una situación nueva.
  - "Respaldo suficiente para revisión": además, señal B ≥ 5 orígenes en ≥ 2 días distintos.
Ningún candidato se incorpora solo al registro: una persona debe revisarlo y editar
config/conflictos.yaml (la web ofrece un borrador).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .agrupacion import fecha_referencia

CATEGORIAS_ARMADAS = {"guerra_estados", "guerra_civil", "otro_armado"}


def detectar(conf, articulos: dict, gdelt_desc: dict, previos: dict, ahora: datetime) -> dict:
    cubiertos = set()
    for c in conf.conflictos:
        if c.estado == "activo" and c.categoria in CATEGORIAS_ARMADAS:
            cubiertos.update(c.paises_escenario)

    senal_a: dict[str, set] = defaultdict(set)
    franjas_por_pais: dict[str, set] = defaultdict(set)
    for franja, paises in gdelt_desc.items():
        for pais, dominios in paises.items():
            if pais in cubiertos:
                continue
            senal_a[pais].update(dominios)
            franjas_por_pais[pais].add(franja)

    limite = (ahora - timedelta(hours=72)).isoformat()
    senal_b: dict[str, list[dict]] = defaultdict(list)
    for a in articulos.values():
        if a.get("conflictos") or not a.get("armado_sin_conflicto"):
            continue
        ref = fecha_referencia(a) or ""
        if ref < limite:
            continue
        principal = (a.get("lugar") or {}).get("pais") or (a.get("paises_mencionados") or [None])[0]
        if principal and principal not in cubiertos:
            senal_b[principal].append(a)

    salida = {}
    for pais in set(senal_a) | set(senal_b):
        arts = senal_b.get(pais, [])
        origenes = {a.get("origen") for a in arts if a.get("origen")}
        extranjeros = {a.get("origen") for a in arts
                       if a.get("pais_medio") and a.get("pais_medio") != pais}
        dias = {(fecha_referencia(a) or "")[:10] for a in arts}
        a_dom = len(senal_a.get(pais, ()))
        a_franjas = len(franjas_por_pais.get(pais, ()))
        internacional = len(extranjeros) >= 3 and len(extranjeros) >= 0.3 * max(len(origenes), 1)
        detectado = a_dom >= 6 and a_franjas >= 3 and len(origenes) >= 3 and internacional
        if not detectado:
            continue
        respaldo = len(origenes) >= 5 and len(dias) >= 2
        cid = f"cand-{pais}"
        previo = previos.get(cid, {})
        arts_orden = sorted(arts, key=lambda a: fecha_referencia(a) or "", reverse=True)
        salida[cid] = {
            "id": cid,
            "pais": pais,
            "nombre": f"Actividad armada reportada en {conf.paises.get(pais, {}).get('nombre', pais)}",
            "estado": "respaldo_suficiente" if respaldo else "detectado",
            "primera_deteccion": previo.get("primera_deteccion") or ahora.isoformat(),
            "ultima_deteccion": ahora.isoformat(),
            "senal_gdelt_dominios": a_dom,
            "senal_gdelt_franjas": a_franjas,
            "origenes_independientes": len(origenes),
            "origenes_extranjeros": len(extranjeros),
            "dias_con_cobertura": len(dias),
            "articulos": [a["k"] for a in arts_orden[:8]],
            "reglas": ("Señal GDELT: {} dominios en {} franjas; artículos: {} orígenes ({} de otros países) "
                       "en {} día(s).").format(a_dom, a_franjas, len(origenes), len(extranjeros), len(dias)),
        }
    return salida
