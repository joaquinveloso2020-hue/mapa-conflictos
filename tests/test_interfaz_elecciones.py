"""Prueba de la interfaz con Chromium sin pantalla (Playwright) para las fichas de elecciones.

Arma la web con los datos FICTICIOS de tests/datos_prueba.py y reemplaza datos/elecciones.json por uno
generado con el procesamiento real (colector.elecciones) a partir de un calendario ficticio con la misma
sintaxis que Wikipedia. Las fechas se calculan desde hoy porque la página compara con la fecha del navegador.
Todo lo que no sea el servidor local se bloquea: no se consulta ningún servicio externo. Si Playwright no
está instalado, la prueba se omite (en GitHub Actions se instala en un paso aparte).
"""
from __future__ import annotations

import calendar
import functools
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from colector import elecciones as el  # noqa: E402
from colector.config import DIR_RECURSOS  # noqa: E402
from tests import datos_prueba  # noqa: E402

AHORA = datetime.now(timezone.utc)
FECHA = (AHORA + timedelta(days=20)).date()
ANIO = FECHA.year
MES = calendar.month_name[FECHA.month]

CALENDARIO_FICTICIO = f"""=={MES}==
* {FECHA.day} {MES}: [[Elections in Slovakia|Slovakia]], [[Next Slovak parliamentary election|Parliament]]<ref>{{{{cite web|url=https://prueba.example/eslovaquia-fecha}}}}</ref>
* {FECHA.day} {MES}: ''[[Politics of Transnistria|Transnistria]], [[{ANIO} Transnistrian presidential election|President]]''<ref>{{{{cite web|url=https://prueba.example/transnistria}}}}</ref>
==Unknown date==
* [[Elections in Slovakia|Slovakia]], [[Next Slovak parliamentary election|Parliament]]<ref>{{{{cite web|url=https://prueba.example/eslovaquia-sin-fecha}}}}</ref>
* [[Elections in Italy|Italy]], [[Next Italian general election|Chamber of Deputies and Senate]]
"""
ARTICULO_TR = f"https://en.wikipedia.org/wiki/{ANIO}_Transnistrian_presidential_election"
CALENDARIO_URL = f"https://en.wikipedia.org/wiki/{ANIO}_national_electoral_calendar"


class _Silencioso(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def sitio(tmp_path_factory):
    raiz = str(tmp_path_factory.mktemp("interfaz") / "web")
    datos_prueba.main(raiz)
    with open(os.path.join(DIR_RECURSOS, "paises.json"), encoding="utf-8") as f:
        paises = json.load(f)["paises"]
    cache = {"anios": {str(ANIO): {"titulo": f"{ANIO} national electoral calendar",
                                   "entradas": el.parsear(CALENDARIO_FICTICIO, ANIO)}},
             "ultimo_ok": AHORA.isoformat()}
    doc = el.documento(cache, paises, AHORA)
    assert doc["duplicados_omitidos"] == 1 and doc["sin_ubicar"] == ["Transnistria"]
    with open(os.path.join(raiz, "datos", "elecciones.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Silencioso, directory=raiz))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}/"
    servidor.shutdown()


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        try:
            # Sin WebGL el mapa no se inicia (la página lo avisa y el panel sigue funcionando). Así la prueba es
            # rápida y estable sin GPU, y además comprueba que la ficha no depende del mapa ni de sus polígonos.
            b = p.chromium.launch(args=["--disable-3d-apis"])
        except Exception as e:  # sin Chromium instalado
            pytest.skip(f"Chromium no disponible: {e}")
        yield b
        b.close()


def _abrir(navegador, url, movil=False):
    if movil:
        ctx = navegador.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    else:
        ctx = navegador.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errores = []
    pg.on("pageerror", lambda e: errores.append(str(e)))
    pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())
    pg.goto(url, wait_until="domcontentloaded")
    pg.click("#tab-elecciones")
    pg.wait_for_selector(".fila-eleccion")
    return ctx, pg, errores


def _hrefs(pg):
    return pg.eval_on_selector_all(".ficha .enlaces-ficha a", "as => as.map(a => a.href)")


def test_territorio_sin_mapa_abre_ficha_con_enlaces(sitio, navegador):
    ctx, pg, errores = _abrir(navegador, sitio)
    fila = pg.locator(".fila-eleccion", has_text="Transnistria")
    assert fila.count() == 1
    assert fila.get_attribute("role") == "button" and fila.get_attribute("tabindex") == "0"
    assert "sin ubicación en el mapa" in fila.inner_text()
    fila.click()
    assert pg.inner_text(".ficha h2") == "Transnistria"
    assert "Sin ubicación en el mapa" in pg.inner_text(".ficha")
    assert _hrefs(pg) == [ARTICULO_TR, "https://prueba.example/transnistria", CALENDARIO_URL]
    # "Volver" regresa a la lista; también se abre con el teclado.
    pg.click(".volver")
    pg.locator(".fila-eleccion", has_text="Transnistria").focus()
    pg.keyboard.press("Enter")
    assert pg.inner_text(".ficha h2") == "Transnistria"
    # La búsqueda también la encuentra aunque no esté en el mapa.
    pg.click(".volver")
    pg.fill("#buscar", "transn")
    op = pg.locator("#sugerencias li", has_text="Transnistria")
    assert "sin mapa" in op.inner_text()
    op.dispatch_event("mousedown")
    assert pg.inner_text(".ficha h2") == "Transnistria"
    assert not errores, errores
    ctx.close()


def test_eleccion_duplicada_aparece_una_vez_con_sus_fuentes(sitio, navegador):
    ctx, pg, errores = _abrir(navegador, sitio)
    filas = pg.locator(".fila-eleccion", has_text="Eslovaquia")
    assert filas.count() == 1
    assert "?" not in filas.first.locator(".fecha-el").inner_text()  # quedó la entrada con fecha
    filas.first.click()
    assert pg.inner_text(".ficha h2") == "Eslovaquia"
    assert _hrefs(pg) == ["https://en.wikipedia.org/wiki/Next_Slovak_parliamentary_election",
                          "https://prueba.example/eslovaquia-fecha", "https://prueba.example/eslovaquia-sin-fecha",
                          CALENDARIO_URL]
    # Desde la ficha de la elección se llega a la del país, y desde ahí se vuelve a la elección y al país.
    pg.click("text=Ver la ficha de Eslovaquia")
    assert pg.inner_text(".ficha .categoria-ficha") == "País"
    seccion = pg.locator(".ficha section", has_text="Próximas elecciones nacionales")
    assert seccion.locator(".fila-eleccion").count() == 1
    seccion.locator(".fila-eleccion").click()
    assert pg.inner_text(".ficha h2") == "Eslovaquia" and "Elección nacional" in pg.inner_text(".ficha .categoria-ficha")
    pg.click(".volver")
    assert pg.inner_text(".ficha .categoria-ficha") == "País"
    assert not errores, errores
    ctx.close()


def test_celular_abre_la_ficha_sin_mapa(sitio, navegador):
    ctx, pg, errores = _abrir(navegador, sitio, movil=True)
    pg.locator(".fila-eleccion", has_text="Transnistria").click()
    titulo = pg.locator(".ficha h2")
    assert titulo.inner_text() == "Transnistria"
    caja = titulo.bounding_box()
    assert caja and 0 <= caja["y"] < 844 - caja["height"]
    enlace = pg.locator(".ficha .enlaces-ficha a").first
    enlace.scroll_into_view_if_needed()
    assert enlace.is_visible() and enlace.get_attribute("href") == ARTICULO_TR
    # Con la hoja expandida: si la elección no tiene ubicación, la hoja sigue expandida (no hay nada que ver en
    # el mapa); si la tiene, baja a la mitad para que se vea el país.
    pg.click(".volver")
    for _ in range(3):
        if "expandido" in (pg.get_attribute("#panel", "class") or ""):
            break
        pg.click("#asa")
    assert "expandido" in pg.get_attribute("#panel", "class")
    pg.locator(".fila-eleccion", has_text="Transnistria").click()
    assert pg.inner_text(".ficha h2") == "Transnistria" and "expandido" in pg.get_attribute("#panel", "class")
    pg.click(".volver")
    pg.locator(".fila-eleccion", has_text="Eslovaquia").click()
    assert pg.inner_text(".ficha h2") == "Eslovaquia" and "expandido" not in pg.get_attribute("#panel", "class")
    assert not errores, errores
    ctx.close()
