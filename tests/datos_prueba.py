"""Genera un conjunto de datos FICTICIO para probar la interfaz localmente (no se publica).

Uso: python -m tests.datos_prueba <carpeta_salida>
Copia la web a la carpeta indicada y escribe datos/ con acontecimientos inventados, todos
marcados con "[PRUEBA]". La web real solo usa datos/ generado por el colector en GitHub Actions.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone

from colector import config

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LUGARES = {
    "ucrania-rusia": [("Járkov", "UKR", [36.25, 49.99], "ciudad"), ("Donetsk", "UKR", [37.8, 48.0], "provincia"),
                      ("Ucrania", "UKR", None, "pais")],
    "sudan": [("El Obeid", "SDN", [30.21, 13.18], "ciudad"), ("Darfur del Norte", "SDN", [25.0, 16.0], "provincia"),
              ("Sudán", "SDN", None, "pais")],
    "iran-guerra": [("Ormuz", "IRN", [56.27, 27.1], "ciudad"), ("Kuwait", "KWT", None, "pais")],
    "israel-palestina": [("Gaza", "PSE", [34.45, 31.5], "ciudad"), ("Nablus", "PSE", [35.26, 32.22], "ciudad")],
    "yemen": [("Taiz", "YEM", [44.02, 13.58], "ciudad"), ("Jizán", "SAU", [42.55, 16.89], "ciudad")],
    "rd-congo": [("Goma", "COD", [29.22, -1.68], "ciudad"), ("RD del Congo", "COD", None, "pais")],
    "myanmar": [("Sittwe", "MMR", [92.9, 20.15], "ciudad")],
    "malvinas": [("Argentina", "ARG", None, "pais")],
    "mar-china-meridional": [("Filipinas", "PHL", None, "pais")],
    "haiti": [("Puerto Príncipe", "HTI", [-72.33, 18.54], "ciudad")],
    "sanciones-rusia": [("Rusia", "RUS", None, "pais")],
}


def main(salida: str) -> None:
    random.seed(7)
    if os.path.exists(salida):
        shutil.rmtree(salida)
    shutil.copytree(os.path.join(RAIZ, "web"), salida, ignore=shutil.ignore_patterns("datos"))
    conf = config.cargar("http://localhost/")
    ahora = datetime.now(timezone.utc)
    eventos, articulos = [], {}
    n = 0
    for cid, lugares in LUGARES.items():
        for i in range(random.randint(3, 9)):
            n += 1
            nombre, pais, coord, prec = random.choice(lugares)
            horas = random.uniform(0.2, 70)
            pub = (ahora - timedelta(hours=horas)).isoformat()
            fuentes = random.choice([1, 1, 2, 3, 5])
            estado = random.choice(["preliminar"] * 2 + ["varias_fuentes"] * 3 + ["declaracion_parte"])
            if estado == "varias_fuentes" and fuentes < 2:
                fuentes = 2
            if estado != "varias_fuentes":
                fuentes = 1 if estado == "preliminar" else 0
            keys = []
            for j in range(max(fuentes, 1)):
                k = f"k{n}-{j}"
                idioma = random.choice(["en", "es", "fr", "ar", "ru"])
                traducido = idioma != "es" and random.random() > 0.15
                articulos[k] = {
                    "k": k, "url": f"https://ejemplo.invalid/{k}",
                    "titulo": f"[PRUEBA] Titular original ficticio {n}.{j} ({idioma})",
                    "titulo_es": f"[PRUEBA] Titular ficticio traducido {n}.{j} sobre {nombre}" if traducido or idioma == "es" else None,
                    "idioma": idioma,
                    "resumen": "[PRUEBA] Extracto ficticio publicado por el medio." if j == 0 else None,
                    "resumen_es": "[PRUEBA] Extracto ficticio traducido al español." if j == 0 and traducido else None,
                    "traduccion": {"estado": "ok" if traducido else ("original" if idioma == "es" else "sin_modelo"),
                                   "error": None if traducido or idioma == "es" else "no hay modelo para este idioma"},
                    "fuente_nombre": f"Medio de prueba {j}", "organizacion": f"Medio de prueba {j}",
                    "dominio": "ejemplo.invalid", "pais_medio": random.choice(["GBR", "FRA", "ESP", "QAT", "RUS"]),
                    "tipo_fuente": "medio", "pub": pub if random.random() > 0.2 else None,
                    "detectado": (ahora - timedelta(hours=horas - 0.1)).isoformat(),
                    "visto_gdelt": pub if random.random() > 0.5 else None,
                    "lugar": {"nombre": nombre, "pais": pais, "coord": coord, "precision": prec, "metodo": "titular"},
                    "via": "rss",
                }
                keys.append(k)
            eventos.append({
                "id": f"{cid}-{n}", "conflicto": cid,
                "titulo": f"[PRUEBA] Acontecimiento ficticio {n} en {nombre}",
                "titulo_traducido": True, "articulo_principal": keys[0],
                "lugar": {"nombre": nombre, "pais": pais, "coord": coord, "precision": prec,
                          "metodo": "gdelt_evento" if coord else "pais_mencionado", "otros_lugares": []},
                "primera_publicacion": pub, "ultima_publicacion": pub,
                "primera_deteccion": pub, "ultima_deteccion": pub, "fechas_hecho": [pub[:10]],
                "referencia": pub, "n_articulos": len(keys), "estado": estado,
                "fuentes_independientes": fuentes, "origenes": [],
                "partes_con_fuente": {"Rusia": ["oficial"]} if estado == "declaracion_parte" else {},
                "contrapuestas": random.random() > 0.8, "atribuida": random.random() > 0.6,
                "marcado_preliminar": False, "reglas": "[PRUEBA] Regla aplicada (ficticia).",
                "creado": pub, "articulos": keys, "articulos_omitidos": 0,
            })
    datos = os.path.join(salida, "datos")
    os.makedirs(datos)
    conflictos = []
    for c in conf.conflictos:
        d = c.publico()
        d["estadisticas"] = {"eventos_72h": sum(1 for e in eventos if e["conflicto"] == c.id), "eventos_24h": 0,
                             "ultima_noticia": None, "articulos_72h": 0}
        d["revision_pendiente"] = False
        conflictos.append(d)
    json.dump({"generado": ahora.isoformat(), "categorias": conf.categorias["categorias"], "conflictos": conflictos,
               "paises": {i: p["nombre"] for i, p in conf.paises.items()},
               "etiquetas_paises": {i: p["etiqueta"] for i, p in conf.paises.items()}},
              open(os.path.join(datos, "conflictos.json"), "w"), ensure_ascii=False)
    json.dump({"generado": ahora.isoformat(), "ventana_horas": 72, "eventos": eventos, "articulos": articulos},
              open(os.path.join(datos, "eventos.json"), "w"), ensure_ascii=False)
    json.dump({"generado": ahora.isoformat(), "candidatos": [{
        "id": "cand-BOL", "pais": "BOL", "nombre": "[PRUEBA] Actividad armada reportada en Bolivia",
        "estado": "detectado", "primera_deteccion": ahora.isoformat(), "ultima_deteccion": ahora.isoformat(),
        "reglas": "[PRUEBA] Señales ficticias.", "articulos": [], "etiqueta": conf.paises["BOL"]["etiqueta"]}]},
        open(os.path.join(datos, "candidatos.json"), "w"), ensure_ascii=False)
    elecciones = []
    for dias, pais, cargos, tipos, prec in [(3, "CHL", "Presidente (2.ª vuelta)", ["ejecutivo"], "dia"),
                                            (12, "DEU", "Parlamento", ["legislativo"], "dia"),
                                            (40, "KEN", "Presidente y Asamblea Nacional", ["ejecutivo", "legislativo"], "dia"),
                                            (70, "UKR", "Referendo", ["referendo"], "mes"),
                                            (200, "IND", "Presidente", ["ejecutivo"], "dia")]:
        f = (ahora + timedelta(days=dias)).date()
        if prec == "mes":
            f = f.replace(day=1)
        elecciones.append({"id": f"prueba-{pais}", "pais": pais, "pais_nombre": conf.paises[pais]["nombre"], "pais_en": pais,
                           "territorio": False, "fecha": f.isoformat(), "fin": None, "precision": prec, "anio": f.year,
                           "texto_fecha": None, "cargos": f"[PRUEBA] {cargos}", "cargos_en": "[PRUEBA]", "tipos": tipos,
                           "indirecta": False, "articulo": "https://ejemplo.invalid/eleccion",
                           "calendario": "https://ejemplo.invalid/calendario", "fuentes": ["https://ejemplo.invalid/fuente"]})
    elecciones.append({**elecciones[0], "id": "prueba-sin-fecha", "pais": "ITA", "pais_nombre": "Italia", "fecha": None,
                       "precision": "anio", "cargos": "[PRUEBA] Parlamento", "tipos": ["legislativo"]})
    json.dump({"generado": ahora.isoformat(), "horizonte_dias": 365, "actualizado": ahora.isoformat(),
               "fuente": {"nombre": "[PRUEBA] calendario ficticio", "licencia": "CC BY-SA 4.0", "paginas": []},
               "sin_ubicar": [], "elecciones": elecciones},
              open(os.path.join(datos, "elecciones.json"), "w"), ensure_ascii=False)
    json.dump({"generado": ahora.isoformat(), "ultimo_exito": (ahora - timedelta(minutes=9)).isoformat(),
               "ciclo_ok": True, "duracion_s": 123, "advertencias": ["[PRUEBA] 2 de 58 feeds RSS fallaron en este ciclo."],
               "errores": [], "fuentes": [{"id": f["id"], "nombre": f["nombre"], "tipo": f["tipo"], "idioma": f["idioma"],
                                           "pais": f.get("pais"), "estado": "ok", "ultimo_ok": ahora.isoformat()}
                                          for f in conf.fuentes["rss"][:8]],
               "resumen_fuentes": {"total": 58, "ok": 56, "error": 2, "bloqueadas": 0},
               "gdelt": {"ultimo_archivo": ahora.strftime("%Y%m%d%H%M00"), "archivos_faltantes": 0},
               "traduccion": {"motor": "Argos Translate (prueba)", "traducidos": 10, "desde_cache": 5, "fallidos": 0, "sin_modelo": ["am"]},
               "telegram": {"configurado": True, "vinculado": True}},
              open(os.path.join(datos, "estado.json"), "w"), ensure_ascii=False)
    print(f"Datos de prueba: {len(eventos)} acontecimientos en {salida}")


if __name__ == "__main__":
    main(sys.argv[1])
