"""Orquestación de un ciclo de recopilación (pensado para ejecutarse cada 15 minutos)."""
from __future__ import annotations

import logging
import os
import subprocess
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests

from . import almacen, config, fuente_gdelt, fuente_rss, red, urls
from .agrupacion import Agrupador, Origenes, tokens_articulo
from .cifrado import ErrorCifrado, cifrar, derivar_clave, descifrar
from .clasificacion import Prefiltro, clasificar, marcas
from .descubrimiento import detectar
from .geografia import Geografia, ubicar_articulo, ubicar_evento
from .publicacion import publicar, vistas_eventos
from .texto import normalizar
from .traduccion import Traductor, podar_cache

log = logging.getLogger("colector")

ANTIGUEDAD_MAX_DIAS = 4        # artículos publicados antes se ignoran (enfoque actual)
MAX_SIN_CONFLICTO_CICLO = 400  # artículos armados sin conflicto guardados para descubrimiento
MOTOR = "Argos Translate (modelos abiertos ejecutados localmente)"
REGLAS_VERSION = 2              # subir al cambiar config/conflictos.yaml o las reglas de clasificación


def _detectar_idioma(texto: str) -> str | None:
    try:
        import py3langid
        idioma, _ = py3langid.classify(texto)
        return idioma
    except Exception:  # noqa: BLE001
        return None


class Ciclo:
    def __init__(self, dir_estado: str, dir_salida: str, dir_modelos: str, url_sitio: str,
                 persistir_cmd: str | None = None, ahora: datetime | None = None, sesion=None,
                 sin_red: bool = False):
        self.ahora = ahora or datetime.now(timezone.utc)
        self.ahora_iso = self.ahora.isoformat()
        self.dir_estado = dir_estado
        self.dir_salida = dir_salida
        self.persistir_cmd = persistir_cmd
        self.sin_red = sin_red
        self.conf = config.cargar(url_sitio)
        self.estado = almacen.cargar(dir_estado)
        for clave in ("fuentes", "gdelt", "robots", "avisos", "telegram", "candidatos", "meta"):
            self.estado.setdefault(clave, {})
        self.sesion = sesion or red.crear_sesion(self.conf.usuario_agente)
        self.geo = Geografia(self.conf.paises)
        self.traductor = Traductor(dir_modelos, None if sin_red else self.sesion,
                                   cache=self.estado.setdefault("traducciones", {}),
                                   max_descargas=int(os.environ.get("MAX_DESCARGAS_MODELOS", "8")))
        self.origenes = Origenes(self.conf)
        self.informe = {"generado": self.ahora_iso, "ciclo_id": self.ahora.strftime("%Y%m%d%H%M"),
                        "advertencias": [], "errores": [], "etapas": {}}
        self.geo_url: dict = {}
        self.nuevos: list[str] = []
        self.inicio = time.monotonic()

    # --------------------------------------------------------------- utilidades
    def _etapa(self, nombre: str, funcion, *args, **kwargs):
        t0 = time.monotonic()
        try:
            resultado = funcion(*args, **kwargs)
            self.informe["etapas"][nombre] = {"ok": True, "segundos": round(time.monotonic() - t0, 1)}
            return resultado
        except Exception as e:  # noqa: BLE001
            log.error("Etapa %s falló: %s", nombre, traceback.format_exc())
            self.informe["etapas"][nombre] = {"ok": False, "segundos": round(time.monotonic() - t0, 1),
                                              "error": f"{type(e).__name__}: {str(e)[:200]}"}
            self.informe["errores"].append(f"{nombre}: {type(e).__name__}: {str(e)[:200]}")
            return None

    def persistir(self) -> bool:
        almacen.guardar(self.dir_estado, self.estado)
        if not self.persistir_cmd:
            return True
        try:
            r = subprocess.run(self.persistir_cmd, shell=True, timeout=180, capture_output=True, text=True)
            if r.returncode != 0:
                self.informe["errores"].append(f"no se pudo guardar el estado: {r.stderr[-200:]}")
                return False
            return True
        except subprocess.TimeoutExpired:
            self.informe["errores"].append("guardar estado: tiempo agotado")
            return False

    # ------------------------------------------------------------------ ingesta
    def ingerir(self) -> list[dict]:
        crudos: list[dict] = []
        if self.sin_red:
            return crudos
        robots = red.Robots(self.sesion, self.estado["robots"], self.conf.usuario_agente)
        rss = self._etapa("rss", fuente_rss.recopilar, self.conf.fuentes["rss"], self.sesion, robots,
                          self.estado["fuentes"], self.ahora_iso)
        if rss:
            arts, estado_fuentes = rss
            self.estado["fuentes"] = estado_fuentes
            extracto = {f["id"]: f.get("extracto", True) for f in self.conf.fuentes["rss"]}
            for a in arts:
                a["extracto"] = extracto.get(a["fuente_id"], True)
            crudos.extend(arts)
        if self.conf.fuentes["gdelt"].get("activo", True):
            prefiltro = Prefiltro(self.conf)
            g = self._etapa("gdelt", fuente_gdelt.recopilar, self.conf, self.sesion, self.estado["gdelt"],
                            self.ahora, prefiltro)
            if g:
                arts, self.geo_url, informe_gdelt = g
                self.informe["gdelt"] = informe_gdelt
                crudos.extend(arts)
        return crudos

    def incorporar(self, crudos: list[dict]) -> list[str]:
        """Deduplica por URL canónica y fusiona información. Devuelve claves a procesar."""
        arts = self.estado["articulos"]
        vistos = self.estado["vistos"]
        limite_pub = (self.ahora - timedelta(days=ANTIGUEDAD_MAX_DIAS)).isoformat()
        procesar: list[str] = []
        for c in crudos:
            k = urls.clave(c["url"])
            if c.get("pub") and c["pub"] < limite_pub:
                continue
            # Una fecha de publicación posterior a la detección no es confiable (p. ej. zona horaria
            # mal informada por el sitio): se descarta y se indica, en lugar de mostrarla.
            tope = min(x for x in (c.get("visto_gdelt"), self.ahora_iso) if x)
            if c.get("pub") and c["pub"] > (datetime.fromisoformat(tope) + timedelta(minutes=10)).isoformat():
                c["pub"] = None
                c["pub_descartada"] = "posterior a la detección"
            if k in arts:
                a = arts[k]
                vias = set(a.get("vias", [a.get("via")])) | {c["via"]}
                a["vias"] = sorted(v for v in vias if v)
                if c["via"] == "rss" and a.get("via") == "gdelt":
                    # La fuente RSS aporta resumen, fecha de publicación y metadatos de la fuente.
                    for campo in ("resumen", "resumen_privado", "autor", "fuente_id", "fuente_nombre",
                                  "tipo_fuente", "pais_medio", "propiedad", "extracto", "idioma"):
                        if c.get(campo):
                            a[campo] = c[campo]
                    a["pub"] = a.get("pub") or c.get("pub")
                    a["via"] = "rss"
                    if k not in procesar:
                        procesar.append(k)
                continue
            if k in vistos or f"x|{k}" in vistos:
                continue
            c["k"] = k
            c["detectado"] = self.ahora_iso
            c["vias"] = [c["via"]]
            if not c.get("pais_medio"):
                c["pais_medio"] = self.geo.pais_de_dominio(c.get("dominio"))
                c["pais_medio_metodo"] = "dominio" if c["pais_medio"] else None
            if not c.get("idioma"):
                c["idioma"] = _detectar_idioma(c["titulo"])
            arts[k] = c
            procesar.append(k)
        return list(dict.fromkeys(procesar))

    # --------------------------------------------------------------- traducción
    def _traducir_campo(self, claves: list[str], campo: str, destino: str, campo_salida: str) -> None:
        """Traduce un campo de varios artículos agrupando por idioma de origen."""
        por_idioma: dict[str, list[str]] = {}
        for k in claves:
            a = self.estado["articulos"][k]
            idioma = a.get("idioma")
            if not a.get(campo) or not idioma or idioma == destino or a.get(campo_salida):
                continue
            por_idioma.setdefault(idioma, []).append(k)
        for idioma, ks in por_idioma.items():
            textos = [self.estado["articulos"][k][campo] for k in ks]
            for k, r in zip(ks, self.traductor.traducir(textos, idioma, destino)):
                a = self.estado["articulos"][k]
                if r.get("texto"):
                    a[campo_salida] = r["texto"]
                elif campo == "titulo":
                    a.setdefault("traduccion_pivote", r.get("estado"))

    def pivote_ingles(self, claves: list[str]) -> None:
        tope = int(self.conf.fuentes["gdelt"].get("max_registros_traducir", 600))
        rss, gdelt = [], []
        paises_registro = set()
        for c in self.conf.conflictos:
            paises_registro.update(c.paises_escenario)
        for k in claves:
            a = self.estado["articulos"][k]
            if a.get("idioma") in (None, "en") or a.get("titulo_en"):
                continue
            if a.get("via") == "rss":
                rss.append(k)
            elif set(a.get("paises_mencionados") or []) & paises_registro or a.get("temas"):
                gdelt.append(k)
        gdelt.sort(key=lambda k: -len(self.estado["articulos"][k].get("temas") or []))
        if len(gdelt) > tope:
            self.informe["advertencias"].append(
                f"{len(gdelt) - tope} titulares de GDELT en otros idiomas no se tradujeron por el tope del ciclo")
            gdelt = gdelt[:tope]
        objetivo = rss + gdelt
        self._traducir_campo(objetivo, "titulo", "en", "titulo_en")
        self._traducir_campo(rss, "resumen_privado", "en", "resumen_en")

    def traducir_espanol(self, claves: list[str]) -> None:
        arts = self.estado["articulos"]
        con_ingles, sin_ingles = [], []
        for k in claves:
            a = arts[k]
            if a.get("idioma") == "es":
                a["titulo_es"] = a["titulo"]
                if a.get("resumen"):
                    a["resumen_es"] = a["resumen"]
                a["traduccion"] = {"estado": "original"}
                continue
            if a.get("titulo_es"):
                continue
            (con_ingles if (a.get("idioma") == "en" or a.get("titulo_en")) else sin_ingles).append(k)
        # Títulos: desde el inglés (original o pivote).
        textos = [arts[k]["titulo"] if arts[k].get("idioma") == "en" else arts[k]["titulo_en"] for k in con_ingles]
        for k, r in zip(con_ingles, self.traductor.traducir(textos, "en", "es") if textos else []):
            self._aplicar(arts[k], r, "titulo_es")
        for k in sin_ingles:
            a = arts[k]
            r = self.traductor.traducir([a["titulo"]], a.get("idioma"), "es")[0]
            self._aplicar(a, r, "titulo_es")
            if r.get("en"):
                a["titulo_en"] = r["en"]
        # Resúmenes (solo si la fuente permite extracto).
        por_idioma: dict[str, list[str]] = {}
        for k in claves:
            a = arts[k]
            if a.get("resumen") and a.get("idioma") not in ("es", None) and not a.get("resumen_es"):
                por_idioma.setdefault(a["idioma"], []).append(k)
        for idioma, ks in por_idioma.items():
            res = self.traductor.traducir([arts[k]["resumen"] for k in ks], idioma, "es")
            for k, r in zip(ks, res):
                if r.get("texto"):
                    arts[k]["resumen_es"] = r["texto"]
                else:
                    arts[k].setdefault("traduccion", {})["resumen"] = r.get("estado")

    @staticmethod
    def _aplicar(a: dict, r: dict, campo: str) -> None:
        if r.get("texto"):
            a[campo] = r["texto"]
            a["traduccion"] = {"estado": "ok", "motor": MOTOR}
        else:
            a["traduccion"] = {"estado": r.get("estado", "fallo"), "motor": MOTOR,
                               "error": r.get("error") or {
                                   "sin_modelo": f"no hay modelo de traducción para el idioma '{a.get('idioma')}'",
                                   "idioma_desconocido": "idioma no identificado",
                               }.get(r.get("estado"), "la traducción falló en este ciclo")}

    def pivote_es_en(self, claves: list[str]) -> None:
        """Títulos en español: traducción al inglés solo para agrupar con coberturas en otros idiomas."""
        es = [k for k in claves if self.estado["articulos"][k].get("idioma") == "es"
              and not self.estado["articulos"][k].get("titulo_en")]
        self._traducir_campo(es, "titulo", "en", "titulo_en")

    # ------------------------------------------------------------ clasificación
    def clasificar(self, claves: list[str]) -> list[str]:
        arts = self.estado["articulos"]
        vistos = self.estado["vistos"]
        armado = self.conf.vocabulario["armado"]
        asignados, sin_conflicto = [], 0
        for k in claves:
            a = arts[k]
            res = clasificar(a, self.conf)
            if not res and a.get("conflictos"):
                asignados.append(k)  # ya estaba asignado en un ciclo anterior: se conserva
                continue
            if res:
                a["conflictos"] = [r["id"] for r in res]
                a["clasificacion"] = res
                asignados.append(k)
                vistos[k] = self.ahora_iso
                continue
            a["conflictos"] = []
            texto = " ".join(x for x in (a.get("titulo"), a.get("titulo_en")) if x)
            es_armado = bool(a.get("temas")) and armado.hay(texto, normalizar(texto))
            if es_armado and sin_conflicto < MAX_SIN_CONFLICTO_CICLO:
                a["armado_sin_conflicto"] = True
                sin_conflicto += 1
                vistos[k] = self.ahora_iso
            else:
                del arts[k]
                if a.get("via") == "rss":
                    vistos[f"x|{k}"] = self.ahora_iso
        return asignados

    def enriquecer(self, claves: list[str]) -> None:
        arts = self.estado["articulos"]
        for k in claves:
            a = arts.get(k)
            if not a:
                continue
            self.origenes.completar(a)
            a["marcas"] = marcas(a, self.conf)
            escenario = set()
            for cid in a.get("conflictos") or []:
                c = self.conf.conflicto(cid)
                if c:
                    escenario.update(c.paises_escenario)
            ev_geo = self.geo_url.get(k)
            if ev_geo and ev_geo.get("fecha_hecho"):
                a["fecha_hecho"] = ev_geo["fecha_hecho"]
            if not a.get("conflictos"):
                escenario = set(a.get("paises_mencionados") or [])
            a["lugar"] = ubicar_articulo(a, ev_geo, escenario, self.geo)
            texto_paises = self.geo.paises_en_texto(a.get("titulo") or "", a.get("titulo_en") or "")
            a["paises_mencionados"] = list(dict.fromkeys((a.get("paises_mencionados") or []) + texto_paises))[:10]
            a["tokens"] = tokens_articulo(a)

    def agrupar(self, claves: list[str]) -> set[str]:
        agrupador = Agrupador(self.estado["eventos"], self.estado["articulos"], self.conf, self.geo, self.ahora)
        agrupador.preparar_idf()
        tocados = set()
        orden = sorted(claves, key=lambda k: self.estado["articulos"][k].get("pub")
                       or self.estado["articulos"][k].get("detectado") or "")
        for k in orden:
            a = self.estado["articulos"][k]
            a["eventos"] = {}
            for cid in a.get("conflictos") or []:
                eid = agrupador.asignar(k, cid)
                a["eventos"][cid] = eid
                tocados.add(eid)
                ev = self.estado["eventos"][eid]
                ev["lugar"] = ubicar_evento([self.estado["articulos"][x] for x in ev["articulos"]
                                             if x in self.estado["articulos"]])
        return tocados

    # -------------------------------------------------------------- telegram
    def telegram(self, vistas: list[dict], candidatos: dict, info: dict) -> dict:
        from .telegram_bot import Bot, ErrorTelegram
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        resultado = {"configurado": bool(token), "vinculado": False, "enviados_ciclo": 0, "errores": []}
        if not token:
            return resultado
        # Clave de cifrado de preferencias: secreto ESTADO_CLAVE o, si no existe, derivada del token.
        clave = os.environ.get("ESTADO_CLAVE", "").strip() or derivar_clave(token)
        try:
            pref = descifrar(self.estado.get("preferencias_cifradas"), clave)
        except ErrorCifrado as e:
            resultado["errores"].append(f"{e}. Se reiniciaron las preferencias: hay que volver a vincular el chat.")
            pref = {}
        sesion_tg = self.sesion if not isinstance(self.sesion, requests.Session) else requests.Session()
        bot = Bot(token, os.environ.get("TELEGRAM_CODIGO_VINCULACION"), sesion_tg, pref,
                  self.estado["telegram"], self.conf, self.conf.url_sitio,
                  os.environ.get("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))
        bot.procesar_comandos(self.ahora, info)
        ledger = self.estado["avisos"].setdefault("eventos", {})
        conflictos = {c.id: c.publico() for c in self.conf.conflictos}
        elegidos = bot.seleccionar(vistas, conflictos, ledger, self.ahora)
        activado = bot.pref.get("activado_en") or "9999"
        cands = [c for c in candidatos.values() if c["estado"] == "respaldo_suficiente"
                 and f"cand:{c['id']}" not in ledger and c["primera_deteccion"] > activado]
        if bot.pausado(self.ahora):
            for ev in elegidos:
                ledger[ev["id"]] = {"t": self.ahora_iso, "estado": "omitido_pausa"}
            for c in cands:
                ledger[f"cand:{c['id']}"] = {"t": self.ahora_iso, "estado": "omitido_pausa"}
            elegidos, cands = [], []
        if elegidos or cands:
            mensajes, ids = bot.construir_mensajes(elegidos, conflictos, self.estado["articulos"], cands, self.ahora)
            for ev in elegidos:
                ledger[ev["id"]] = {"t": self.ahora_iso,
                                    "estado": "enviando" if ev["id"] in ids else "resumido",
                                    "intentos": (ledger.get(ev["id"]) or {}).get("intentos", 0) + 1,
                                    "ciclo": self.informe["ciclo_id"]}
            for c in cands[:3]:
                ledger[f"cand:{c['id']}"] = {"t": self.ahora_iso, "estado": "enviando"}
            self.estado["preferencias_cifradas"] = cifrar(bot.pref, clave)
            if not self.persistir():
                # Sin estado guardado no se envía: evita duplicados si el ciclo se repite.
                for ev in elegidos:
                    ledger.pop(ev["id"], None)
                for c in cands[:3]:
                    ledger.pop(f"cand:{c['id']}", None)
                resultado["errores"].append("No se enviaron avisos porque no se pudo guardar el estado antes.")
            else:
                for i, m in enumerate(mensajes):
                    try:
                        bot.enviar(m)
                    except ErrorTelegram as e:
                        resultado["errores"].append(f"envío: {e}")
                        # Con respuesta de error, el mensaje no se entregó: se reintenta (hasta 3 veces).
                        # Sin respuesta (red), el resultado es incierto: no se reintenta para no duplicar.
                        estado_falla = "fallido" if e.con_respuesta else "incierto"
                        for eid in ids:
                            if ledger.get(eid, {}).get("estado") == "enviando":
                                ledger[eid]["estado"] = estado_falla if i == 0 else "fallido"
                        break
                for eid, v in ledger.items():
                    if v.get("estado") == "enviando":
                        v["estado"] = "enviado"
        self.estado["preferencias_cifradas"] = cifrar(bot.pref, clave)
        limite = (self.ahora - timedelta(days=14)).isoformat()
        self.estado["avisos"]["eventos"] = {k: v for k, v in ledger.items() if v.get("t", "") >= limite}
        resultado.update({"vinculado": bool(bot.pref.get("chat_id")), "enviados_ciclo": bot.enviados_ciclo,
                          "pausado": bot.pausado(self.ahora), "modo": bot.pref.get("modo")})
        resultado["errores"] += bot.errores
        return resultado

    # ------------------------------------------------------------------ ciclo
    def reprocesar_si_cambiaron_reglas(self) -> int:
        """Si cambió la versión de las reglas de clasificación, reclasifica lo guardado y rehace
        los acontecimientos (los avisos ya enviados se conservan en el registro de avisos)."""
        meta = self.estado.setdefault("meta", {})
        if meta.get("reglas_version") == REGLAS_VERSION:
            return 0
        arts = self.estado["articulos"]
        quedan = []
        for k, a in list(arts.items()):
            res = clasificar(a, self.conf)
            if res:
                a["conflictos"] = [r["id"] for r in res]
                a["clasificacion"] = res
                a.pop("armado_sin_conflicto", None)
                quedan.append(k)
            elif not a.get("armado_sin_conflicto"):
                del arts[k]
            else:
                a["conflictos"] = []
        self.estado["eventos"] = {}
        self.enriquecer(quedan)
        self.agrupar(quedan)
        meta["reglas_version"] = REGLAS_VERSION
        self.informe["advertencias"].append(
            f"Se aplicaron reglas de clasificación nuevas (v{REGLAS_VERSION}): se reclasificaron {len(quedan)} artículos.")
        return len(quedan)

    def ejecutar(self) -> dict:
        self._etapa("reglas", self.reprocesar_si_cambiaron_reglas)
        if not self.sin_red:
            # Modelos esenciales primero (inglés<->español), antes que los de otros idiomas.
            self._etapa("modelos", self.traductor.precargar, [("en", "es"), ("es", "en")])
        crudos = self.ingerir()
        claves = self._etapa("incorporar", self.incorporar, crudos) or []
        self._etapa("pivote_ingles", self.pivote_ingles, claves)
        self._etapa("pivote_es_en", self.pivote_es_en, claves)
        asignados = self._etapa("clasificar", self.clasificar, claves) or []
        self._etapa("traducir_espanol", self.traducir_espanol, asignados)
        vivos = [k for k in claves if k in self.estado["articulos"]]
        self._etapa("enriquecer", self.enriquecer, vivos)
        self._etapa("agrupar", self.agrupar, asignados)
        almacen.podar(self.estado, self.ahora)
        self.estado["traducciones"] = podar_cache(self.estado["traducciones"])
        vistas = self._etapa("vistas", vistas_eventos, self.estado, self.conf, self.ahora) or []
        candidatos = self._etapa("descubrir", detectar, self.conf, self.estado["articulos"],
                                 self.estado["gdelt"].get("descubrimiento", {}),
                                 self.estado["candidatos"], self.ahora) or {}
        self.estado["candidatos"] = candidatos
        # Traducir titulares de los candidatos (solo los que se publican).
        claves_cand = [k for c in candidatos.values() for k in c["articulos"] if k in self.estado["articulos"]]
        self._etapa("traducir_candidatos", self.traducir_espanol, claves_cand)
        info = self._informe(len(claves), len(asignados), vistas)
        tg = self._etapa("telegram", self.telegram, vistas, candidatos, info)
        info["telegram"] = tg or {"configurado": bool(os.environ.get("TELEGRAM_BOT_TOKEN")), "errores": ["falló la etapa"]}
        info["duracion_s"] = round(time.monotonic() - self.inicio, 1)
        publicado = self._etapa("publicar", publicar, self.estado, self.conf, vistas, candidatos, info,
                                self.dir_salida, self.ahora)
        info["publicado"] = publicado
        # Copia del informe en la rama "estado" (diagnóstico público, sin datos privados).
        self.estado["informe"] = {k: v for k, v in info.items() if k != "fuentes"} | {
            "fuentes_con_error": [f for f in info.get("fuentes", []) if f.get("estado") != "ok"]}
        self.estado["ciclos"].append({"t": self.ahora_iso, "ok": info["ciclo_ok"],
                                      "nuevos": len(claves), "asignados": len(asignados),
                                      "duracion_s": info["duracion_s"], "errores": len(info["errores"])})
        self.persistir()
        return info

    def _informe(self, n_nuevos: int, n_asignados: int, vistas: list[dict]) -> dict:
        inf = self.informe
        fuentes_cfg = {f["id"]: f for f in self.conf.fuentes["rss"]}
        lista = []
        for fid, f in fuentes_cfg.items():
            e = self.estado["fuentes"].get(fid, {})
            lista.append({"id": fid, "nombre": f["nombre"], "tipo": f.get("tipo"), "idioma": f.get("idioma"),
                          "pais": f.get("pais"), "propiedad": f.get("propiedad"), "licencia": f.get("licencia"),
                          "extracto": f.get("extracto", True), "estado": e.get("estado", "sin_datos"),
                          "ultimo_ok": e.get("ultimo_ok"), "error": e.get("error"), "items": e.get("items")})
        ok = sum(1 for x in lista if x["estado"] == "ok")
        err = sum(1 for x in lista if x["estado"] == "error")
        bloq = sum(1 for x in lista if x["estado"] == "bloqueada_robots")
        gd = inf.get("gdelt") or {}
        if self.sin_red:
            inf["advertencias"].append("Ejecución sin red: no se consultaron fuentes.")
        if err:
            inf["advertencias"].append(f"{err} de {len(lista)} feeds RSS fallaron en este ciclo.")
        ultimo = gd.get("ultimo_archivo")
        if ultimo:
            edad = self.ahora - datetime.strptime(ultimo, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            if edad > timedelta(minutes=75):
                inf["advertencias"].append(f"GDELT no publica archivos nuevos desde hace {int(edad.total_seconds() // 60)} min.")
        elif not self.sin_red:
            inf["advertencias"].append("Sin archivos de GDELT procesados todavía.")
        if gd.get("errores"):
            inf["advertencias"].append(f"GDELT: {len(gd['errores'])} error(es) de descarga.")
        if self.traductor.sin_modelo:
            inf["advertencias"].append("Sin modelo de traducción para: " + ", ".join(sorted(self.traductor.sin_modelo)))
        rss_ok = ok >= max(1, len(lista) // 2)
        gdelt_ok = (gd.get("archivos_ok", 0) > 0) or bool(ultimo and not gd.get("errores"))
        publicacion_ok = "vistas" in inf["etapas"] and inf["etapas"]["vistas"]["ok"]
        inf["ciclo_ok"] = bool(publicacion_ok and (rss_ok or gdelt_ok) and not self.sin_red)
        previos_ok = [c["t"] for c in self.estado.get("ciclos", []) if c.get("ok")]
        inf["ultimo_exito"] = self.ahora_iso if inf["ciclo_ok"] else (previos_ok[-1] if previos_ok else None)
        inf.update({
            "fuentes": lista,
            "resumen_fuentes": {"total": len(lista), "ok": ok, "error": err, "bloqueadas": bloq},
            "gdelt": {k: gd.get(k) for k in ("ultimo_archivo", "archivos_ok", "archivos_pendientes",
                                              "archivos_faltantes", "registros_gkg", "filas_invalidas")}
                     | {"errores": (gd.get("errores") or [])[:5],
                        "cita": self.conf.fuentes["gdelt"].get("cita")},
            "traduccion": {"motor": MOTOR, **self.traductor.contador,
                           "sin_modelo": sorted(self.traductor.sin_modelo),
                           "errores": self.traductor.errores[:8],
                           "modelos_instalados": self.traductor.modelos_instalados()},
            "articulos_nuevos": n_nuevos, "articulos_asignados": n_asignados,
            "eventos_72h": len(vistas),
            "conflictos_registro": len(self.conf.conflictos),
        })
        return inf
