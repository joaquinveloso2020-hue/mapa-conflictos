"""Bot de Telegram: comandos del chat privado vinculado y resumen de novedades por ciclo.

Garantías:
  - Solo atiende al chat privado vinculado (vinculación con un código secreto de un solo uso).
  - Nunca envía como "nuevas" las novedades anteriores a la activación (línea de base).
  - Cada acontecimiento se avisa como máximo una vez: se registra "enviando" y se guarda el estado
    ANTES de enviar; si el proceso se corta a mitad de camino, no se reenvía (al menos no duplica).
  - Límites gratuitos: ≤ 1 mensaje por segundo, ≤ 3 mensajes de resumen por ciclo, sin difusiones
    pagas (no se usa allow_paid_broadcast ni ningún método con Telegram Stars).
"""
from __future__ import annotations

import html
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from .texto import normalizar

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{metodo}"
LIMITE_TEXTO = 3900
MAX_MENSAJES_CICLO = 3
ETIQUETA_ESTADO = {
    "preliminar": "Reporte preliminar",
    "varias_fuentes": "Varias fuentes independientes",
    "declaracion_parte": "Declaración de parte",
}
PREFERENCIAS_INICIALES = {
    "chat_id": None, "vinculado_en": None, "activado_en": None,
    "pausado_hasta": None, "modo": "mundial", "paises": [], "conflictos": [],
    "min_fuentes_mundial": 2, "min_fuentes_filtrado": 1, "max_items": 10,
}


class ErrorTelegram(Exception):
    """definitivo: el error no se resolverá reintentando; con_respuesta: Telegram respondió (el
    mensaje NO se entregó). Sin respuesta (error de red) el resultado es incierto."""

    def __init__(self, mensaje: str, definitivo: bool, con_respuesta: bool = True):
        super().__init__(mensaje)
        self.definitivo = definitivo
        self.con_respuesta = con_respuesta


def esc(t) -> str:
    return html.escape(str(t or ""), quote=False)


class Bot:
    def __init__(self, token: str, codigo_vinculacion: str | None, sesion: requests.Session,
                 preferencias: dict, estado_tg: dict, conf, url_sitio: str, zona: str):
        self.token = token
        self.codigo = (codigo_vinculacion or "").strip()
        self.sesion = sesion
        self.pref = {**PREFERENCIAS_INICIALES, **(preferencias or {})}
        self.estado = estado_tg
        self.conf = conf
        self.url_sitio = url_sitio
        self.zona = ZoneInfo(zona)
        self._ultimo_envio = 0.0
        self.enviados_ciclo = 0
        self.errores: list[str] = []

    # ------------------------------------------------------------------ API
    def _limpiar(self, texto: str) -> str:
        return texto.replace(self.token, "***") if self.token else texto

    def api(self, metodo: str, datos: dict) -> dict:
        espera = 1.05 - (time.monotonic() - self._ultimo_envio)
        if metodo == "sendMessage" and espera > 0:
            time.sleep(espera)
        for intento in range(3):
            try:
                r = self.sesion.post(API.format(token=self.token, metodo=metodo), json=datos, timeout=30)
            except requests.RequestException as e:
                raise ErrorTelegram(self._limpiar(f"red: {type(e).__name__}"), definitivo=False,
                                    con_respuesta=False) from None
            if metodo == "sendMessage":
                self._ultimo_envio = time.monotonic()
            try:
                cuerpo = r.json()
            except ValueError:
                cuerpo = {"ok": False, "description": f"HTTP {r.status_code}"}
            if cuerpo.get("ok"):
                return cuerpo.get("result")
            if r.status_code == 429:
                espera = int((cuerpo.get("parameters") or {}).get("retry_after", 5))
                if espera > 60:
                    raise ErrorTelegram("límite de Telegram (429), se reintentará en el próximo ciclo", False)
                time.sleep(espera + 1)
                continue
            definitivo = r.status_code in (400, 401, 403, 404)
            raise ErrorTelegram(self._limpiar(f"{r.status_code}: {cuerpo.get('description', '')[:120]}"),
                                definitivo)
        raise ErrorTelegram("límite de Telegram persistente", False)

    def enviar(self, texto: str, chat_id=None) -> None:
        self.api("sendMessage", {
            "chat_id": chat_id or self.pref["chat_id"], "text": texto, "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        })
        self.enviados_ciclo += 1

    # ------------------------------------------------------------ comandos
    def procesar_comandos(self, ahora: datetime, info_estado: dict) -> int:
        offset = self.estado.get("offset")
        datos = {"timeout": 0, "allowed_updates": ["message"], "limit": 100}
        if offset:
            datos["offset"] = offset
        try:
            actualizaciones = self.api("getUpdates", datos) or []
        except ErrorTelegram as e:
            self.errores.append(f"getUpdates: {e}")
            return 0
        procesados = 0
        for u in actualizaciones:
            self.estado["offset"] = u["update_id"] + 1
            m = u.get("message") or {}
            chat = m.get("chat") or {}
            texto = (m.get("text") or "").strip()
            if not texto.startswith("/"):
                continue
            try:
                if not self.pref.get("chat_id"):
                    self._vincular(chat, texto, ahora)
                elif chat.get("id") == self.pref["chat_id"]:
                    self._comando(texto, ahora, info_estado)
                procesados += 1
            except ErrorTelegram as e:
                self.errores.append(f"respuesta a comando: {e}")
        return procesados

    def _vincular(self, chat: dict, texto: str, ahora: datetime) -> None:
        partes = texto.split()
        if chat.get("type") != "private" or len(partes) < 2 or not self.codigo:
            return
        if partes[0].split("@")[0] not in ("/vincular", "/start") or partes[1] != self.codigo:
            return
        self.pref.update({"chat_id": chat["id"], "vinculado_en": ahora.isoformat(),
                          "activado_en": ahora.isoformat()})
        self.enviar(
            "<b>Bot vinculado.</b> Desde ahora recibirás un resumen de novedades mundiales en cada ciclo "
            "(cada ~15 minutos) solo cuando haya información nueva. Las noticias anteriores a este momento "
            "no se envían.\n\nEscribí /ayuda para ver los comandos. Los comandos se aplican en el próximo "
            "ciclo de actualización (hasta ~15 minutos).", chat_id=chat["id"])

    def _resolver_pais(self, token: str) -> str | None:
        t = token.strip().upper()
        for iso3, p in self.conf.paises.items():
            if t == iso3 or (p.get("iso2") and t == p["iso2"]):
                return iso3
        n = normalizar(token)
        for iso3, p in self.conf.paises.items():
            nombres = [p["nombre"]] + [v for k, v in p["nombres"].items() if k in ("es", "en") and v]
            if n in {normalizar(x) for x in nombres}:
                return iso3
        return None

    def _resolver_conflicto(self, token: str) -> str | None:
        t = token.strip().lower()
        return t if self.conf.conflicto(t) else None

    def _comando(self, texto: str, ahora: datetime, info_estado: dict) -> None:
        partes = texto.split()
        cmd = partes[0].split("@")[0].lower()
        args = partes[1:]
        p = self.pref
        if cmd in ("/start", "/ayuda", "/help"):
            self.enviar(AYUDA)
        elif cmd == "/estado":
            self.enviar(self._texto_estado(ahora, info_estado))
        elif cmd == "/pausar":
            if args and args[0].replace(",", ".").replace(".", "", 1).isdigit():
                horas = float(args[0].replace(",", "."))
                p["pausado_hasta"] = (ahora + timedelta(hours=horas)).isoformat()
                self.enviar(f"Alertas pausadas por {horas:g} h. Lo que ocurra en ese lapso no se enviará después.")
            else:
                p["pausado_hasta"] = "indefinido"
                self.enviar("Alertas pausadas hasta que escribas /reanudar.")
        elif cmd == "/reanudar":
            p["pausado_hasta"] = None
            self.enviar("Alertas reanudadas. Recibirás solo novedades detectadas desde ahora.")
            p["activado_en"] = ahora.isoformat()
        elif cmd == "/mundial":
            p.update({"modo": "mundial", "paises": [], "conflictos": []})
            p["activado_en"] = max(p.get("activado_en") or "", ahora.isoformat())
            self.enviar("Modo resumen mundial activado.")
        elif cmd in ("/paises", "/conflictos", "/agregar", "/quitar"):
            self._filtros(cmd, args, ahora)
        elif cmd == "/lista":
            lineas = [f"<code>{esc(c.id)}</code> — {esc(c.nombre)}" for c in self.conf.conflictos if c.estado == "activo"]
            self._enviar_largo("<b>Conflictos del registro</b>\n" + "\n".join(lineas))
        elif cmd == "/fuentes":
            if args and args[0].isdigit() and 1 <= int(args[0]) <= 5:
                clave = "min_fuentes_mundial" if p["modo"] == "mundial" else "min_fuentes_filtrado"
                p[clave] = int(args[0])
                self.enviar(f"Mínimo de fuentes independientes: {args[0]}.")
            else:
                self.enviar("Usá /fuentes N con N entre 1 y 5.")
        elif cmd == "/desvincular":
            self.enviar("Chat desvinculado. No recibirás más avisos hasta vincularlo de nuevo.")
            self.pref.update({**PREFERENCIAS_INICIALES})
        else:
            self.enviar("Comando no reconocido. Escribí /ayuda.")

    def _filtros(self, cmd: str, args: list[str], ahora: datetime) -> None:
        p = self.pref
        if not args:
            self.enviar("Indicá países (códigos o nombres) o ids de conflicto. Ej.: /paises AR UA SD")
            return
        paises, conflictos, desconocidos = [], [], []
        for a in " ".join(args).replace(",", " ").split():
            iso = self._resolver_pais(a)
            cid = self._resolver_conflicto(a)
            if cid:
                conflictos.append(cid)
            elif iso:
                paises.append(iso)
            else:
                desconocidos.append(a)
        if cmd == "/paises":
            p["paises"] = sorted(set(paises))
            if conflictos:
                p["conflictos"] = sorted(set(conflictos))
        elif cmd == "/conflictos":
            p["conflictos"] = sorted(set(conflictos))
            if paises:
                p["paises"] = sorted(set(paises))
        elif cmd == "/agregar":
            p["paises"] = sorted(set(p["paises"]) | set(paises))
            p["conflictos"] = sorted(set(p["conflictos"]) | set(conflictos))
        else:
            p["paises"] = sorted(set(p["paises"]) - set(paises))
            p["conflictos"] = sorted(set(p["conflictos"]) - set(conflictos))
        p["modo"] = "filtrado" if (p["paises"] or p["conflictos"]) else "mundial"
        p["activado_en"] = max(p.get("activado_en") or "", ahora.isoformat())
        texto = f"Modo: <b>{'filtrado' if p['modo'] == 'filtrado' else 'mundial'}</b>\n"
        if p["paises"]:
            texto += "Países: " + ", ".join(esc(self.conf.paises.get(x, {}).get("nombre", x)) for x in p["paises"]) + "\n"
        if p["conflictos"]:
            texto += "Conflictos: " + ", ".join(esc(x) for x in p["conflictos"]) + "\n"
        if desconocidos:
            texto += "No reconocidos: " + esc(", ".join(desconocidos)) + " (usá /lista para ver ids)"
        self.enviar(texto)

    def _texto_estado(self, ahora: datetime, info: dict) -> str:
        p = self.pref
        pausa = "no"
        if p.get("pausado_hasta") == "indefinido":
            pausa = "sí (hasta /reanudar)"
        elif p.get("pausado_hasta") and p["pausado_hasta"] > ahora.isoformat():
            pausa = "hasta " + self.hora(p["pausado_hasta"])
        lineas = [
            "<b>Estado</b>",
            f"Última actualización exitosa: {esc(self.hora(info.get('ultimo_exito')) if info.get('ultimo_exito') else 'sin datos')}",
            f"Modo: {esc(p['modo'])}",
            f"Pausa: {esc(pausa)}",
            f"Mínimo de fuentes: {p['min_fuentes_mundial'] if p['modo'] == 'mundial' else p['min_fuentes_filtrado']}",
        ]
        if p["paises"]:
            lineas.append("Países: " + esc(", ".join(p["paises"])))
        if p["conflictos"]:
            lineas.append("Conflictos: " + esc(", ".join(p["conflictos"])))
        if info.get("advertencias"):
            lineas.append("Advertencias: " + esc("; ".join(info["advertencias"][:3])))
        return "\n".join(lineas)

    def _enviar_largo(self, texto: str) -> None:
        bloque = ""
        for linea in texto.split("\n"):
            if len(bloque) + len(linea) + 1 > LIMITE_TEXTO:
                self.enviar(bloque)
                bloque = ""
            bloque += linea + "\n"
        if bloque.strip():
            self.enviar(bloque)

    def hora(self, iso: str | None) -> str:
        if not iso:
            return "—"
        try:
            return datetime.fromisoformat(iso).astimezone(self.zona).strftime("%d/%m %H:%M")
        except ValueError:
            return iso

    # ------------------------------------------------------------ avisos
    def pausado(self, ahora: datetime) -> bool:
        h = self.pref.get("pausado_hasta")
        if not h:
            return False
        return h == "indefinido" or h > ahora.isoformat()

    def seleccionar(self, eventos: list[dict], conflictos: dict, ledger: dict, ahora: datetime) -> list[dict]:
        p = self.pref
        activado = p.get("activado_en")
        if not p.get("chat_id") or not activado:
            return []
        limite_reciente = (ahora - timedelta(hours=24)).isoformat()
        minimo = p["min_fuentes_mundial"] if p["modo"] == "mundial" else p["min_fuentes_filtrado"]
        elegidos = []
        for ev in eventos:
            previo = ledger.get(ev["id"])
            if previo and previo.get("estado") != "fallido":
                continue
            if previo and previo.get("intentos", 0) >= 3:
                continue
            if (ev.get("creado") or "") <= activado or (ev.get("referencia") or "") < limite_reciente:
                continue
            if p["modo"] == "filtrado":
                c = conflictos.get(ev["conflicto"]) or {}
                paises_ev = set(c.get("paises_escenario", [])) | {(ev.get("lugar") or {}).get("pais")}
                if ev["conflicto"] not in p["conflictos"] and not (paises_ev & set(p["paises"])):
                    continue
            if ev["estado"] == "declaracion_parte":
                if minimo > 1:
                    continue
            elif ev["fuentes_independientes"] < minimo:
                continue
            elegidos.append(ev)
        elegidos.sort(key=lambda e: e.get("referencia") or "", reverse=True)
        elegidos.sort(key=lambda e: e["fuentes_independientes"], reverse=True)
        return elegidos

    def formatear(self, ev: dict, conflictos: dict, articulos: dict) -> str:
        c = conflictos.get(ev["conflicto"]) or {}
        art = articulos.get(ev.get("articulo_principal")) or {}
        etiqueta = ETIQUETA_ESTADO.get(ev["estado"], ev["estado"])
        if ev["estado"] == "declaracion_parte":
            etiqueta = "Declaración de " + ", ".join(ev.get("partes_con_fuente") or {}) or etiqueta
        elif ev["estado"] == "varias_fuentes":
            etiqueta = f"{ev['fuentes_independientes']} fuentes independientes"
        extras = []
        if ev.get("contrapuestas"):
            extras.append("versiones contrapuestas")
        if ev.get("atribuida"):
            extras.append("afirmación atribuida")
        lineas = [f"<b>{esc(c.get('nombre', ev['conflicto']))}</b> · <i>{esc(etiqueta)}</i>"
                  + (f" · {esc(', '.join(extras))}" if extras else "")]
        lineas.append(esc(ev.get("titulo") or art.get("titulo")))
        resumen = art.get("resumen_es") or art.get("resumen") or ""
        if resumen:
            lineas.append("Según el medio: " + esc(resumen[:220]) + ("…" if len(resumen) > 220 else ""))
        if art.get("traduccion", {}).get("estado") not in (None, "original", "ok") or \
                (art.get("resumen") and not art.get("resumen_es") and art.get("idioma") != "es"):
            lineas.append("<i>(Traducción no disponible: se muestra el texto original)</i>")
        fuente = art.get("fuente_nombre") or art.get("dominio") or "fuente"
        if art.get("pub"):
            fecha = "publicado " + self.hora(art["pub"])
        else:
            fecha = "detectado " + self.hora(art.get("detectado")) + " (sin fecha de publicación)"
        mas = ev["n_articulos"] - 1
        lineas.append(f"{esc(fuente)} · {esc(fecha)} · <a href=\"{esc(art.get('url', ''))}\">original</a>"
                      + (f" · +{mas} artículo(s)" if mas > 0 else ""))
        return "\n".join(lineas)

    def construir_mensajes(self, elegidos: list[dict], conflictos: dict, articulos: dict,
                           candidatos_nuevos: list[dict], ahora: datetime) -> tuple[list[str], list[str]]:
        """Devuelve (mensajes, ids_incluidos)."""
        tope = self.pref.get("max_items", 10)
        incluidos = elegidos[:tope]
        resto = len(elegidos) - len(incluidos)
        cabecera = f"<b>Novedades · ciclo {self.hora(ahora.isoformat())}</b> (hora Argentina)"
        bloques = [self.formatear(ev, conflictos, articulos) for ev in incluidos]
        for cand in candidatos_nuevos[:3]:
            bloques.append(f"<b>Situación detectada automáticamente (sin verificar)</b>\n{esc(cand['nombre'])}\n"
                           f"<i>{esc(cand['reglas'])}</i>")
        pie = ""
        if resto > 0:
            pie += f"\nY {resto} novedad(es) más en el mapa."
        pie += f"\n<a href=\"{esc(self.url_sitio)}\">Abrir el mapa</a>"
        mensajes, actual, ids = [], cabecera, []
        for ev, bloque in zip(incluidos + [None] * len(candidatos_nuevos[:3]), bloques):
            if len(actual) + len(bloque) + 2 > LIMITE_TEXTO:
                mensajes.append(actual)
                if len(mensajes) >= MAX_MENSAJES_CICLO:
                    actual = None
                    break
                actual = "<b>(continuación)</b>"
            actual += "\n\n" + bloque
            if ev:
                ids.append(ev["id"])
        if actual is not None:
            if len(actual) + len(pie) > LIMITE_TEXTO:
                mensajes.append(actual)
                actual = pie.strip()
            else:
                actual += "\n" + pie
            mensajes.append(actual)
        return mensajes[:MAX_MENSAJES_CICLO], ids


AYUDA = """<b>Comandos</b>
/estado — configuración y última actualización
/pausar [horas] — pausar avisos (sin número: hasta /reanudar)
/reanudar — volver a recibir avisos
/mundial — resumen mundial (configuración inicial)
/paises AR UA SD — solo esos países (códigos o nombres)
/conflictos sudan ucrania-rusia — solo esos conflictos
/agregar … y /quitar … — sumar o quitar países/conflictos
/lista — ids de los conflictos
/fuentes N — mínimo de fuentes independientes (1–5)
/desvincular — dejar de recibir avisos

Los comandos se aplican en el próximo ciclo (hasta ~15 min). Las etiquetas indican si un aviso es un <i>reporte preliminar</i>, una <i>declaración de parte</i> o está cubierto por <i>varias fuentes independientes</i>."""
