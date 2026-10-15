"""Pruebas de varios ciclos completos con servicios simulados (datos ficticios, solo pruebas).

Comprueban: deduplicación al repetir ciclos, línea de base de Telegram, un aviso por novedad,
reintentos, fallos parciales de fuentes y su recuperación, y que la traducción fallida conserva
el original.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from colector.cifrado import descifrar, nueva_clave
from colector.ciclo import Ciclo
from colector import elecciones
from colector.fuente_gdelt import FLUJOS
from tests.fakes import Respuesta, SesionFalsa, fila_evento, fila_gkg, rfc822, rss, ts_franja, zip_texto

FEED_A = "https://prueba-a.example/rss"
FEED_B = "https://prueba-b.example/rss"
FEED_ROTO = "https://prueba-rota.example/rss"
GDELT = "http://data.gdeltproject.org/gdeltv2/"


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    clave = nueva_clave()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TOKEN-DE-PRUEBA")
    monkeypatch.setenv("TELEGRAM_CODIGO_VINCULACION", "codigo-prueba-42")
    monkeypatch.setenv("ESTADO_CLAVE", clave)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    sesion = SesionFalsa()
    return {"tmp": tmp_path, "sesion": sesion, "clave": clave}


def nuevo_ciclo(entorno, ahora, persistir_ok=True):
    tmp = entorno["tmp"]
    cmd = "true" if persistir_ok else "false"
    c = Ciclo(str(tmp / "estado"), str(tmp / "salida"), str(tmp / "modelos"),
              "https://ejemplo.github.io/mapa-conflictos/", persistir_cmd=cmd, ahora=ahora,
              sesion=entorno["sesion"])
    c.conf.fuentes["rss"] = [
        {"id": "prueba-a", "nombre": "Diario Prueba A", "url": FEED_A, "tipo": "medio", "pais": "GBR",
         "idioma": "en", "propiedad": "privada", "extracto": True},
        {"id": "prueba-b", "nombre": "Diario Prueba B", "url": FEED_B, "tipo": "medio", "pais": "ESP",
         "idioma": "es", "propiedad": "privada", "extracto": False},
        {"id": "prueba-rota", "nombre": "Fuente Rota", "url": FEED_ROTO, "tipo": "medio", "pais": "FRA",
         "idioma": "fr", "propiedad": "privada", "extracto": True},
    ]
    return c


def servir_feeds(sesion, ahora, extra_a=()):
    items_a = [
        {"titulo": "[PRUEBA] Sudan army says drone strike kills 12 in El Obeid", "url": "https://prueba-a.example/n1?utm_source=rss",
         "resumen": "[PRUEBA] Resumen ficticio del medio A.", "pub": rfc822(ahora - timedelta(hours=2))},
        {"titulo": "[PRUEBA] Recipe of the day", "url": "https://prueba-a.example/n2",
         "resumen": "nada", "pub": rfc822(ahora - timedelta(hours=1))},
        *extra_a,
    ]
    items_b = [
        {"titulo": "[PRUEBA] Ataque con drones deja 12 muertos en El Obeid, Sudán", "url": "https://prueba-b.example/x1",
         "resumen": "[PRUEBA] Resumen que NO debe publicarse (extracto desactivado).", "pub": rfc822(ahora - timedelta(hours=1, minutes=50))},
    ]
    sesion.rutas[FEED_A] = Respuesta(200, rss(items_a))
    sesion.rutas[FEED_B] = Respuesta(200, rss(items_b))
    sesion.fallos[FEED_ROTO] = 500


def servir_gdelt(sesion, ahora):
    ts = ts_franja(ahora, 1)
    lug = "4#El Obeid, North Kordofan, Sudan#SU#SU00##13.18#30.21#-123#100"
    gkg = fila_gkg("https://www.prueba-a.example/n1", "[PRUEBA] Sudan army says drone strike kills 12 in El Obeid",
                   "ARMEDCONFLICT;KILL", lug, ts, dominio="prueba-a.example")
    gkg2 = fila_gkg("https://prueba-c.example/z9", "[PRUEBA] El Obeid drone strike kills 12, Sudanese army says",
                    "ARMEDCONFLICT;KILL", lug, ts, dominio="prueba-c.example")
    ev = fila_evento("https://prueba-c.example/z9", "SU", 4, "El Obeid, Sudan", 13.18, 30.21)
    sesion.rutas[GDELT + FLUJOS["gkg"].format(ts=ts)] = Respuesta(200, zip_texto("a.csv", gkg + "\n" + gkg2 + "\n"))
    sesion.rutas[GDELT + FLUJOS["export"].format(ts=ts)] = Respuesta(200, zip_texto("b.csv", ev + "\n"))


def leer(entorno, nombre):
    with open(os.path.join(entorno["tmp"], "salida", nombre), encoding="utf-8") as f:
        return json.load(f)


def test_ciclos_completos(entorno):
    s = entorno["sesion"]
    t0 = datetime(2026, 10, 13, 12, 10, tzinfo=timezone.utc)
    servir_feeds(s, t0)
    servir_gdelt(s, t0)
    # El usuario vincula el bot ANTES del primer ciclo.
    s.telegram_actualizaciones.append({"update_id": 1, "message": {"chat": {"id": 999, "type": "private"},
                                                                    "text": "/vincular codigo-prueba-42"}})
    # Calendario electoral ficticio (misma sintaxis que Wikipedia).
    s.rutas[elecciones.url_api(2026)] = Respuesta(200, js={"parse": {"title": "2026 national electoral calendar", "revid": 7,
        "wikitext": "==November==\n* 8 November: [[Elections in Chile|Chile]], [[Prueba|President]]<ref>{{cite web|url=https://prueba.example/cl}}</ref>\n"}})
    info = nuevo_ciclo(entorno, t0).ejecutar()
    assert info["publicado"]["eventos"] >= 1
    # Elecciones: se publican aparte; la página del año siguiente (404 en la prueba) se informa como advertencia.
    el = leer(entorno, "elecciones.json")
    assert [(x["pais"], x["fecha"], x["cargos"]) for x in el["elecciones"]] == [("CHL", "2026-11-08", "Presidente")]
    assert el["fuente"]["licencia"] == "CC BY-SA 4.0" and el["elecciones"][0]["fuentes"] == ["https://prueba.example/cl"]
    assert info["elecciones"]["proximas"] == 1 and info["elecciones"]["errores"]
    ev = leer(entorno, "eventos.json")
    arts = ev["articulos"]
    # Deduplicación por URL canónica: n1 llegó por RSS y por GDELT y es un solo artículo.
    urls_n1 = [a for a in arts.values() if "prueba-a.example/n1" in a["url"]]
    assert len(urls_n1) == 1
    # La receta no corresponde a ningún conflicto.
    assert not any("Recipe" in a["titulo"] for a in arts.values())
    # El extracto de una fuente con extracto=false no se publica.
    b = [a for a in arts.values() if "prueba-b.example" in a["url"]][0]
    assert "resumen" not in b and "resumen_es" not in b
    # Las tres coberturas del mismo hecho forman un acontecimiento con varias fuentes.
    sudan = [e for e in ev["eventos"] if e["conflicto"] == "sudan"]
    assert len(sudan) == 1 and sudan[0]["n_articulos"] == 3
    assert sudan[0]["fuentes_independientes"] == 3 and sudan[0]["estado"] == "varias_fuentes"
    assert sudan[0]["lugar"]["precision"] == "ciudad"
    # Fechas separadas: publicación (RSS) y detección.
    a1 = urls_n1[0]
    assert a1["pub"] != a1["detectado"]
    # Sin modelos de traducción: se conserva el original y se indica.
    assert a1.get("traduccion", {}).get("estado") in ("sin_modelo", "fallo")
    # Telegram: vinculado; la carga inicial NO se envía como novedad.
    assert len(s.telegram_enviados) == 1 and "vinculado" in s.telegram_enviados[0]["text"].lower()
    estado = leer(entorno, "estado.json")
    assert estado["telegram"]["vinculado"] and "999" not in json.dumps(estado)
    assert any(f["id"] == "prueba-rota" and f["estado"] == "error" for f in estado["fuentes"])
    assert estado["ciclo_ok"]

    # Segundo ciclo con los mismos datos: no duplica artículos ni envía avisos.
    t1 = t0 + timedelta(minutes=15)
    info2 = nuevo_ciclo(entorno, t1).ejecutar()
    ev2 = leer(entorno, "eventos.json")
    assert len(ev2["articulos"]) == len(arts)
    assert len([e for e in ev2["eventos"] if e["conflicto"] == "sudan"]) == 1
    assert len(s.telegram_enviados) == 1
    assert info2["articulos_nuevos"] == 0

    # Tercer ciclo: aparece una novedad nueva cubierta por dos medios -> un aviso.
    t2 = t1 + timedelta(minutes=15)
    nuevo = {"titulo": "[PRUEBA] Houthi missile attack hits Jizan, Saudi Arabia says",
             "url": "https://prueba-a.example/n3", "resumen": "[PRUEBA] Texto ficticio.", "pub": rfc822(t2 - timedelta(minutes=5))}
    servir_feeds(s, t2, extra_a=[nuevo])
    ts = ts_franja(t2, 0)
    lug = "4#Jizan, Jizan, Saudi Arabia#SA#SA00##16.89#42.55#-1#10"
    s.rutas[GDELT + FLUJOS["gkg"].format(ts=ts)] = Respuesta(200, zip_texto("c.csv", fila_gkg(
        "https://prueba-d.example/h1", "[PRUEBA] Houthi missiles strike Jizan in Saudi Arabia, officials say",
        "ARMEDCONFLICT", lug, ts, dominio="prueba-d.example") + "\n"))
    s.fallos.pop(FEED_ROTO)  # la fuente rota se recupera
    s.rutas[FEED_ROTO] = Respuesta(200, rss([]))
    nuevo_ciclo(entorno, t2).ejecutar()
    assert len(s.telegram_enviados) == 2
    texto = s.telegram_enviados[1]["text"]
    assert "Yemen" in texto and "original" in texto and "Según el medio" in texto
    assert "Traducción no disponible" in texto  # sin modelos en la prueba: se indica y se muestra el original
    assert s.telegram_enviados[1]["link_preview_options"]["is_disabled"] is True
    estado3 = leer(entorno, "estado.json")
    assert all(f["estado"] == "ok" for f in estado3["fuentes"])

    # Cuarto ciclo idéntico: no se repite el aviso.
    t3 = t2 + timedelta(minutes=15)
    nuevo_ciclo(entorno, t3).ejecutar()
    assert len(s.telegram_enviados) == 2


def test_pausa_y_comandos(entorno):
    s = entorno["sesion"]
    t0 = datetime(2026, 10, 13, 12, 10, tzinfo=timezone.utc)
    s.telegram_actualizaciones += [
        {"update_id": 1, "message": {"chat": {"id": 7, "type": "private"}, "text": "/vincular codigo-prueba-42"}},
        {"update_id": 2, "message": {"chat": {"id": 8, "type": "private"}, "text": "/estado"}},  # otro chat: ignorado
        {"update_id": 3, "message": {"chat": {"id": 7, "type": "private"}, "text": "/paises Sudán UA"}},
        {"update_id": 4, "message": {"chat": {"id": 7, "type": "private"}, "text": "/pausar 2"}},
    ]
    servir_feeds(s, t0)
    nuevo_ciclo(entorno, t0).ejecutar()
    destinos = {m["chat_id"] for m in s.telegram_enviados}
    assert destinos == {7}
    pref = descifrar(open(entorno["tmp"] / "estado" / "preferencias.enc").read(), entorno["clave"])
    assert pref["paises"] == ["SDN", "UKR"] and pref["modo"] == "filtrado" and pref["pausado_hasta"]
    # El archivo cifrado no contiene el chat en claro.
    assert "\"chat_id\"" not in open(entorno["tmp"] / "estado" / "preferencias.enc").read()
    # Durante la pausa, una novedad nueva NO se envía, ni tampoco al reanudar.
    t1 = t0 + timedelta(minutes=30)
    extra = {"titulo": "[PRUEBA] RSF attack kills 9 in Darfur", "url": "https://prueba-a.example/n7",
             "resumen": "x", "pub": rfc822(t1 - timedelta(minutes=5))}
    servir_feeds(s, t1, extra_a=[extra])
    previos = len(s.telegram_enviados)
    nuevo_ciclo(entorno, t1).ejecutar()
    assert len(s.telegram_enviados) == previos
    ledger = json.load(open(entorno["tmp"] / "estado" / "avisos.json"))["eventos"]
    assert any(v["estado"] == "omitido_pausa" for v in ledger.values())


def test_sin_guardar_estado_no_envia(entorno):
    s = entorno["sesion"]
    t0 = datetime(2026, 10, 13, 12, 10, tzinfo=timezone.utc)
    s.telegram_actualizaciones.append({"update_id": 1, "message": {"chat": {"id": 5, "type": "private"},
                                                                    "text": "/vincular codigo-prueba-42"}})
    nuevo_ciclo(entorno, t0).ejecutar()  # vincula (sin novedades previas)
    t1 = t0 + timedelta(minutes=15)
    servir_feeds(s, t1)
    s.rutas[FEED_B] = Respuesta(200, rss([{"titulo": "[PRUEBA] Combates en El Obeid, Sudán, dejan 12 muertos",
                                           "url": "https://prueba-b.example/x5", "resumen": "", "pub": rfc822(t1)}]))
    previos = len(s.telegram_enviados)
    nuevo_ciclo(entorno, t1, persistir_ok=False).ejecutar()
    assert len(s.telegram_enviados) == previos  # sin estado guardado, no se envía
    # Con el estado funcionando, el próximo ciclo sí envía y una sola vez.
    t2 = t1 + timedelta(minutes=15)
    nuevo_ciclo(entorno, t2).ejecutar()
    assert len(s.telegram_enviados) == previos + 1
    nuevo_ciclo(entorno, t2 + timedelta(minutes=15)).ejecutar()
    assert len(s.telegram_enviados) == previos + 1


def test_fallo_de_envio_se_reintenta_y_red_incierta_no_duplica(entorno):
    s = entorno["sesion"]
    t0 = datetime(2026, 10, 13, 12, 10, tzinfo=timezone.utc)
    s.telegram_actualizaciones.append({"update_id": 1, "message": {"chat": {"id": 5, "type": "private"},
                                                                    "text": "/vincular codigo-prueba-42"}})
    nuevo_ciclo(entorno, t0).ejecutar()
    t1 = t0 + timedelta(minutes=15)
    servir_feeds(s, t1)
    s.telegram_falla_envio = 500
    nuevo_ciclo(entorno, t1).ejecutar()
    previos = len(s.telegram_enviados)
    s.telegram_falla_envio = None
    nuevo_ciclo(entorno, t1 + timedelta(minutes=15)).ejecutar()  # reintento de lo fallido
    assert len(s.telegram_enviados) == previos + 1
    # Caída de red durante el envío: estado incierto -> no se reenvía (evita duplicados).
    t3 = t1 + timedelta(minutes=30)
    extra = {"titulo": "[PRUEBA] Hezbollah rockets hit northern Israel, army says",
             "url": "https://prueba-a.example/n9", "resumen": "x", "pub": rfc822(t3)}
    servir_feeds(s, t3, extra_a=[extra])
    s.rutas[FEED_B] = Respuesta(200, rss([{"titulo": "[PRUEBA] Cohetes de Hezbolá impactan en el norte de Israel",
                                           "url": "https://prueba-b.example/x9", "resumen": "", "pub": rfc822(t3)}]))
    s.telegram_falla_envio = "red"
    nuevo_ciclo(entorno, t3).ejecutar()
    s.telegram_falla_envio = None
    antes = len(s.telegram_enviados)
    nuevo_ciclo(entorno, t3 + timedelta(minutes=15)).ejecutar()
    assert len(s.telegram_enviados) == antes


def test_traduccion_simulada_y_resumen_atribuido(entorno, monkeypatch):
    """Con un motor de traducción simulado, el título y el extracto se publican en español."""
    from colector import traduccion
    monkeypatch.setattr(traduccion.Traductor, "_indice_paquetes", lambda self: {("en", "es"): {}, ("fr", "en"): {}})
    monkeypatch.setattr(traduccion.Traductor, "_directo",
                        lambda self, textos, o, d: [f"[{o}->{d}] {t}" for t in textos])
    monkeypatch.setattr(traduccion.Traductor, "_importar", lambda self: True)
    s = entorno["sesion"]
    t0 = datetime(2026, 10, 13, 12, 10, tzinfo=timezone.utc)
    servir_feeds(s, t0)
    nuevo_ciclo(entorno, t0).ejecutar()
    arts = leer(entorno, "eventos.json")["articulos"]
    a = [x for x in arts.values() if "/n1" in x["url"]][0]
    assert a["titulo_es"].startswith("[en->es]") and a["resumen_es"].startswith("[en->es]")
    assert a["traduccion"]["estado"] == "ok" and a["titulo"].startswith("[PRUEBA]")


def test_fecha_de_publicacion_posterior_a_la_deteccion_se_descarta(entorno):
    s = entorno["sesion"]
    t0 = datetime(2026, 10, 13, 12, 10, tzinfo=timezone.utc)
    s.rutas[FEED_A] = Respuesta(200, rss([{"titulo": "[PRUEBA] RSF drone strike kills 5 in El Fasher",
                                           "url": "https://prueba-a.example/f1", "resumen": "x",
                                           "pub": rfc822(t0 + timedelta(minutes=90))}]))
    nuevo_ciclo(entorno, t0).ejecutar()
    a = [x for x in leer(entorno, "eventos.json")["articulos"].values() if x["url"].endswith("/f1")][0]
    assert "pub" not in a and a["pub_descartada"] == "posterior a la detección"
