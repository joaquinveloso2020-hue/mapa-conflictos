/* Mapa de conflictos — interfaz (JavaScript sin dependencias aparte de MapLibre GL). */
(function () {
  'use strict';

  // ------------------------------------------------------------------ utilidades
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const norm = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
  const rtf = new Intl.RelativeTimeFormat('es', { numeric: 'auto' });
  const dtf = new Intl.DateTimeFormat('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  const df = new Intl.DateTimeFormat('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const IDIOMAS = { es: 'español', en: 'inglés', fr: 'francés', ar: 'árabe', ru: 'ruso', uk: 'ucraniano', zh: 'chino', fa: 'persa',
    tr: 'turco', hi: 'hindi', ur: 'urdu', pt: 'portugués', de: 'alemán', ja: 'japonés', ko: 'coreano', he: 'hebreo', it: 'italiano',
    sw: 'suajili', pl: 'polaco', id: 'indonesio', nl: 'neerlandés', vi: 'vietnamita', th: 'tailandés', bn: 'bengalí' };
  const PRECISION = { ciudad: 'ciudad', provincia: 'provincia/región', pais: 'solo país', desconocida: 'sin ubicación' };
  const METODO = {
    gdelt_evento: 'Lugar del hecho según la codificación automática de eventos de GDELT',
    titular: 'Lugar nombrado en el titular',
    pais_mencionado: 'Solo se conoce el país (mencionado en el texto)',
    pais_del_conflicto: 'Ubicación no especificada: se asigna al país del conflicto',
    pais: 'Solo se conoce el país',
  };

  function relativo(iso) {
    if (!iso) return '';
    const s = (new Date(iso).getTime() - Date.now()) / 1000;
    if (s > 300) return 'el ' + absoluto(iso); // fecha futura: no se presenta como relativa
    const a = Math.abs(s);
    if (a < 60) return 'hace instantes';
    if (a < 3600) return rtf.format(Math.round(s / 60), 'minute');
    if (a < 86400) return rtf.format(Math.round(s / 3600), 'hour');
    return rtf.format(Math.round(s / 86400), 'day');
  }
  const absoluto = (iso) => (iso ? dtf.format(new Date(iso)) : '—');
  const fechaCorta = (iso) => (iso ? df.format(new Date(iso.length === 10 ? iso + 'T12:00:00Z' : iso)) : '—');
  function el(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }

  // ------------------------------------------------------------------ estado
  const E = {
    datos: { estado: null, conflictos: null, eventos: null, candidatos: null },
    geo: { paises: null, zonas: null },
    idx: {},
    horas: 24,
    categorias: new Set(),
    capas: { paises: true, eventos: true, zonas: true, candidatos: false, base: false },
    pestana: 'novedades',
    vista: null, // {tipo:'conflicto'|'pais'|'candidato', id}
    eventoAbierto: null,
    limiteLista: 40,
    orden: 'recientes',     // 'recientes' | 'fuentes'
    soloVarias: false,      // ocultar acontecimientos de un solo origen
    mapa: null,
    mapaListo: false,
    generado: null,
  };

  const colorCat = (c) => (E.datos.conflictos && E.datos.conflictos.categorias[c] ? E.datos.conflictos.categorias[c].color : '#888');
  const nombreCat = (c) => (E.datos.conflictos && E.datos.conflictos.categorias[c] ? E.datos.conflictos.categorias[c].nombre : c);
  const nombrePais = (iso) => (E.datos.conflictos && E.datos.conflictos.paises[iso]) || iso;

  // ------------------------------------------------------------------ datos
  async function cargarJSON(ruta) {
    const r = await fetch(ruta + (ruta.includes('?') ? '&' : '?') + 'v=' + Math.floor(Date.now() / 60000), { cache: 'no-store' });
    if (!r.ok) throw new Error(ruta + ': HTTP ' + r.status);
    return r.json();
  }

  async function cargarDatos() {
    const [estado, conflictos, eventos, candidatos] = await Promise.all([
      cargarJSON('datos/estado.json'), cargarJSON('datos/conflictos.json'),
      cargarJSON('datos/eventos.json'), cargarJSON('datos/candidatos.json').catch(() => ({ candidatos: [] })),
    ]);
    E.datos = { estado, conflictos, eventos, candidatos };
    E.generado = estado.generado;
    indexar();
  }

  function indexar() {
    const idx = { conflicto: {}, eventosPorConflicto: {}, paisConflictos: {}, articulo: E.datos.eventos.articulos || {} };
    for (const c of E.datos.conflictos.conflictos) {
      idx.conflicto[c.id] = c;
      for (const p of c.paises_escenario) (idx.paisConflictos[p] = idx.paisConflictos[p] || []).push({ id: c.id, rol: 'escenario' });
      for (const p of c.paises_participantes) (idx.paisConflictos[p] = idx.paisConflictos[p] || []).push({ id: c.id, rol: 'participante' });
    }
    for (const ev of E.datos.eventos.eventos) (idx.eventosPorConflicto[ev.conflicto] = idx.eventosPorConflicto[ev.conflicto] || []).push(ev);
    E.idx = idx;
    if (!E.categorias.size) Object.keys(E.datos.conflictos.categorias).forEach((c) => E.categorias.add(c));
  }

  function eventosFiltrados(extra) {
    const limite = new Date(Date.now() - E.horas * 3600e3).toISOString();
    return E.datos.eventos.eventos.filter((ev) => {
      const c = E.idx.conflicto[ev.conflicto];
      if (!c || !E.categorias.has(c.categoria)) return false;
      if ((ev.referencia || '') < limite) return false;
      return !extra || extra(ev);
    }).sort((a, b) => (b.referencia || '').localeCompare(a.referencia || ''));
  }

  // ------------------------------------------------------------------ mapa
  function patron(fondo, linea, tam = 8, grosor = 2) {
    const c = document.createElement('canvas');
    c.width = c.height = tam;
    const x = c.getContext('2d');
    if (fondo) { x.fillStyle = fondo; x.fillRect(0, 0, tam, tam); }
    x.strokeStyle = linea; x.lineWidth = grosor;
    x.beginPath(); x.moveTo(0, tam); x.lineTo(tam, 0); x.moveTo(-tam / 2, tam / 2); x.lineTo(tam / 2, -tam / 2);
    x.moveTo(tam / 2, tam * 1.5); x.lineTo(tam * 1.5, tam / 2); x.stroke();
    return x.getImageData(0, 0, tam, tam);
  }

  function expresionColor(prop) {
    const e = ['match', ['get', prop]];
    for (const [k, v] of Object.entries(E.datos.conflictos.categorias)) e.push(k, v.color);
    e.push('#7a7a7a');
    return e;
  }

  function iniciarMapa() {
    const base = location.href.replace(/[#?].*$/, '').replace(/[^/]*$/, '');
    const mapa = new maplibregl.Map({
      container: 'mapa',
      style: {
        version: 8,
        glyphs: base + 'fonts/{fontstack}/{range}.pbf',
        sources: {},
        layers: [{ id: 'fondo', type: 'background', paint: { 'background-color': '#dfe7ee' } }],
      },
      center: [20, 20], zoom: 1.4, minZoom: 0.8, maxZoom: 11,
      attributionControl: false, dragRotate: false, pitchWithRotate: false,
      renderWorldCopies: true,
    });
    mapa.touchZoomRotate.disableRotation();
    mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    mapa.addControl(new maplibregl.AttributionControl({
      compact: true,
      customAttribution: 'Noticias: <a href="https://www.gdeltproject.org/" target="_blank" rel="noopener">The GDELT Project</a> y feeds RSS · Geografía: <a href="https://www.naturalearthdata.com/" target="_blank" rel="noopener">Natural Earth</a>',
    }), 'bottom-left');
    E.mapa = mapa;
    mapa.on('load', () => {
      const attrib = document.querySelector('.maplibregl-ctrl-attrib');
      if (attrib) attrib.classList.remove('maplibregl-compact-show');
      mapa.fitBounds([[-150, -48], [160, 70]], { padding: rellenoMapa(), duration: 0 });
      mapa.addImage('rayado', patron('#e3e3e3', '#5f5f5f', 8, 2.2), { pixelRatio: 1 });
      mapa.addImage('rayado-zona', patron(null, 'rgba(11,61,102,0.75)', 10, 1.6), { pixelRatio: 1 });
      agregarCapas();
      E.mapaListo = true;
      actualizarMapa();
      interacciones();
    });
    mapa.on('error', (e) => {
      const fuente = e && e.sourceId;
      if (fuente === 'ofm') {
        const cb = $('input[data-capa="base"]');
        if (cb && cb.checked) {
          cb.checked = false; E.capas.base = false; alternarBase(false);
          avisoCapas('No se pudo cargar el mapa base detallado (OpenFreeMap). Se sigue usando el mapa simple.');
        }
      }
    });
  }

  const esMovil = () => matchMedia('(max-width: 760px)').matches;
  function rellenoMapa() {
    if (esMovil()) {
      const p = $('#panel');
      const alto = p ? p.getBoundingClientRect().height : window.innerHeight * 0.42;
      return { top: 20, bottom: Math.min(alto + 10, window.innerHeight * 0.6), left: 16, right: 16 };
    }
    return { top: 30, bottom: 30, left: 330, right: 450 };
  }

  function avisoCapas(texto) {
    let a = $('#aviso-capas');
    if (!a) { a = el('<p id="aviso-capas" class="alerta aviso"></p>'); $('.leyenda').before(a); }
    a.textContent = texto;
  }

  function agregarCapas() {
    const m = E.mapa;
    m.addSource('paises', { type: 'geojson', data: E.geo.paises, promoteId: 'id' });
    m.addSource('zonas', { type: 'geojson', data: E.geo.zonas });
    m.addSource('etiquetas', { type: 'geojson', data: puntosEtiquetas() });
    m.addSource('eventos', { type: 'geojson', data: vacio(), cluster: true, clusterRadius: 38, clusterMaxZoom: 7 });
    m.addSource('eventos-pais', { type: 'geojson', data: vacio() });
    m.addSource('candidatos', { type: 'geojson', data: vacio() });
    const color = expresionColor('cat');
    m.addLayer({ id: 'tierra', type: 'fill', source: 'paises', paint: { 'fill-color': '#f8f8f6' } });
    m.addLayer({ id: 'paises-escenario', type: 'fill', source: 'paises',
      filter: ['all', ['==', ['get', 'rol'], 'escenario'], ['!=', ['get', 'cat'], 'varias']],
      paint: { 'fill-color': color, 'fill-opacity': 0.72 } });
    m.addLayer({ id: 'paises-varias', type: 'fill', source: 'paises',
      filter: ['all', ['==', ['get', 'rol'], 'escenario'], ['==', ['get', 'cat'], 'varias']],
      paint: { 'fill-pattern': 'rayado', 'fill-opacity': 0.9 } });
    m.addLayer({ id: 'paises-participante', type: 'line', source: 'paises',
      filter: ['==', ['get', 'rol'], 'participante'],
      paint: { 'line-color': ['case', ['==', ['get', 'cat'], 'varias'], '#555', color], 'line-width': 2.4, 'line-offset': 1 } });
    m.addLayer({ id: 'paises-borde', type: 'line', source: 'paises', paint: { 'line-color': '#7d838a', 'line-width': 0.6 } });
    m.addLayer({ id: 'paises-resaltado', type: 'line', source: 'paises', filter: ['==', ['get', 'id'], '__ninguno__'],
      paint: { 'line-color': '#111', 'line-width': 2.2 } });
    m.addLayer({ id: 'zonas-relleno', type: 'fill', source: 'zonas', paint: { 'fill-pattern': 'rayado-zona', 'fill-opacity': 0.95 } });
    m.addLayer({ id: 'zonas-borde', type: 'line', source: 'zonas', paint: { 'line-color': '#0b3d66', 'line-width': 1.2, 'line-dasharray': [3, 2] } });
    m.addLayer({ id: 'candidatos-borde', type: 'line', source: 'paises', filter: ['in', ['get', 'id'], ['literal', []]],
      paint: { 'line-color': '#5a5a5a', 'line-width': 2.2, 'line-dasharray': [2, 2] } });
    m.addLayer({ id: 'candidatos-punto', type: 'circle', source: 'candidatos',
      paint: { 'circle-radius': 11, 'circle-color': '#ffffff', 'circle-stroke-color': '#5a5a5a', 'circle-stroke-width': 2 } });
    m.addLayer({ id: 'candidatos-texto', type: 'symbol', source: 'candidatos',
      layout: { 'text-field': '?', 'text-font': ['Open Sans Semibold'], 'text-size': 13, 'text-allow-overlap': true },
      paint: { 'text-color': '#3a3a3a' } });
    m.addLayer({ id: 'etiquetas-paises', type: 'symbol', source: 'etiquetas', minzoom: 2.6,
      layout: { 'text-field': ['get', 'nombre'], 'text-font': ['Open Sans Semibold'], 'text-size': ['interpolate', ['linear'], ['zoom'], 3, 10, 6, 13],
        'text-max-width': 8, 'text-padding': 4 },
      paint: { 'text-color': '#4a4a48', 'text-halo-color': 'rgba(255,255,255,0.85)', 'text-halo-width': 1.3 } });
    m.addLayer({ id: 'eventos-pais', type: 'circle', source: 'eventos-pais',
      paint: { 'circle-radius': ['interpolate', ['linear'], ['get', 'n'], 1, 11, 20, 18, 80, 24],
        'circle-color': 'rgba(255,255,255,0.88)', 'circle-stroke-color': '#2d2d2d', 'circle-stroke-width': 2 } });
    m.addLayer({ id: 'eventos-pais-texto', type: 'symbol', source: 'eventos-pais',
      layout: { 'text-field': ['to-string', ['get', 'n']], 'text-font': ['Open Sans Semibold'], 'text-size': 11, 'text-allow-overlap': true },
      paint: { 'text-color': '#1b1b1a' } });
    m.addLayer({ id: 'grupos', type: 'circle', source: 'eventos', filter: ['has', 'point_count'],
      paint: { 'circle-color': '#3d3d3b', 'circle-opacity': 0.88, 'circle-stroke-color': '#fff', 'circle-stroke-width': 2,
        'circle-radius': ['step', ['get', 'point_count'], 13, 10, 17, 50, 22] } });
    m.addLayer({ id: 'grupos-texto', type: 'symbol', source: 'eventos', filter: ['has', 'point_count'],
      layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-font': ['Open Sans Semibold'], 'text-size': 12, 'text-allow-overlap': true },
      paint: { 'text-color': '#fff' } });
    m.addLayer({ id: 'eventos-punto', type: 'circle', source: 'eventos', filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-radius': ['case', ['>=', ['get', 'fuentes'], 2], 7.5, 6],
        'circle-color': ['case', ['==', ['get', 'precision'], 'provincia'], '#ffffff', color],
        'circle-stroke-color': ['case', ['==', ['get', 'precision'], 'provincia'], color, '#ffffff'],
        'circle-stroke-width': ['case', ['==', ['get', 'precision'], 'provincia'], 3, 1.6],
      } });
  }

  const vacio = () => ({ type: 'FeatureCollection', features: [] });

  function puntosEtiquetas() {
    const et = E.datos.conflictos.etiquetas_paises || {};
    return { type: 'FeatureCollection', features: Object.entries(et).map(([iso, c]) => ({
      type: 'Feature', geometry: { type: 'Point', coordinates: c }, properties: { id: iso, nombre: nombrePais(iso) } })) };
  }

  function actualizarMapa() {
    if (!E.mapaListo) return;
    const m = E.mapa;
    // Países: categoría y rol según conflictos visibles.
    const esc = {}, part = {};
    for (const c of E.datos.conflictos.conflictos) {
      if (c.estado !== 'activo' || !E.categorias.has(c.categoria)) continue;
      c.paises_escenario.forEach((p) => (esc[p] = esc[p] || new Set()).add(c.categoria));
      c.paises_participantes.forEach((p) => (part[p] = part[p] || new Set()).add(c.categoria));
    }
    const features = E.geo.paises.features.map((f) => {
      const id = f.properties.id;
      const cats = esc[id] || part[id];
      const rol = esc[id] ? 'escenario' : part[id] ? 'participante' : null;
      return { type: 'Feature', geometry: f.geometry, properties: { id, nombre: f.properties.nombre, rol,
        cat: cats ? (cats.size === 1 ? [...cats][0] : 'varias') : null } };
    });
    m.getSource('paises').setData({ type: 'FeatureCollection', features });
    // Acontecimientos.
    const evs = eventosFiltrados();
    const puntos = [], porPais = {};
    for (const ev of evs) {
      const l = ev.lugar || {};
      const c = E.idx.conflicto[ev.conflicto];
      if (l.coord) {
        puntos.push({ type: 'Feature', geometry: { type: 'Point', coordinates: l.coord },
          properties: { id: ev.id, cat: c.categoria, precision: l.precision, fuentes: ev.fuentes_independientes } });
      } else if (l.pais) {
        (porPais[l.pais] = porPais[l.pais] || []).push(ev.id);
      }
    }
    m.getSource('eventos').setData({ type: 'FeatureCollection', features: puntos });
    const et = E.datos.conflictos.etiquetas_paises || {};
    m.getSource('eventos-pais').setData({ type: 'FeatureCollection', features: Object.entries(porPais)
      .filter(([iso]) => et[iso]).map(([iso, ids]) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: et[iso] },
        properties: { pais: iso, n: ids.length } })) });
    // Candidatos.
    const cands = (E.datos.candidatos.candidatos || []);
    m.setFilter('candidatos-borde', ['in', ['get', 'id'], ['literal', cands.map((c) => c.pais)]]);
    m.getSource('candidatos').setData({ type: 'FeatureCollection', features: cands.filter((c) => c.etiqueta)
      .map((c) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: c.etiqueta }, properties: { id: c.id } })) });
    visibilidad();
  }

  function visibilidad() {
    const m = E.mapa;
    const vis = (ids, on) => ids.forEach((id) => m.getLayer(id) && m.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'));
    vis(['paises-escenario', 'paises-varias', 'paises-participante'], E.capas.paises);
    vis(['eventos-punto', 'grupos', 'grupos-texto', 'eventos-pais', 'eventos-pais-texto'], E.capas.eventos);
    vis(['zonas-relleno', 'zonas-borde'], E.capas.zonas);
    vis(['candidatos-borde', 'candidatos-punto', 'candidatos-texto'], E.capas.candidatos);
    const op = E.capas.base ? 0.45 : 0.72;
    if (m.getLayer('paises-escenario')) m.setPaintProperty('paises-escenario', 'fill-opacity', op);
  }

  function alternarBase(on) {
    const m = E.mapa;
    if (!E.mapaListo) return;
    const capas = ['ofm-agua', 'ofm-limites', 'ofm-rutas', 'ofm-lugares'];
    if (!on) { capas.forEach((id) => m.getLayer(id) && m.removeLayer(id)); if (m.getSource('ofm')) m.removeSource('ofm'); visibilidad(); return; }
    if (!m.getSource('ofm')) {
      m.addSource('ofm', { type: 'vector', url: 'https://tiles.openfreemap.org/planet',
        attribution: '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> Datos de <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>' });
    }
    const antes = 'paises-borde';
    m.addLayer({ id: 'ofm-agua', type: 'fill', source: 'ofm', 'source-layer': 'water', paint: { 'fill-color': '#c6d6e3' } }, antes);
    m.addLayer({ id: 'ofm-limites', type: 'line', source: 'ofm', 'source-layer': 'boundary', minzoom: 3,
      filter: ['==', ['get', 'admin_level'], 4], paint: { 'line-color': '#9a9a9a', 'line-width': 0.7, 'line-dasharray': [3, 2] } }, antes);
    m.addLayer({ id: 'ofm-rutas', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 5,
      filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary']]],
      paint: { 'line-color': '#c9b99a', 'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.5, 10, 2] } }, antes);
    m.addLayer({ id: 'ofm-lugares', type: 'symbol', source: 'ofm', 'source-layer': 'place', minzoom: 4.5,
      filter: ['in', ['get', 'class'], ['literal', ['city', 'town']]],
      layout: { 'text-field': ['coalesce', ['get', 'name:es'], ['get', 'name:latin'], ['get', 'name']], 'text-font': ['Open Sans Semibold'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 5, 10, 10, 13], 'text-max-width': 8 },
      paint: { 'text-color': '#333', 'text-halo-color': '#fff', 'text-halo-width': 1.2 } }, 'eventos-pais');
    visibilidad();
  }

  // ------------------------------------------------------------- interacción
  function interacciones() {
    const m = E.mapa;
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: '280px' });
    const capasPais = ['paises-escenario', 'paises-varias', 'paises-participante', 'tierra'];
    let hover = null;
    m.on('mousemove', (e) => {
      const f = m.queryRenderedFeatures(e.point, { layers: ['eventos-punto', 'grupos', 'eventos-pais', 'candidatos-punto', 'zonas-relleno', ...capasPais].filter((l) => m.getLayer(l)) });
      m.getCanvas().style.cursor = f.length ? 'pointer' : '';
      if (!f.length) { popup.remove(); if (hover) { m.setFilter('paises-resaltado', ['==', ['get', 'id'], '__ninguno__']); hover = null; } return; }
      const x = f[0];
      let html = '';
      if (x.layer.id === 'eventos-punto') {
        const ev = E.datos.eventos.eventos.find((v) => v.id === x.properties.id);
        if (ev) html = `<div class="popup-titulo">${esc(ev.titulo)}</div><div class="popup-sub">${esc(E.idx.conflicto[ev.conflicto].nombre)} · ${esc((ev.lugar || {}).nombre || '')} (${esc(PRECISION[(ev.lugar || {}).precision] || '')})</div>`;
      } else if (x.layer.id === 'grupos') {
        html = `<div class="popup-titulo">${x.properties.point_count} acontecimientos</div><div class="popup-sub">Acercá el mapa o hacé clic para verlos</div>`;
      } else if (x.layer.id === 'eventos-pais') {
        html = `<div class="popup-titulo">${x.properties.n} acontecimiento(s) en ${esc(nombrePais(x.properties.pais))}</div><div class="popup-sub">Ubicación conocida solo a nivel país: el anillo no indica un lugar exacto.</div>`;
      } else if (x.layer.id === 'candidatos-punto') {
        const c = (E.datos.candidatos.candidatos || []).find((v) => v.id === x.properties.id);
        if (c) html = `<div class="popup-titulo">${esc(c.nombre)}</div><div class="popup-sub">Detectado automáticamente · sin verificar</div>`;
      } else if (x.layer.id === 'zonas-relleno') {
        html = `<div class="popup-titulo">${esc(x.properties.nombre)}</div><div class="popup-sub">Zona en disputa de soberanía (no indica control militar ni frentes). Fuente: Natural Earth, consultado ${esc(fechaCorta(x.properties.fecha_consulta))}.</div>`;
      } else {
        const id = x.properties.id;
        const cs = (E.idx.paisConflictos[id] || []).filter((r) => E.categorias.has(E.idx.conflicto[r.id].categoria));
        html = `<div class="popup-titulo">${esc(nombrePais(id))}</div>` + (cs.length
          ? '<div class="popup-sub">' + cs.slice(0, 5).map((r) => esc(E.idx.conflicto[r.id].nombre) + (r.rol === 'participante' ? ' (participa)' : '')).join('<br>') + (cs.length > 5 ? '<br>…' : '') + '</div>'
          : '<div class="popup-sub">Sin conflictos del registro en las categorías elegidas</div>');
        if (hover !== id) { hover = id; m.setFilter('paises-resaltado', ['==', ['get', 'id'], id]); }
      }
      if (html && matchMedia('(hover: hover)').matches) popup.setLngLat(e.lngLat).setHTML(html).addTo(m);
    });
    m.on('mouseout', () => popup.remove());
    m.on('click', (e) => {
      const capas = ['grupos', 'eventos-punto', 'eventos-pais', 'candidatos-punto', 'zonas-relleno', ...capasPais].filter((l) => m.getLayer(l) && m.getLayoutProperty(l, 'visibility') !== 'none');
      const f = m.queryRenderedFeatures(e.point, { layers: capas });
      if (!f.length) return;
      const x = f[0];
      if (x.layer.id === 'grupos') {
        m.getSource('eventos').getClusterExpansionZoom(x.properties.cluster_id).then((z) => m.easeTo({ center: x.geometry.coordinates, zoom: z + 0.3 }));
      } else if (x.layer.id === 'eventos-punto') {
        abrirEvento(x.properties.id);
      } else if (x.layer.id === 'eventos-pais') {
        abrirVista({ tipo: 'pais', id: x.properties.pais });
      } else if (x.layer.id === 'candidatos-punto') {
        abrirVista({ tipo: 'candidato', id: x.properties.id });
      } else if (x.layer.id === 'zonas-relleno') {
        new maplibregl.Popup({ offset: 8 }).setLngLat(e.lngLat).setHTML(`<div class="popup-titulo">${esc(x.properties.nombre)}</div><div class="popup-sub">Zona en disputa de soberanía según ${esc(x.properties.fuente)}; consultado ${esc(fechaCorta(x.properties.fecha_consulta))}. No indica control militar ni líneas de frente.</div>`).addTo(m);
        const otra = f.find((g) => capasPais.includes(g.layer.id));
        if (otra && (E.idx.paisConflictos[otra.properties.id] || []).length) abrirVista({ tipo: 'pais', id: otra.properties.id });
      } else {
        const id = x.properties.id;
        if ((E.idx.paisConflictos[id] || []).length) abrirVista({ tipo: 'pais', id });
      }
    });
  }

  // ------------------------------------------------------------------ panel
  function insignias(ev) {
    const b = [];
    if (ev.estado === 'declaracion_parte') b.push(`<span class="insignia parte">Declaración de ${esc(Object.keys(ev.partes_con_fuente || {}).join(', ') || 'parte')}</span>`);
    else if (ev.estado === 'varias_fuentes') b.push(`<span class="insignia varias">${ev.fuentes_independientes} fuentes independientes</span>`);
    else b.push('<span class="insignia preliminar">Reporte preliminar</span>');
    if (ev.estado !== 'declaracion_parte' && Object.keys(ev.partes_con_fuente || {}).length) b.push(`<span class="insignia parte">También declaración de ${esc(Object.keys(ev.partes_con_fuente).join(', '))}</span>`);
    if (ev.contrapuestas) b.push('<span class="insignia contrapuestas">Versiones contrapuestas</span>');
    if (ev.atribuida) b.push('<span class="insignia">Afirmación atribuida</span>');
    if (ev.marcado_preliminar && ev.estado !== 'preliminar') b.push('<span class="insignia preliminar">Titular preliminar</span>');
    return `<div class="insignias">${b.join('')}</div>`;
  }

  function textoLugar(l) {
    if (!l || !l.nombre) return 'Sin ubicación';
    const pais = l.pais ? nombrePais(l.pais) : '';
    const nombre = l.precision !== 'pais' && pais && l.nombre !== pais ? `${l.nombre} (${pais})` : l.nombre;
    return `${nombre} · ${PRECISION[l.precision] || ''}`;
  }

  function sinTraducir(ev) {
    const a = E.idx.articulo[ev.articulo_principal] || {};
    return a.idioma && a.idioma !== 'es' && !a.titulo_es ? (IDIOMAS[a.idioma] || a.idioma) : null;
  }

  function lineaFecha(ev) {
    if (ev.ultima_publicacion) return `Publicado ${relativo(ev.ultima_publicacion)}`;
    return `Detectado ${relativo(ev.ultima_deteccion)} (sin fecha de publicación)`;
  }

  function tarjetaEvento(ev, mostrarConflicto = true) {
    const c = E.idx.conflicto[ev.conflicto];
    const l = ev.lugar || {};
    const abierto = E.eventoAbierto === ev.id;
    const t = el(`<article class="tarjeta" style="--cat:${colorCat(c.categoria)}" tabindex="0" data-evento="${esc(ev.id)}" aria-expanded="${abierto}">
      ${mostrarConflicto ? `<div class="conflicto">${esc(c.nombre)}</div>` : ''}
      <h3>${esc(ev.titulo)}</h3>
      ${insignias(ev)}
      <div class="meta">
        <span>${esc(textoLugar(l))}</span>
        <span>${esc(lineaFecha(ev))}</span>
        <span>${ev.n_articulos} artículo(s)</span>
        ${sinTraducir(ev) ? `<span class="nota-trad">Sin traducir (${esc(sinTraducir(ev))})</span>` : ev.titulo_traducido ? '<span>Traducción automática</span>' : ''}
      </div>
    </article>`);
    if (abierto) t.appendChild(detalleEvento(ev));
    const alternar = (e) => {
      if (e.target.closest('a, button, .detalle')) return;
      E.eventoAbierto = E.eventoAbierto === ev.id ? null : ev.id;
      const nuevo = tarjetaEvento(ev, mostrarConflicto);
      t.replaceWith(nuevo);
      nuevo.focus({ preventScroll: true });
      if (E.eventoAbierto && l.coord) E.mapa.easeTo({ center: l.coord, zoom: Math.max(E.mapa.getZoom(), 5), padding: rellenoMapa() });
    };
    t.addEventListener('click', alternar);
    t.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alternar(e); } });
    return t;
  }

  function detalleEvento(ev) {
    const arts = (ev.articulos || []).map((k) => E.idx.articulo[k]).filter(Boolean);
    const l = ev.lugar || {};
    const d = el('<div class="detalle"></div>');
    let html = `<p class="meta" style="font-size:12.5px;color:var(--texto-2)"><strong>Corroboración:</strong> ${esc(ev.reglas || '')}</p>`;
    html += `<p class="meta" style="font-size:12.5px;color:var(--texto-2)"><strong>Ubicación:</strong> ${esc(l.nombre || 'no determinada')}${l.precision ? ' — precisión: ' + esc(PRECISION[l.precision]) : ''}. ${esc(METODO[l.metodo] || '')}${(l.otros_lugares || []).length ? '. Otros lugares reportados: ' + esc(l.otros_lugares.join(', ')) : ''}.</p>`;
    if ((ev.fechas_hecho || []).length) html += `<p class="meta" style="font-size:12.5px;color:var(--texto-2)"><strong>Fecha del hecho</strong> (según GDELT, precisión de día): ${esc(ev.fechas_hecho.map(fechaCorta).join(', '))}</p>`;
    d.innerHTML = html;
    for (const a of arts) d.appendChild(bloqueArticulo(a));
    if (ev.articulos_omitidos) d.appendChild(el(`<p class="meta">Y ${ev.articulos_omitidos} artículo(s) más sobre este acontecimiento.</p>`));
    return d;
  }

  function bloqueArticulo(a) {
    const traducido = a.titulo_es && a.idioma !== 'es';
    const tr = a.traduccion || {};
    const partes = [];
    partes.push(`<div><span class="fuente">${esc(a.organizacion || a.fuente_nombre || a.dominio)}</span>`
      + (a.agencia ? ` · reproduce a ${esc(a.agencia)}` : '')
      + (a.pais_medio ? ` · medio de ${esc(nombrePais(a.pais_medio))}` : '')
      + (a.fuente_estatal_de ? ` · <em>${a.fuente_estatal_tipo === 'oficial' ? 'fuente oficial' : 'medio estatal'} de ${esc(nombrePais(a.fuente_estatal_de))}</em>` : '')
      + (a.idioma ? ` · ${esc(IDIOMAS[a.idioma] || a.idioma)}` : '') + '</div>');
    partes.push(`<div>${esc(a.titulo_es || a.titulo)}</div>`);
    if (traducido) partes.push(`<div class="orig">Original: ${esc(a.titulo)}</div>`);
    if (!a.titulo_es && a.idioma && a.idioma !== 'es') partes.push(`<div class="nota-trad">Traducción no disponible (${esc(tr.error || tr.estado || 'pendiente')}). Se muestra el texto original.</div>`);
    const resumen = a.resumen_es || a.resumen;
    if (resumen) {
      const etiqueta = a.resumen_es && a.idioma !== 'es' ? `Según ${esc(a.organizacion || a.fuente_nombre)} (traducción automática):` : `Según ${esc(a.organizacion || a.fuente_nombre)}:`;
      partes.push(`<blockquote><small>${etiqueta}</small><br>${esc(resumen)}</blockquote>`);
      if (!a.resumen_es && a.idioma !== 'es') partes.push('<div class="nota-trad">Resumen sin traducir.</div>');
    } else {
      partes.push('<div class="orig">Solo se dispone del titular (sin resumen del medio).</div>');
    }
    const f = [];
    f.push(a.pub ? `Publicado: ${absoluto(a.pub)}` : a.pub_descartada ? `Fecha de publicación descartada (${a.pub_descartada})` : 'Sin fecha de publicación');
    f.push(`Detectado: ${absoluto(a.detectado)}`);
    if (a.visto_gdelt) f.push(`Visto por GDELT: ${absoluto(a.visto_gdelt)}`);
    partes.push(`<div class="fechas">${esc(f.join(' · '))}</div>`);
    partes.push(`<div><a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">Abrir el artículo original ↗</a></div>`);
    return el(`<div class="articulo">${partes.join('')}</div>`);
  }

  function mensajeVacio(texto) { return el(`<p class="vacio">${esc(texto)}</p>`); }

  function renderPanel() {
    const cont = $('#contenido-panel');
    cont.innerHTML = '';
    $$('.pestanas button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.pestana === E.pestana && !E.vista)));
    if (!E.datos.eventos) { cont.appendChild(mensajeVacio('Cargando…')); return; }
    if (E.vista) return renderVista(cont);
    if (E.pestana === 'novedades') renderNovedades(cont);
    else if (E.pestana === 'conflictos') renderConflictos(cont);
    else renderFuentes(cont);
  }

  function avisosDatos(cont) {
    const est = E.datos.estado;
    const s = estadoActualizacion();
    if (s.nivel !== 'ok') cont.appendChild(el(`<p class="alerta ${s.nivel === 'error' ? 'error' : 'aviso'}">${esc(s.detalle)}</p>`));
    if (!E.datos.eventos.eventos.length) cont.appendChild(el('<p class="alerta info">Todavía no hay acontecimientos publicados. Si el sitio es nuevo, la primera recopilación puede tardar hasta 30 minutos.</p>'));
    return est;
  }

  function renderNovedades(cont) {
    avisosDatos(cont);
    let evs = eventosFiltrados(E.soloVarias ? (ev) => ev.fuentes_independientes >= 2 : null);
    if (E.orden === 'fuentes') evs = evs.slice().sort((a, b) => b.fuentes_independientes - a.fuentes_independientes || (b.referencia || '').localeCompare(a.referencia || ''));
    const barra = el(`<div class="opciones-lista">
      <div class="segmentado chico" role="radiogroup" aria-label="Orden">
        <button role="radio" aria-checked="${E.orden === 'recientes'}" data-orden="recientes">Más recientes</button>
        <button role="radio" aria-checked="${E.orden === 'fuentes'}" data-orden="fuentes">Más fuentes</button>
      </div>
      <label class="interruptor"><input type="checkbox" ${E.soloVarias ? 'checked' : ''}> Solo con 2 o más fuentes independientes</label>
    </div>`);
    $$('button[data-orden]', barra).forEach((b) => b.onclick = () => { E.orden = b.dataset.orden; E.limiteLista = 40; renderPanel(); });
    $('input', barra).onchange = (e) => { E.soloVarias = e.target.checked; E.limiteLista = 40; renderPanel(); };
    cont.appendChild(barra);
    cont.appendChild(el(`<div class="encabezado-lista"><strong>${evs.length} acontecimientos</strong> · últimas ${E.horas} h · ${E.orden === 'fuentes' ? 'con más fuentes primero' : 'más recientes primero'}</div>`));
    if (!evs.length) cont.appendChild(mensajeVacio('No hay novedades en este período para las categorías elegidas.'));
    evs.slice(0, E.limiteLista).forEach((ev) => cont.appendChild(tarjetaEvento(ev)));
    if (evs.length > E.limiteLista) {
      const b = el(`<button class="btn mas">Ver ${Math.min(40, evs.length - E.limiteLista)} más</button>`);
      b.onclick = () => { E.limiteLista += 40; renderPanel(); };
      cont.appendChild(b);
    }
  }

  function renderConflictos(cont) {
    const hace = E.horas;
    const lista = E.datos.conflictos.conflictos.filter((c) => E.categorias.has(c.categoria));
    const n = (c) => (E.idx.eventosPorConflicto[c.id] || []).filter((ev) => ev.referencia >= new Date(Date.now() - hace * 3600e3).toISOString()).length;
    lista.sort((a, b) => n(b) - n(a) || a.nombre.localeCompare(b.nombre, 'es'));
    cont.appendChild(el(`<div class="encabezado-lista"><strong>${lista.length} situaciones en el registro</strong> · ordenadas por novedades (${hace} h)</div>`));
    for (const c of lista) {
      const k = n(c);
      const t = el(`<article class="tarjeta" style="--cat:${colorCat(c.categoria)}" tabindex="0">
        <div class="conflicto">${esc(nombreCat(c.categoria))}</div>
        <h3>${esc(c.nombre)}</h3>
        <div class="meta"><span>${esc(c.paises_escenario.map(nombrePais).join(', '))}</span>
          <span>${k ? k + ' acontecimiento(s) en ' + hace + ' h' : 'Sin noticias nuevas en ' + hace + ' h (sigue en el registro)'}</span>
          <span>Revisado ${esc(fechaCorta(c.revisado))}${c.revision_pendiente ? ' · revisión pendiente' : ''}</span></div>
      </article>`);
      const abrir = () => abrirVista({ tipo: 'conflicto', id: c.id });
      t.onclick = abrir; t.onkeydown = (e) => { if (e.key === 'Enter') abrir(); };
      cont.appendChild(t);
    }
  }

  function renderVista(cont) {
    const v = E.vista;
    const volver = el('<button class="volver">← Volver</button>');
    volver.onclick = () => { E.vista = null; E.eventoAbierto = null; renderPanel(); };
    cont.appendChild(volver);
    if (v.tipo === 'conflicto') return fichaConflicto(cont, E.idx.conflicto[v.id]);
    if (v.tipo === 'pais') return fichaPais(cont, v.id);
    if (v.tipo === 'candidato') return fichaCandidato(cont, (E.datos.candidatos.candidatos || []).find((c) => c.id === v.id));
  }

  function fichaConflicto(cont, c) {
    if (!c) return cont.appendChild(mensajeVacio('Conflicto no encontrado.'));
    const evs = eventosFiltrados((ev) => ev.conflicto === c.id);
    const st = c.estadisticas || {};
    const f = el(`<div class="ficha">
      <span class="categoria-ficha"><i style="background:${colorCat(c.categoria)}"></i>${esc(nombreCat(c.categoria))}</span>
      <h2>${esc(c.nombre)}</h2>
      <p class="meta" style="font-size:12.5px;color:var(--texto-3)">Estado en el registro: ${esc(c.estado)} · revisado el ${esc(fechaCorta(c.revisado))}${c.revision_pendiente ? ' · <strong>revisión pendiente</strong>' : ''}</p>
      <section><h4>Qué está pasando</h4><p>${esc(c.resumen)}</p>
        <p class="meta" style="font-size:12px;color:var(--texto-3)">Resumen del registro basado en las fuentes indicadas abajo. Las novedades se actualizan automáticamente.</p></section>
      <section><h4>Quiénes participan</h4><ul>${c.actores.map((a) => `<li>${esc(a)}</li>`).join('')}</ul></section>
      <section><h4>Países</h4><p><strong>Escenario:</strong> ${esc(c.paises_escenario.map(nombrePais).join(', ') || '—')}</p>
        ${c.paises_participantes.length ? `<p><strong>Participan o están involucrados:</strong> ${esc((c.participantes_grupos || []).includes('UE') ? 'Unión Europea (27 países)' + (c.paises_participantes.filter((p) => !['AUT','BEL','BGR','HRV','CYP','CZE','DNK','EST','FIN','FRA','DEU','GRC','HUN','IRL','ITA','LVA','LTU','LUX','MLT','NLD','POL','PRT','ROU','SVK','SVN','ESP','SWE'].includes(p)).map((p) => ', ' + nombrePais(p)).join('')) : c.paises_participantes.map(nombrePais).join(', '))}</p>` : ''}</section>
      <section><h4>Últimas noticias (${E.horas} h)</h4><div class="lista-eventos"></div></section>
      <section><h4>Fuentes del registro</h4><ul class="fuentes-registro">${c.fuentes.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.titulo)}</a> — ${esc(s.medio)}, ${esc(fechaCorta(s.fecha))}</li>`).join('')}</ul></section>
      <p class="meta" style="font-size:12px;color:var(--texto-3)">Actividad en el sistema: ${st.eventos_72h || 0} acontecimiento(s) en 72 h${st.ultima_noticia ? ', última noticia ' + esc(relativo(st.ultima_noticia)) : ''}. La falta de noticias no implica que el conflicto haya terminado.</p>
    </div>`);
    const lista = $('.lista-eventos', f);
    if (!evs.length) lista.appendChild(mensajeVacio('Sin acontecimientos nuevos detectados en este período.'));
    evs.slice(0, 60).forEach((ev) => lista.appendChild(tarjetaEvento(ev, false)));
    cont.appendChild(f);
  }

  function fichaPais(cont, iso) {
    const rels = (E.idx.paisConflictos[iso] || []).filter((r) => E.categorias.has(E.idx.conflicto[r.id].categoria));
    const f = el(`<div class="ficha"><h2>${esc(nombrePais(iso))}</h2>
      <section><h4>Conflictos y situaciones</h4><div class="lista-conf"></div></section>
      <section><h4>Acontecimientos ubicados en el país (${E.horas} h)</h4><div class="lista-eventos"></div></section></div>`);
    const lc = $('.lista-conf', f);
    if (!rels.length) lc.appendChild(mensajeVacio('Sin conflictos del registro en las categorías elegidas.'));
    for (const r of rels) {
      const c = E.idx.conflicto[r.id];
      const t = el(`<article class="tarjeta" style="--cat:${colorCat(c.categoria)}" tabindex="0"><div class="conflicto">${esc(nombreCat(c.categoria))} · ${r.rol === 'escenario' ? 'escenario' : 'participa'}</div><h3>${esc(c.nombre)}</h3></article>`);
      t.onclick = () => abrirVista({ tipo: 'conflicto', id: c.id });
      t.onkeydown = (e) => { if (e.key === 'Enter') t.onclick(); };
      lc.appendChild(t);
    }
    const evs = eventosFiltrados((ev) => (ev.lugar || {}).pais === iso);
    const le = $('.lista-eventos', f);
    if (!evs.length) le.appendChild(mensajeVacio('Sin acontecimientos con ubicación en este país en el período.'));
    evs.slice(0, 60).forEach((ev) => le.appendChild(tarjetaEvento(ev)));
    cont.appendChild(f);
  }

  function fichaCandidato(cont, c) {
    if (!c) return cont.appendChild(mensajeVacio('Este candidato ya no está activo.'));
    const borrador = `- id: nuevo-${c.pais.toLowerCase()}\n  nombre: "…"\n  categoria: otro_armado\n  estado: activo\n  revisado: ${new Date().toISOString().slice(0, 10)}\n  resumen: >-\n    …\n  actores: […]\n  paises_escenario: [${c.pais}]\n  paises_participantes: []\n  partes: []\n  zonas: []\n  fuentes:\n    - {medio: …, fecha: …, titulo: "…", url: "…"}\n  coincidencias:\n    lugares: […]\n    paises_nombre: [${c.pais}]\n    paises_gdelt: [${c.pais}]`;
    const f = el(`<div class="ficha"><span class="categoria-ficha"><i style="background:#8c8c8c"></i>Detectado automáticamente · sin verificar</span>
      <h2>${esc(c.nombre)}</h2>
      <p class="alerta aviso">No forma parte del registro de conflictos. ${c.estado === 'respaldo_suficiente' ? 'Cumple las reglas de respaldo para que una persona lo revise.' : 'Aún no alcanza el respaldo requerido para revisión.'}</p>
      <dl class="kv"><dt>Detectado</dt><dd>${esc(absoluto(c.primera_deteccion))}</dd><dt>Señales</dt><dd>${esc(c.reglas)}</dd></dl>
      <section><h4>Artículos que lo sustentan</h4><div class="lista"></div></section>
      <details><summary>Borrador para incorporarlo al registro (requiere revisión)</summary><pre style="white-space:pre-wrap;font-size:12px">${esc(borrador)}</pre></details></div>`);
    const lista = $('.lista', f);
    (c.articulos || []).forEach((a) => lista.appendChild(bloqueArticulo(a)));
    cont.appendChild(f);
  }

  function renderFuentes(cont) {
    const est = E.datos.estado || {};
    const s = estadoActualizacion();
    cont.appendChild(el(`<p class="alerta ${s.nivel === 'ok' ? 'info' : s.nivel === 'error' ? 'error' : 'aviso'}">${esc(s.detalle)}</p>`));
    const g = est.gdelt || {};
    const t = est.traduccion || {};
    const tg = est.telegram || {};
    const r = est.resumen_fuentes || {};
    const ultimoG = g.ultimo_archivo ? g.ultimo_archivo.replace(/(\d{4})(\d{2})(\d{2})(\d{2})(\d{2}).*/, '$1-$2-$3T$4:$5:00Z') : null;
    cont.appendChild(el(`<dl class="kv">
      <dt>Última actualización exitosa</dt><dd>${esc(absoluto(est.ultimo_exito))} (${esc(relativo(est.ultimo_exito) || 'nunca')})</dd>
      <dt>Último ciclo</dt><dd>${esc(absoluto(est.generado))} · ${est.ciclo_ok ? 'correcto' : 'con fallas'} · ${esc(est.duracion_s)} s</dd>
      <dt>Feeds RSS</dt><dd>${r.ok || 0} de ${r.total || 0} disponibles${r.error ? ' · ' + r.error + ' con error' : ''}${r.bloqueadas ? ' · ' + r.bloqueadas + ' bloqueadas por robots.txt' : ''}</dd>
      <dt>GDELT</dt><dd>${ultimoG ? 'último archivo ' + esc(absoluto(ultimoG)) : 'sin archivos procesados'}${g.archivos_faltantes ? ' · ' + g.archivos_faltantes + ' faltantes' : ''}</dd>
      <dt>Traducción</dt><dd>${esc(t.motor || '—')}: ${t.traducidos || 0} nuevas, ${t.desde_cache || 0} reutilizadas, ${t.fallidos || 0} fallidas${(t.sin_modelo || []).length ? ' · sin modelo: ' + esc(t.sin_modelo.join(', ')) : ''}</dd>
      <dt>Alertas Telegram</dt><dd>${tg.configurado ? (tg.vinculado ? 'activas' + (tg.pausado ? ' (en pausa)' : '') : 'bot configurado, chat sin vincular') : 'no configuradas'}</dd>
    </dl>`));
    if ((est.advertencias || []).length) cont.appendChild(el(`<div class="alerta aviso"><strong>Advertencias del último ciclo</strong><ul>${est.advertencias.map((a) => `<li>${esc(a)}</li>`).join('')}</ul></div>`));
    if ((est.errores || []).length) cont.appendChild(el(`<div class="alerta error"><strong>Errores del último ciclo</strong><ul>${est.errores.slice(0, 6).map((a) => `<li>${esc(a)}</li>`).join('')}</ul></div>`));
    const filas = (est.fuentes || []).map((f) => `<tr><td>${esc(f.nombre)}<br><small>${esc(f.tipo)} · ${esc(IDIOMAS[f.idioma] || f.idioma)}${f.pais ? ' · ' + esc(nombrePais(f.pais)) : ''}${f.propiedad === 'estatal' ? ' · estatal' : ''}</small></td>
      <td class="${f.estado === 'ok' ? 'estado-ok' : f.estado === 'error' ? 'estado-error' : 'estado-otro'}">${esc({ ok: 'disponible', error: 'error', bloqueada_robots: 'bloqueada (robots.txt)', sin_datos: 'sin datos' }[f.estado] || f.estado)}${f.error ? '<br><small>' + esc(f.error) + '</small>' : ''}</td>
      <td><small>${f.ultimo_ok ? esc(relativo(f.ultimo_ok)) : '—'}</small></td></tr>`).join('');
    cont.appendChild(el(`<section><h4 style="font-size:12px;text-transform:uppercase;color:var(--texto-3);margin:14px 0 6px">Fuentes RSS</h4>
      <table class="tabla-fuentes"><thead><tr><th>Fuente</th><th>Estado</th><th>Último dato</th></tr></thead><tbody>${filas}</tbody></table></section>`));
    cont.appendChild(el(`<section><h4 style="font-size:12px;text-transform:uppercase;color:var(--texto-3);margin:14px 0 6px">Cobertura y limitaciones</h4>
      <ul style="font-size:13px;color:var(--texto-2);padding-left:18px">
        <li>No se capturan todos los conflictos ni todas las noticias del mundo: solo lo que publican estas fuentes y lo que indexa GDELT.</li>
        <li>GDELT entrega titulares y metadatos, no el texto completo; la geolocalización y la clasificación son automáticas y pueden fallar.</li>
        <li>Las traducciones son automáticas (modelos abiertos, calidad variable). Algunos idiomas no tienen modelo.</li>
        <li>Las etiquetas de verificación cuentan orígenes; no confirman hechos.</li>
        <li>La actualización programada de GitHub Actions puede demorarse en horas de alta demanda.</li>
      </ul></section>`));
    cont.appendChild(el(`<p class="meta" style="font-size:12px;color:var(--texto-3)">Datos: ${esc(g.cita || 'The GDELT Project')}. Geografía: Natural Earth (dominio público). Mapa: MapLibre GL JS. Traducción: Argos Translate.</p>`));
  }

  function abrirVista(v) {
    E.vista = v; E.eventoAbierto = null;
    renderPanel();
    panelNormal();
    if (v.tipo === 'conflicto') encuadrar(E.idx.conflicto[v.id].paises_escenario);
    else if (v.tipo === 'pais') encuadrar([v.id]);
    else if (v.tipo === 'candidato') { const c = (E.datos.candidatos.candidatos || []).find((x) => x.id === v.id); if (c) encuadrar([c.pais]); }
  }

  function abrirEvento(id) {
    const ev = E.datos.eventos.eventos.find((x) => x.id === id);
    if (!ev) return;
    E.vista = null; E.pestana = 'novedades'; E.eventoAbierto = id;
    const evs = eventosFiltrados();
    const pos = evs.findIndex((x) => x.id === id);
    if (pos >= E.limiteLista) E.limiteLista = pos + 10;
    renderPanel(); panelNormal();
    const t = $(`[data-evento="${CSS.escape(id)}"]`);
    if (t) t.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  // ------------------------------------------------------------ geometría
  const bboxes = {};
  function calcularBboxes() {
    for (const f of E.geo.paises.features) {
      let b = [180, 90, -180, -90];
      const recorrer = (c) => { if (typeof c[0] === 'number') { b = [Math.min(b[0], c[0]), Math.min(b[1], c[1]), Math.max(b[2], c[0]), Math.max(b[3], c[1])]; } else c.forEach(recorrer); };
      recorrer(f.geometry.coordinates);
      bboxes[f.properties.id] = b;
    }
  }
  function encuadrar(paises) {
    if (!E.mapaListo || !paises || !paises.length) return;
    let b = null;
    for (const p of paises) {
      const x = bboxes[p];
      if (!x) continue;
      b = b ? [Math.min(b[0], x[0]), Math.min(b[1], x[1]), Math.max(b[2], x[2]), Math.max(b[3], x[3])] : x.slice();
    }
    if (!b) return;
    const padding = rellenoMapa();
    if (b[2] - b[0] > 250) {
      const et = (E.datos.conflictos.etiquetas_paises || {})[paises[0]];
      if (et) E.mapa.easeTo({ center: et, zoom: 2.2, padding });
      return;
    }
    E.mapa.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding, maxZoom: 5.5, duration: 700 });
  }

  // ------------------------------------------------------------ búsqueda
  function iniciarBusqueda() {
    const input = $('#buscar'), lista = $('#sugerencias');
    let opciones = [], sel = -1;
    const cerrar = () => { lista.hidden = true; input.setAttribute('aria-expanded', 'false'); sel = -1; };
    const elegir = (o) => { cerrar(); input.value = ''; if (o.tipo === 'conflicto') abrirVista({ tipo: 'conflicto', id: o.id }); else abrirVista({ tipo: 'pais', id: o.id }); $('#controles').classList.remove('abierto'); };
    input.addEventListener('input', () => {
      const q = norm(input.value);
      if (q.length < 2) return cerrar();
      const confs = E.datos.conflictos.conflictos.filter((c) => norm(c.nombre).includes(q) || c.actores.some((a) => norm(a).includes(q)))
        .map((c) => ({ tipo: 'conflicto', id: c.id, texto: c.nombre, sub: nombreCat(c.categoria) }));
      const paises = Object.entries(E.datos.conflictos.paises).filter(([, n]) => norm(n).includes(q))
        .map(([iso, n]) => ({ tipo: 'pais', id: iso, texto: n, sub: (E.idx.paisConflictos[iso] || []).length ? (E.idx.paisConflictos[iso].length + ' conflicto(s)') : 'país' }));
      opciones = [...confs.slice(0, 8), ...paises.sort((a, b) => (b.sub === 'país' ? 0 : 1) - (a.sub === 'país' ? 0 : 1)).slice(0, 8)];
      lista.innerHTML = opciones.length ? opciones.map((o, i) => `<li role="option" id="op-${i}" aria-selected="false">${esc(o.texto)}<span class="tipo">${esc(o.sub)}</span></li>`).join('') : '<li role="option" aria-disabled="true">Sin resultados</li>';
      lista.hidden = false; input.setAttribute('aria-expanded', 'true');
      $$('li[id]', lista).forEach((li, i) => li.addEventListener('mousedown', (e) => { e.preventDefault(); elegir(opciones[i]); }));
    });
    input.addEventListener('keydown', (e) => {
      if (lista.hidden) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + opciones.length) % opciones.length;
        $$('li[id]', lista).forEach((li, i) => li.setAttribute('aria-selected', String(i === sel)));
        input.setAttribute('aria-activedescendant', 'op-' + sel);
      } else if (e.key === 'Enter' && opciones.length) { e.preventDefault(); elegir(opciones[Math.max(sel, 0)]); }
      else if (e.key === 'Escape') cerrar();
    });
    input.addEventListener('blur', () => setTimeout(cerrar, 150));
  }

  // ------------------------------------------------------------ controles
  function renderCategorias() {
    const cont = $('#filtro-categorias');
    const conteo = {};
    for (const c of E.datos.conflictos.conflictos) conteo[c.categoria] = (conteo[c.categoria] || 0) + 1;
    cont.innerHTML = Object.entries(E.datos.conflictos.categorias).map(([k, v]) =>
      `<label class="categoria" title="${esc(v.descripcion)}"><input type="checkbox" data-cat="${esc(k)}" ${E.categorias.has(k) ? 'checked' : ''}>
        <span class="muestra" style="background:${v.color}"></span>${esc(v.nombre)}<span class="n">${conteo[k] || 0}</span></label>`).join('');
    $$('input[data-cat]', cont).forEach((cb) => cb.addEventListener('change', () => {
      if (cb.checked) E.categorias.add(cb.dataset.cat); else E.categorias.delete(cb.dataset.cat);
      E.limiteLista = 40; actualizarMapa(); renderPanel();
    }));
  }

  function renderLeyenda() {
    const cats = Object.entries(E.datos.conflictos.categorias).map(([, v]) => `<div class="item"><svg width="18" height="14"><rect width="18" height="14" rx="3" fill="${v.color}" fill-opacity=".72" stroke="#555" stroke-width=".6"/></svg>${esc(v.nombre)}</div>`).join('');
    $('#leyenda').innerHTML = cats + `
      <div class="item"><svg width="18" height="14"><defs><pattern id="ly" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="5" height="5" fill="#e3e3e3"/><line x1="0" y1="0" x2="0" y2="5" stroke="#5f5f5f" stroke-width="2"/></pattern></defs><rect width="18" height="14" rx="3" fill="url(#ly)"/></svg>País con conflictos de varias categorías</div>
      <div class="item"><svg width="18" height="14"><rect x="1.5" y="1.5" width="15" height="11" rx="2" fill="none" stroke="#0072B2" stroke-width="2.4"/></svg>Borde: el país participa sin ser escenario</div>
      <div class="item"><svg width="18" height="18"><circle cx="9" cy="9" r="6" fill="#D55E00" stroke="#fff" stroke-width="1.6"/></svg>Acontecimiento ubicado en una ciudad</div>
      <div class="item"><svg width="18" height="18"><circle cx="9" cy="9" r="5.5" fill="#fff" stroke="#D55E00" stroke-width="3"/></svg>Ubicado en una provincia o región</div>
      <div class="item"><svg width="22" height="22"><circle cx="11" cy="11" r="9" fill="#fff" stroke="#2d2d2d" stroke-width="2"/><text x="11" y="15" font-size="10" text-anchor="middle" fill="#1b1b1a">3</text></svg>Solo se conoce el país (no es un lugar exacto)</div>
      <div class="item"><svg width="22" height="22"><circle cx="11" cy="11" r="9" fill="#3d3d3b" stroke="#fff" stroke-width="2"/><text x="11" y="15" font-size="10" text-anchor="middle" fill="#fff">12</text></svg>Grupo de acontecimientos (acercá el mapa)</div>
      <div class="item"><svg width="18" height="14"><defs><pattern id="lz" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5" stroke="#0b3d66" stroke-width="1.4"/></pattern></defs><rect width="18" height="14" fill="url(#lz)" stroke="#0b3d66" stroke-dasharray="3 2"/></svg>Zona en disputa de soberanía (Natural Earth)</div>
      <div class="item"><svg width="22" height="22"><circle cx="11" cy="11" r="9" fill="#fff" stroke="#5a5a5a" stroke-width="2"/><text x="11" y="15" font-size="11" text-anchor="middle" fill="#3a3a3a">?</text></svg>Situación detectada automáticamente (sin verificar)</div>
      <p class="nota">Los colores identifican categorías, no gravedad. Los puntos más grandes tienen dos o más fuentes independientes.</p>`;
  }

  function iniciarControles() {
    $$('.segmentado button').forEach((b) => b.addEventListener('click', () => {
      $$('.segmentado button').forEach((x) => x.setAttribute('aria-checked', String(x === b)));
      E.horas = Number(b.dataset.horas); E.limiteLista = 40;
      actualizarMapa(); renderPanel();
    }));
    $$('input[data-capa]').forEach((cb) => cb.addEventListener('change', () => {
      E.capas[cb.dataset.capa] = cb.checked;
      if (cb.dataset.capa === 'base') alternarBase(cb.checked); else visibilidad();
    }));
    $$('.pestanas button').forEach((b) => b.addEventListener('click', () => { E.pestana = b.dataset.pestana; E.vista = null; E.eventoAbierto = null; renderPanel(); }));
    $('#btn-ayuda').addEventListener('click', () => $('#dialogo-ayuda').showModal());
    $('#btn-filtros').addEventListener('click', () => {
      const c = $('#controles');
      c.classList.toggle('abierto');
      $('#btn-filtros').setAttribute('aria-expanded', String(c.classList.contains('abierto')));
    });
    $('#asa').addEventListener('click', () => {
      const p = $('#panel');
      if (p.classList.contains('contraido')) estadoPanel('normal');
      else if (p.classList.contains('expandido')) estadoPanel('contraido');
      else estadoPanel('expandido');
    });
    $('#estado-actualizacion').addEventListener('click', () => { E.pestana = 'fuentes'; E.vista = null; renderPanel(); panelNormal(); });
  }
  function estadoPanel(modo) {
    const p = $('#panel');
    p.classList.toggle('contraido', modo === 'contraido');
    p.classList.toggle('expandido', modo === 'expandido');
    document.body.dataset.panel = modo;
  }
  function panelNormal() { if ($('#panel').classList.contains('contraido')) estadoPanel('normal'); }

  // ------------------------------------------------------- estado de datos
  function estadoActualizacion() {
    const est = E.datos.estado || {};
    const ultimo = est.ultimo_exito ? new Date(est.ultimo_exito).getTime() : null;
    const min = ultimo ? (Date.now() - ultimo) / 60000 : Infinity;
    const hace = ultimo ? (min < 60 ? Math.max(1, Math.round(min)) + ' min' : Math.round(min / 60) + ' h') : '';
    if (!ultimo) return { nivel: 'error', corto: 'Sin datos todavía', movil: 'Sin datos', detalle: 'Todavía no hubo una recopilación exitosa.' };
    if (min > 90) return { nivel: 'error', movil: `Desactualizado (${hace})`, corto: `Desactualizado (${relativo(est.ultimo_exito)})`, detalle: `Los datos están desactualizados: la última recopilación exitosa fue ${relativo(est.ultimo_exito)} (${absoluto(est.ultimo_exito)}). La recopilación automática puede estar fallando.` };
    if (min > 35) return { nivel: 'aviso', movil: `Demorado (${hace})`, corto: `Actualización demorada (${relativo(est.ultimo_exito)})`, detalle: `La última recopilación exitosa fue ${relativo(est.ultimo_exito)}. Las ejecuciones programadas pueden demorarse.` };
    if (!est.ciclo_ok) return { nivel: 'aviso', movil: 'Con fallas', corto: 'Último ciclo con fallas', detalle: 'El último ciclo tuvo fallas; se muestran los datos de la última recopilación exitosa.' };
    if ((est.advertencias || []).length) return { nivel: 'aviso', movil: `Hace ${hace}`, corto: `Actualizado ${relativo(est.ultimo_exito)}`, detalle: 'Actualizado ' + relativo(est.ultimo_exito) + '. Hay advertencias sobre algunas fuentes (ver “Fuentes y estado”).' };
    return { nivel: 'ok', movil: `Hace ${hace}`, corto: `Actualizado ${relativo(est.ultimo_exito)}`, detalle: `Actualizado ${relativo(est.ultimo_exito)} (${absoluto(est.ultimo_exito)}).` };
  }
  function renderEstado() {
    const s = estadoActualizacion();
    const p = $('#estado-actualizacion');
    p.className = 'pastilla pastilla-' + (s.nivel === 'ok' ? 'ok' : s.nivel === 'aviso' ? 'aviso' : 'error');
    p.textContent = esMovil() ? s.movil || s.corto : s.corto;
    p.title = s.detalle + ' Clic para ver el estado de las fuentes.';
    p.style.cursor = 'pointer';
  }

  async function refrescar() {
    try {
      const est = await cargarJSON('datos/estado.json');
      if (est.generado !== E.generado) {
        await cargarDatos();
        renderCategorias(); actualizarMapa(); renderPanel();
      } else {
        E.datos.estado = est;
      }
    } catch (e) { /* se reintenta en el próximo intervalo */ }
    renderEstado();
  }

  // ------------------------------------------------------------------ inicio
  async function iniciar() {
    iniciarControles();
    try {
      const [paises, zonas] = await Promise.all([cargarJSON('geo/paises.geojson'), cargarJSON('geo/zonas.geojson')]);
      E.geo = { paises, zonas };
      calcularBboxes();
      await cargarDatos();
    } catch (e) {
      $('#estado-actualizacion').className = 'pastilla pastilla-error';
      $('#estado-actualizacion').textContent = 'No se pudieron cargar los datos';
      $('#contenido-panel').innerHTML = '<p class="alerta error">No se pudieron cargar los datos del mapa. Reintentá en unos minutos.</p>';
      return;
    }
    renderEstado(); renderCategorias(); renderLeyenda(); iniciarBusqueda(); renderPanel();
    if (window.maplibregl) iniciarMapa();
    if (esMovil()) estadoPanel('contraido'); else estadoPanel('normal');
    setInterval(refrescar, 5 * 60 * 1000);
    setInterval(renderEstado, 60 * 1000);
  }
  iniciar();
})();
