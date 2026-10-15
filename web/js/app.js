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
  const nf = new Intl.NumberFormat('es-AR');
  const IDIOMAS = { es: 'español', en: 'inglés', fr: 'francés', ar: 'árabe', ru: 'ruso', uk: 'ucraniano', zh: 'chino', fa: 'persa',
    tr: 'turco', hi: 'hindi', ur: 'urdu', pt: 'portugués', de: 'alemán', ja: 'japonés', ko: 'coreano', he: 'hebreo', it: 'italiano',
    sw: 'suajili', pl: 'polaco', id: 'indonesio', nl: 'neerlandés', vi: 'vietnamita', th: 'tailandés', bn: 'bengalí' };
  const PRECISION = { ciudad: 'ciudad', provincia: 'provincia/región', pais: 'solo país', desconocida: 'sin ubicación' };
  const METODO = {
    gdelt_evento: 'Lugar del hecho según la codificación automática de eventos de GDELT',
    titular: 'Lugar nombrado en el titular',
    gkg_titular: 'Lugar nombrado en el titular e identificado por el geocodificador de GDELT',
    pais_mencionado: 'Solo se conoce el país (mencionado en el texto)',
    pais_del_conflicto: 'Ubicación no especificada: se asigna al país del conflicto',
    pais: 'Solo se conoce el país',
  };
  // Nombres cortos de las categorías para la leyenda-filtro.
  const CORTO = { guerra_estados: 'Entre Estados', guerra_civil: 'Guerra civil', otro_armado: 'Otro armado',
    disputa_territorial: 'Territorial', tension_diplomatica: 'Diplomática', sanciones_economico: 'Económica' };
  const HORAS_RECIENTE = 3; // los puntos de novedades más recientes laten
  const VISTA_MUNDO = [[-150, -48], [160, 70]];

  const movimientoReducido = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const temaOscuro = () => {
    const t = document.documentElement.dataset.theme;
    return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  };
  // Paletas del mapa (claro y oscuro). Los colores de categoría no cambian.
  const PALETAS = {
    claro: { agua: '#d6e2ec', tierra: '#f7f6f2', borde: '#b3b9c0', limite: '#c4c9cf', etiqueta: '#3c424a', halo: 'rgba(255,255,255,0.9)',
      ciudad: '#2a2e33', region: '#737a83', grupo: '#2e3238', grupoTexto: '#ffffff', grupoBorde: 'rgba(255,255,255,0.95)',
      anillo: '#6b727b', anilloFondo: 'rgba(255,255,255,0.8)', anilloTexto: '#2e3238', puntoBorde: '#ffffff', resaltado: '#111111',
      mar: '#2c4a66', rayadoDoc: 'rgba(30,30,30,0.38)', rayadoZona: 'rgba(11,61,102,0.55)', bordeDoc: 'rgba(40,40,40,0.65)', bordeZona: '#0b3d66' },
    oscuro: { agua: '#0d141b', tierra: '#1e2329', borde: '#3d454e', limite: '#2f363e', etiqueta: '#c9cfd6', halo: 'rgba(13,20,27,0.92)',
      ciudad: '#d7dce2', region: '#8c949d', grupo: '#e8ecf0', grupoTexto: '#14181d', grupoBorde: 'rgba(20,24,29,0.9)',
      anillo: '#99a2ac', anilloFondo: 'rgba(30,35,41,0.88)', anilloTexto: '#e8ecf0', puntoBorde: '#14181d', resaltado: '#ffffff',
      mar: '#93b8da', rayadoDoc: 'rgba(235,238,242,0.34)', rayadoZona: 'rgba(130,185,235,0.6)', bordeDoc: 'rgba(200,206,214,0.7)', bordeZona: '#7fb2e0' },
  };
  const paleta = () => PALETAS[temaOscuro() ? 'oscuro' : 'claro'];

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
    geo: { paises: null, zonas: null, regiones: null, mares: null, ciudades: null },
    idx: {},
    reg: { info: {}, cajas: {}, porPais: {}, deEvento: {}, conteo: {}, listo: false }, // regiones admin-1
    horas: 24,
    categorias: new Set(),
    capas: { paises: true, eventos: true, zonas: true, regiones: true, afectadas: true, candidatos: false, base: false },
    pestana: 'novedades',
    vista: null, // {tipo:'conflicto'|'pais'|'region'|'candidato', id}
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
  const focoActual = () => (E.vista && E.vista.tipo === 'conflicto' ? E.vista.id : null);

  // ------------------------------------------------------------------ datos
  async function cargarJSON(ruta) {
    const r = await fetch(ruta + (ruta.includes('?') ? '&' : '?') + 'v=' + Math.floor(Date.now() / 60000), { cache: 'no-store' });
    if (!r.ok) throw new Error(ruta + ': HTTP ' + r.status);
    return r.json();
  }

  // Archivos geográficos estáticos: se permite la caché del navegador (cambian solo con el código).
  const VERSION_GEO = '2';
  async function cargarEstatico(ruta) {
    const r = await fetch(ruta + '?g=' + VERSION_GEO);
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
    const idx = { conflicto: {}, evento: {}, eventosPorConflicto: {}, paisConflictos: {}, articulo: E.datos.eventos.articulos || {} };
    for (const c of E.datos.conflictos.conflictos) {
      idx.conflicto[c.id] = c;
      for (const p of c.paises_escenario) (idx.paisConflictos[p] = idx.paisConflictos[p] || []).push({ id: c.id, rol: 'escenario' });
      for (const p of c.paises_participantes) (idx.paisConflictos[p] = idx.paisConflictos[p] || []).push({ id: c.id, rol: 'participante' });
    }
    for (const ev of E.datos.eventos.eventos) {
      idx.evento[ev.id] = ev;
      (idx.eventosPorConflicto[ev.conflicto] = idx.eventosPorConflicto[ev.conflicto] || []).push(ev);
    }
    E.idx = idx;
    if (!E.categorias.size) Object.keys(E.datos.conflictos.categorias).forEach((c) => E.categorias.add(c));
  }

  const limitePeriodo = (horas = E.horas) => new Date(Date.now() - horas * 3600e3).toISOString();
  function eventosFiltrados(extra) {
    const limite = limitePeriodo();
    return E.datos.eventos.eventos.filter((ev) => {
      const c = E.idx.conflicto[ev.conflicto];
      if (!c || !E.categorias.has(c.categoria)) return false;
      if ((ev.referencia || '') < limite) return false;
      return !extra || extra(ev);
    }).sort((a, b) => (b.referencia || '').localeCompare(a.referencia || ''));
  }
  const esReciente = (ev) => ev.referencia && Date.now() - new Date(ev.referencia).getTime() < HORAS_RECIENTE * 3600e3;

  // ------------------------------------------------------------------ mapa
  function patron(fondo, linea, tam = 8, grosor = 2, inverso = false) {
    const c = document.createElement('canvas');
    c.width = c.height = tam;
    const x = c.getContext('2d');
    if (fondo) { x.fillStyle = fondo; x.fillRect(0, 0, tam, tam); }
    if (inverso) { x.translate(tam, 0); x.scale(-1, 1); } // diagonal en el otro sentido
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

  // Botón "vista mundial" junto a los controles de zoom.
  class ControlMundo {
    onAdd() {
      this._c = el(`<div class="maplibregl-ctrl maplibregl-ctrl-group boton-mundo"><button type="button" title="Ver todo el mundo" aria-label="Ver todo el mundo"><span class="maplibregl-ctrl-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3.2 3.4 3.2 14.6 0 18M12 3c-3.2 3.4-3.2 14.6 0 18"/></svg></span></button></div>`);
      $('button', this._c).addEventListener('click', vistaMundo);
      return this._c;
    }
    onRemove() { this._c.remove(); }
  }
  function vistaMundo() { if (E.mapaListo) E.mapa.fitBounds(VISTA_MUNDO, { padding: rellenoMapa(), duration: 900 }); }

  function iniciarMapa() {
    const base = location.href.replace(/[#?].*$/, '').replace(/[^/]*$/, '');
    const P = paleta();
    const mapa = new maplibregl.Map({
      container: 'mapa',
      style: {
        version: 8,
        glyphs: base + 'fonts/{fontstack}/{range}.pbf',
        sources: {},
        layers: [{ id: 'fondo', type: 'background', paint: { 'background-color': P.agua } }],
      },
      center: [20, 20], zoom: 1.4, minZoom: 0.8, maxZoom: 11,
      attributionControl: false, dragRotate: false, pitchWithRotate: false,
      renderWorldCopies: true,
    });
    mapa.touchZoomRotate.disableRotation();
    mapa.addControl(new ControlMundo(), 'bottom-right');
    mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    mapa.addControl(new maplibregl.AttributionControl({
      compact: true,
      customAttribution: 'Noticias: <a href="https://www.gdeltproject.org/" target="_blank" rel="noopener">The GDELT Project</a> y feeds RSS · Geografía: <a href="https://www.naturalearthdata.com/" target="_blank" rel="noopener">Natural Earth</a>',
    }), 'bottom-left');
    E.mapa = mapa;
    window.mapaDeConflictos = E; // acceso para depuración desde la consola del navegador
    mapa.on('load', () => {
      const attrib = document.querySelector('.maplibregl-ctrl-attrib');
      if (attrib) attrib.classList.remove('maplibregl-compact-show');
      mapa.fitBounds(VISTA_MUNDO, { padding: rellenoMapa(), duration: 0 });
      mapa.addImage('rayado-zona', patron(null, P.rayadoZona, 10, 1.6), { pixelRatio: 1 });
      mapa.addImage('rayado-doc', patron(null, P.rayadoDoc, 7, 1.1, true), { pixelRatio: 1 });
      agregarCapas();
      E.mapaListo = true;
      agregarCapasDetalle();
      actualizarMapa();
      interacciones();
      iniciarPulso();
    });
    mapa.on('error', (e) => {
      if (e && e.sourceId === 'ofm') {
        const cb = $('input[data-capa="base"]');
        if (cb && cb.checked) {
          cb.checked = false; E.capas.base = false; alternarBase(false);
          avisoCapas('No se pudo cargar el mapa base detallado (OpenFreeMap). Se sigue usando el mapa simple.');
        }
      }
    });
    const mq = matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', aplicarPaleta);
  }

  const esMovil = () => matchMedia('(max-width: 760px)').matches;
  const panelVisible = () => document.body.dataset.escritorio !== 'oculto';
  function rellenoMapa() {
    const cab = $('#controles');
    const abajoCab = cab ? cab.getBoundingClientRect().bottom : 140;
    if (esMovil()) {
      const p = $('#panel');
      const alto = p ? p.getBoundingClientRect().height : window.innerHeight * 0.44;
      return { top: Math.min(abajoCab + 8, window.innerHeight * 0.3), bottom: Math.min(alto + 48, window.innerHeight * 0.62), left: 16, right: 16 };
    }
    return { top: abajoCab + 12, bottom: 64, left: 40, right: panelVisible() ? 384 + 56 : 56 };
  }

  function avisoCapas(texto) {
    let a = $('#aviso-capas');
    if (!a) { a = el('<p id="aviso-capas" class="alerta aviso"></p>'); $('#popover-capas').prepend(a); }
    a.textContent = texto;
  }

  const vacio = () => ({ type: 'FeatureCollection', features: [] });

  // Opacidad de los países: color pleno al ver el mundo y atenuado al acercar (para leer las regiones);
  // en modo foco, los países ajenos al conflicto elegido se atenúan.
  function opacidadPaises() {
    const foco = ['case', ['==', ['get', 'foco'], 0], 0.16, 1];
    const hover = ['case', ['boolean', ['feature-state', 'hover'], false], 1.3, 1];
    const base = E.capas.base ? 0.4 : temaOscuro() ? 0.56 : 0.58;
    const cerca = E.capas.regiones && E.reg.listo ? 0.26 : base;
    return ['interpolate', ['linear'], ['zoom'], 2.2, ['*', base, foco, hover], 3.8, ['*', cerca, foco, hover]];
  }

  function agregarCapas() {
    const m = E.mapa, P = paleta();
    m.addSource('paises', { type: 'geojson', data: E.geo.paises, promoteId: 'id' });
    m.addSource('zonas', { type: 'geojson', data: E.geo.zonas });
    m.addSource('etiquetas', { type: 'geojson', data: vacio() });
    // 'rec' cuenta las novedades de las últimas horas también dentro de cada grupo (para que el grupo lata).
    m.addSource('eventos', { type: 'geojson', data: vacio(), cluster: true, clusterRadius: 46, clusterMaxZoom: 7,
      clusterProperties: { rec: ['+', ['get', 'rec']] } });
    m.addSource('eventos-pais', { type: 'geojson', data: vacio() });
    m.addSource('resaltado', { type: 'geojson', data: vacio() });
    m.addSource('candidatos', { type: 'geojson', data: vacio() });
    const color = expresionColor('cat');
    m.addLayer({ id: 'tierra', type: 'fill', source: 'paises', paint: { 'fill-color': P.tierra } });
    m.addLayer({ id: 'paises-escenario', type: 'fill', source: 'paises', filter: ['==', ['get', 'rol'], 'escenario'],
      paint: { 'fill-color': color, 'fill-opacity': opacidadPaises() } });
    m.addLayer({ id: 'paises-participante', type: 'line', source: 'paises', filter: ['==', ['get', 'rol'], 'participante'],
      paint: { 'line-color': color, 'line-width': ['interpolate', ['linear'], ['zoom'], 1.5, 1, 4, 2.2], 'line-offset': 0.5,
        'line-opacity': ['case', ['==', ['get', 'foco'], 0], 0.15, 0.75] } });
    m.addLayer({ id: 'paises-borde', type: 'line', source: 'paises',
      paint: { 'line-color': P.borde, 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.35, 6, 1] } });
    m.addLayer({ id: 'paises-resaltado', type: 'line', source: 'paises', filter: ['==', ['get', 'id'], '__ninguno__'],
      paint: { 'line-color': P.resaltado, 'line-width': 1.8 } });
    m.addLayer({ id: 'zonas-relleno', type: 'fill', source: 'zonas', minzoom: 2.8, paint: { 'fill-pattern': 'rayado-zona', 'fill-opacity': 0.9 } });
    m.addLayer({ id: 'zonas-borde', type: 'line', source: 'zonas', minzoom: 2.8, paint: { 'line-color': P.bordeZona, 'line-width': 1.1, 'line-dasharray': [3, 2] } });
    m.addLayer({ id: 'candidatos-borde', type: 'line', source: 'paises', filter: ['in', ['get', 'id'], ['literal', []]],
      paint: { 'line-color': '#7a7a7a', 'line-width': 2, 'line-dasharray': [2, 2] } });
    m.addLayer({ id: 'candidatos-punto', type: 'circle', source: 'candidatos',
      paint: { 'circle-radius': 10, 'circle-color': P.anilloFondo, 'circle-stroke-color': P.anillo, 'circle-stroke-width': 1.6 } });
    m.addLayer({ id: 'candidatos-texto', type: 'symbol', source: 'candidatos',
      layout: { 'text-field': '?', 'text-font': ['Open Sans Semibold'], 'text-size': 12, 'text-allow-overlap': true },
      paint: { 'text-color': P.anilloTexto } });
    // Etiquetas: con zoom bajo, solo los países con conflictos; al acercar, todos.
    const etiqueta = { 'text-field': ['get', 'nombre'], 'text-font': ['Open Sans Semibold'], 'text-max-width': 8, 'text-padding': 4 };
    m.addLayer({ id: 'etiquetas-conflicto', type: 'symbol', source: 'etiquetas', minzoom: 1.9, maxzoom: 3.8,
      filter: ['==', ['get', 'conflicto'], 1],
      layout: { ...etiqueta, 'text-size': ['interpolate', ['linear'], ['zoom'], 2, 10, 3.8, 12] },
      paint: { 'text-color': P.etiqueta, 'text-halo-color': P.halo, 'text-halo-width': 1.3 } });
    m.addLayer({ id: 'etiquetas-paises', type: 'symbol', source: 'etiquetas', minzoom: 3.8,
      layout: { ...etiqueta, 'text-size': ['interpolate', ['linear'], ['zoom'], 3.8, 12, 7, 14] },
      paint: { 'text-color': P.etiqueta, 'text-halo-color': P.halo, 'text-halo-width': 1.3 } });
    // Novedades ubicadas solo a nivel país: círculo gris discreto (no es un lugar exacto).
    m.addLayer({ id: 'eventos-pais', type: 'circle', source: 'eventos-pais', minzoom: 2.5,
      paint: { 'circle-radius': ['interpolate', ['linear'], ['get', 'n'], 1, 9, 20, 13, 80, 18],
        'circle-color': P.anilloFondo, 'circle-stroke-color': P.anillo, 'circle-stroke-width': 1.3 } });
    m.addLayer({ id: 'eventos-pais-texto', type: 'symbol', source: 'eventos-pais', minzoom: 2.5,
      layout: { 'text-field': ['to-string', ['get', 'n']], 'text-font': ['Open Sans Semibold'], 'text-size': 10.5, 'text-allow-overlap': true },
      paint: { 'text-color': P.anilloTexto } });
    // Pulso de las novedades recientes (debajo de los puntos y de los grupos que las contienen).
    m.addLayer({ id: 'eventos-pulso', type: 'circle', source: 'eventos', filter: ['>', ['get', 'rec'], 0],
      paint: { 'circle-radius': radioPulso(0), 'circle-color': ['case', ['has', 'point_count'], P.grupo, color], 'circle-opacity': 0, 'circle-stroke-width': 0 } });
    m.addLayer({ id: 'grupos', type: 'circle', source: 'eventos', filter: ['has', 'point_count'],
      paint: { 'circle-color': P.grupo, 'circle-opacity': 0.88, 'circle-stroke-color': P.grupoBorde, 'circle-stroke-width': 1.5,
        'circle-radius': ['step', ['get', 'point_count'], 12, 10, 15, 50, 19] } });
    m.addLayer({ id: 'grupos-texto', type: 'symbol', source: 'eventos', filter: ['has', 'point_count'],
      layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-font': ['Open Sans Semibold'], 'text-size': 11.5, 'text-allow-overlap': true },
      paint: { 'text-color': P.grupoTexto } });
    m.addLayer({ id: 'eventos-punto', type: 'circle', source: 'eventos', filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, ['case', ['>=', ['get', 'fuentes'], 2], 5.5, 4.5], 7, ['case', ['>=', ['get', 'fuentes'], 2], 8, 6.5]],
        'circle-color': ['case', ['==', ['get', 'precision'], 'provincia'], P.tierra, color],
        'circle-stroke-color': ['case', ['==', ['get', 'precision'], 'provincia'], color, P.puntoBorde],
        'circle-stroke-width': ['case', ['==', ['get', 'precision'], 'provincia'], 2.6, 1.4],
      } });
    m.addLayer({ id: 'resaltado-anillo', type: 'circle', source: 'resaltado',
      paint: { 'circle-radius': 13, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': P.resaltado, 'circle-stroke-width': 2.4 } });
  }

  function agregarCapasDetalle() {
    const m = E.mapa;
    if (!E.mapaListo || !E.reg.listo || m.getSource('regiones')) return;
    const P = paleta();
    const colorEstado = ['match', ['feature-state', 'cat']];
    for (const [k, v] of Object.entries(E.datos.conflictos.categorias)) colorEstado.push(k, v.color);
    colorEstado.push('#7a7f86');
    const n = ['coalesce', ['feature-state', 'n'], 0];
    m.addSource('regiones', { type: 'geojson', data: E.geo.regiones, promoteId: 'id' });
    m.addSource('regiones-et', { type: 'geojson', data: { type: 'FeatureCollection', features: Object.values(E.reg.info).filter((r) => r.et)
      .map((r) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: r.et }, properties: { id: r.id, n: r.n } })) } });
    m.addSource('mares', { type: 'geojson', data: E.geo.mares || vacio() });
    m.addSource('ciudades', { type: 'geojson', data: E.geo.ciudades || vacio() });
    // Intensidad por cantidad de novedades en la región (más intenso = más novedades). Aparece al acercar.
    m.addLayer({ id: 'regiones-actividad', type: 'fill', source: 'regiones', minzoom: 2.6,
      paint: { 'fill-color': colorEstado, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 2.6, 0,
        3.4, ['case', ['>', n, 0], ['step', n, 0.5, 3, 0.66, 6, 0.8, 12, 0.92], 0]] } }, 'paises-participante');
    m.addLayer({ id: 'regiones-limites', type: 'line', source: 'regiones', minzoom: 2.8,
      paint: { 'line-color': P.limite, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.3, 7, 0.9] } }, 'paises-borde');
    m.addLayer({ id: 'regiones-doc', type: 'fill', source: 'regiones', minzoom: 3, filter: ['in', ['get', 'id'], ['literal', []]],
      paint: { 'fill-pattern': 'rayado-doc', 'fill-opacity': 0.85 } }, 'zonas-relleno');
    m.addLayer({ id: 'regiones-doc-borde', type: 'line', source: 'regiones', minzoom: 3, filter: ['in', ['get', 'id'], ['literal', []]],
      paint: { 'line-color': P.bordeDoc, 'line-width': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 1.1] } }, 'zonas-relleno');
    m.addLayer({ id: 'mares-doc', type: 'fill', source: 'mares', minzoom: 2.4, filter: ['in', ['get', 'id'], ['literal', []]],
      paint: { 'fill-pattern': 'rayado-doc', 'fill-opacity': 0.35 } }, 'zonas-relleno');
    m.addLayer({ id: 'mares-doc-borde', type: 'line', source: 'mares', minzoom: 2.4, filter: ['in', ['get', 'id'], ['literal', []]],
      paint: { 'line-color': P.mar, 'line-width': 1, 'line-dasharray': [2, 2] } }, 'zonas-relleno');
    m.addLayer({ id: 'regiones-sel', type: 'line', source: 'regiones', filter: ['in', ['get', 'id'], ['literal', []]],
      paint: { 'line-color': P.resaltado, 'line-width': 2.4 } }, 'zonas-relleno');
    m.addLayer({ id: 'mares-texto', type: 'symbol', source: 'mares', minzoom: 2.4, filter: ['in', ['get', 'id'], ['literal', []]],
      layout: { 'text-field': ['get', 'n'], 'text-font': ['Open Sans Semibold'], 'text-size': 11, 'text-max-width': 7 },
      paint: { 'text-color': P.mar, 'text-halo-color': P.halo, 'text-halo-width': 1.2 } }, 'eventos-pais');
    m.addLayer({ id: 'ciudades-punto', type: 'circle', source: 'ciudades', minzoom: 3.4,
      filter: ['<=', ['get', 'r'], ['step', ['zoom'], 1, 4.5, 2, 5.5, 3]],
      paint: { 'circle-radius': ['case', ['==', ['get', 'cap'], 1], 2.8, 2], 'circle-color': P.ciudad, 'circle-stroke-color': P.halo, 'circle-stroke-width': 1 } }, 'eventos-pais');
    m.addLayer({ id: 'ciudades-texto', type: 'symbol', source: 'ciudades', minzoom: 3.4,
      filter: ['<=', ['get', 'r'], ['step', ['zoom'], 1, 4.5, 2, 5.5, 3]],
      layout: { 'text-field': ['get', 'n'], 'text-font': ['Open Sans Semibold'], 'text-size': ['interpolate', ['linear'], ['zoom'], 3.4, 10, 8, 13],
        'text-anchor': 'left', 'text-offset': [0.5, 0], 'text-max-width': 8, 'text-padding': 3, 'text-optional': true },
      paint: { 'text-color': P.ciudad, 'text-halo-color': P.halo, 'text-halo-width': 1.2 } }, 'eventos-pais');
    m.addLayer({ id: 'regiones-etiquetas', type: 'symbol', source: 'regiones-et', minzoom: 4.6,
      layout: { 'text-field': ['get', 'n'], 'text-font': ['Open Sans Semibold'], 'text-size': ['interpolate', ['linear'], ['zoom'], 4.6, 9.5, 8, 12],
        'text-max-width': 7, 'text-padding': 8, 'text-letter-spacing': 0.05, 'text-transform': 'uppercase' },
      paint: { 'text-color': P.region, 'text-halo-color': P.halo, 'text-halo-width': 1.1 } }, 'ciudades-punto');
    actualizarMapa();
  }

  // Cambia los colores del mapa al pasar de tema claro a oscuro (o al revés).
  function aplicarPaleta() {
    const m = E.mapa;
    if (!E.mapaListo) return;
    const P = paleta();
    const pintar = (capa, prop, valor) => m.getLayer(capa) && m.setPaintProperty(capa, prop, valor);
    pintar('fondo', 'background-color', P.agua);
    pintar('tierra', 'fill-color', P.tierra);
    pintar('paises-borde', 'line-color', P.borde);
    pintar('paises-resaltado', 'line-color', P.resaltado);
    ['etiquetas-conflicto', 'etiquetas-paises'].forEach((c) => { pintar(c, 'text-color', P.etiqueta); pintar(c, 'text-halo-color', P.halo); });
    pintar('eventos-pais', 'circle-color', P.anilloFondo); pintar('eventos-pais', 'circle-stroke-color', P.anillo);
    pintar('eventos-pais-texto', 'text-color', P.anilloTexto);
    pintar('candidatos-punto', 'circle-color', P.anilloFondo); pintar('candidatos-punto', 'circle-stroke-color', P.anillo);
    pintar('candidatos-texto', 'text-color', P.anilloTexto);
    pintar('grupos', 'circle-color', P.grupo); pintar('grupos', 'circle-stroke-color', P.grupoBorde); pintar('grupos-texto', 'text-color', P.grupoTexto);
    const color = expresionColor('cat');
    pintar('eventos-punto', 'circle-color', ['case', ['==', ['get', 'precision'], 'provincia'], P.tierra, color]);
    pintar('eventos-punto', 'circle-stroke-color', ['case', ['==', ['get', 'precision'], 'provincia'], color, P.puntoBorde]);
    pintar('resaltado-anillo', 'circle-stroke-color', P.resaltado);
    pintar('zonas-borde', 'line-color', P.bordeZona);
    pintar('regiones-limites', 'line-color', P.limite);
    pintar('regiones-doc-borde', 'line-color', P.bordeDoc);
    pintar('regiones-sel', 'line-color', P.resaltado);
    pintar('mares-doc-borde', 'line-color', P.mar);
    pintar('mares-texto', 'text-color', P.mar); pintar('mares-texto', 'text-halo-color', P.halo);
    pintar('ciudades-punto', 'circle-color', P.ciudad); pintar('ciudades-punto', 'circle-stroke-color', P.halo);
    pintar('ciudades-texto', 'text-color', P.ciudad); pintar('ciudades-texto', 'text-halo-color', P.halo);
    pintar('regiones-etiquetas', 'text-color', P.region); pintar('regiones-etiquetas', 'text-halo-color', P.halo);
    if (m.hasImage('rayado-doc')) m.updateImage('rayado-doc', patron(null, P.rayadoDoc, 7, 1.1, true));
    if (m.hasImage('rayado-zona')) m.updateImage('rayado-zona', patron(null, P.rayadoZona, 10, 1.6));
    if (m.getLayer('ofm-agua')) pintar('ofm-agua', 'fill-color', P.agua);
    visibilidad();
  }

  function puntosEtiquetas(conConflicto) {
    const et = E.datos.conflictos.etiquetas_paises || {};
    return { type: 'FeatureCollection', features: Object.entries(et).map(([iso, c]) => ({
      type: 'Feature', geometry: { type: 'Point', coordinates: c },
      properties: { id: iso, nombre: nombrePais(iso), conflicto: conConflicto.has(iso) ? 1 : 0 } })) };
  }

  // Cantidad de novedades del período por categoría (para la leyenda-filtro).
  function conteoPorCategoria() {
    const limite = limitePeriodo(), n = {};
    for (const ev of E.datos.eventos.eventos) {
      if ((ev.referencia || '') < limite) continue;
      const c = E.idx.conflicto[ev.conflicto];
      if (c) n[c.categoria] = (n[c.categoria] || 0) + 1;
    }
    return n;
  }

  function actualizarMapa() {
    if (!E.mapaListo) return;
    const m = E.mapa;
    const foco = focoActual();
    const cf = foco ? E.idx.conflicto[foco] : null;
    const evsTodos = eventosFiltrados();
    const evs = cf ? evsTodos.filter((ev) => ev.conflicto === foco) : evsTodos;
    // Países: si son escenario de conflictos de varias categorías, se usa la que tiene más novedades.
    const orden = Object.keys(E.datos.conflictos.categorias);
    const esc = {}, part = {};
    for (const c of E.datos.conflictos.conflictos) {
      if (c.estado !== 'activo' || !E.categorias.has(c.categoria)) continue;
      c.paises_escenario.forEach((p) => (esc[p] = esc[p] || new Set()).add(c.categoria));
      c.paises_participantes.forEach((p) => (part[p] = part[p] || new Set()).add(c.categoria));
    }
    const porPaisCat = {};
    for (const ev of evsTodos) {
      const p = (ev.lugar || {}).pais;
      if (!p) continue;
      const cat = E.idx.conflicto[ev.conflicto].categoria;
      const x = porPaisCat[p] = porPaisCat[p] || {};
      x[cat] = (x[cat] || 0) + 1;
    }
    const elegirCat = (iso, cats) => [...cats].sort((a, b) => ((porPaisCat[iso] || {})[b] || 0) - ((porPaisCat[iso] || {})[a] || 0)
      || orden.indexOf(a) - orden.indexOf(b))[0];
    const enFoco = cf ? new Set([...cf.paises_escenario, ...cf.paises_participantes]) : null;
    const conConflicto = new Set();
    const features = E.geo.paises.features.map((f) => {
      const id = f.properties.id;
      let rol = esc[id] ? 'escenario' : part[id] ? 'participante' : null;
      let cat = rol ? elegirCat(id, esc[id] || part[id]) : null;
      if (cf) {
        if (cf.paises_escenario.includes(id)) { rol = 'escenario'; cat = cf.categoria; }
        else if (cf.paises_participantes.includes(id)) { rol = 'participante'; cat = cf.categoria; }
      }
      if (cf ? enFoco.has(id) : rol) conConflicto.add(id);
      return { type: 'Feature', geometry: f.geometry, properties: { id, nombre: f.properties.nombre, rol, cat, foco: !cf || enFoco.has(id) ? 1 : 0 } };
    });
    m.getSource('paises').setData({ type: 'FeatureCollection', features });
    m.getSource('etiquetas').setData(puntosEtiquetas(conConflicto));
    // Novedades.
    const puntos = [], porPais = {};
    for (const ev of evs) {
      const l = ev.lugar || {};
      const c = E.idx.conflicto[ev.conflicto];
      if (l.coord) {
        const f = { type: 'Feature', geometry: { type: 'Point', coordinates: l.coord },
          properties: { id: ev.id, cat: c.categoria, precision: l.precision, fuentes: ev.fuentes_independientes, rec: esReciente(ev) ? 1 : 0 } };
        puntos.push(f);
      } else if (l.pais) {
        (porPais[l.pais] = porPais[l.pais] || []).push(ev.id);
      }
    }
    m.getSource('eventos').setData({ type: 'FeatureCollection', features: puntos });
    const et = E.datos.conflictos.etiquetas_paises || {};
    m.getSource('eventos-pais').setData({ type: 'FeatureCollection', features: Object.entries(porPais)
      .filter(([iso]) => et[iso]).map(([iso, ids]) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: et[iso] },
        properties: { pais: iso, n: ids.length } })) });
    actualizarRegiones(evs);
    // Zonas en disputa: en modo foco, solo las del conflicto elegido.
    const filtroZonas = cf ? ['in', ['get', 'id'], ['literal', cf.zonas || []]] : null;
    m.setFilter('zonas-relleno', filtroZonas);
    m.setFilter('zonas-borde', filtroZonas);
    // Candidatos.
    const cands = (E.datos.candidatos.candidatos || []);
    m.setFilter('candidatos-borde', ['in', ['get', 'id'], ['literal', cands.map((c) => c.pais)]]);
    m.getSource('candidatos').setData({ type: 'FeatureCollection', features: cands.filter((c) => c.etiqueta)
      .map((c) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: c.etiqueta }, properties: { id: c.id } })) });
    // En modo foco, las zonas del conflicto se ven aun con zoom bajo.
    const rango = (capa, min) => m.getLayer(capa) && m.setLayerZoomRange(capa, cf ? 0 : min, 24);
    rango('zonas-relleno', 2.8); rango('zonas-borde', 2.8);
    rango('regiones-doc', 3); rango('regiones-doc-borde', 3);
    rango('mares-doc', 2.4); rango('mares-doc-borde', 2.4); rango('mares-texto', 2.4);
    visibilidad();
    renderCategorias();
  }

  // Colorea las regiones según las novedades del período y marca las documentadas.
  function actualizarRegiones(evs) {
    const m = E.mapa;
    if (!m.getSource('regiones')) return;
    const conteo = conteoRegiones(evs);
    E.reg.conteo = conteo;
    m.removeFeatureState({ source: 'regiones' });
    for (const [id, c] of Object.entries(conteo)) {
      m.setFeatureState({ source: 'regiones', id }, { n: c.n, cat: c.cats.size === 1 ? [...c.cats][0] : 'varias' });
    }
    const ids = new Set(), mares = new Set();
    for (const { grupo } of regionesDocumentadas(focoActual())) { grupo.ids.forEach((i) => ids.add(i)); grupo.mares.forEach((x) => mares.add(x)); }
    m.setFilter('regiones-doc', ['in', ['get', 'id'], ['literal', [...ids]]]);
    m.setFilter('regiones-doc-borde', ['in', ['get', 'id'], ['literal', [...ids]]]);
    ['mares-doc', 'mares-doc-borde', 'mares-texto'].forEach((l) => m.setFilter(l, ['in', ['get', 'id'], ['literal', [...mares]]]));
    resaltarSeleccion();
  }

  // Contorno de la región que se está viendo.
  function resaltarSeleccion() {
    const m = E.mapa;
    if (!m || !m.getLayer('regiones-sel')) return;
    const v = E.vista;
    m.setFilter('regiones-sel', ['in', ['get', 'id'], ['literal', v && v.tipo === 'region' ? [v.id] : []]]);
    m.setFilter('paises-resaltado', ['==', ['get', 'id'], v && v.tipo === 'pais' ? v.id : '__ninguno__']);
  }

  function visibilidad() {
    const m = E.mapa;
    if (!E.mapaListo) return;
    const vis = (ids, on) => ids.forEach((id) => m.getLayer(id) && m.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'));
    vis(['paises-escenario', 'paises-participante'], E.capas.paises);
    vis(['eventos-punto', 'grupos', 'grupos-texto', 'eventos-pais', 'eventos-pais-texto', 'eventos-pulso', 'resaltado-anillo'], E.capas.eventos);
    vis(['zonas-relleno', 'zonas-borde'], E.capas.zonas);
    vis(['candidatos-borde', 'candidatos-punto', 'candidatos-texto'], E.capas.candidatos && !focoActual());
    vis(['regiones-actividad'], E.capas.regiones);
    vis(['regiones-doc', 'regiones-doc-borde', 'mares-doc', 'mares-doc-borde', 'mares-texto'], E.capas.afectadas);
    vis(['ciudades-punto', 'ciudades-texto'], !E.capas.base);
    if (m.getLayer('paises-escenario')) m.setPaintProperty('paises-escenario', 'fill-opacity', opacidadPaises());
  }

  // Radio del pulso: el del punto o grupo más un extra que crece con la animación.
  const radioPulso = (extra) => ['+', ['case', ['has', 'point_count'], ['step', ['get', 'point_count'], 12, 10, 15, 50, 19], 6], extra];

  // Pulso suave en las novedades de las últimas horas (se desactiva si se pidió reducir el movimiento).
  function iniciarPulso() {
    if (movimientoReducido()) return;
    const t0 = performance.now();
    let ultimo = 0;
    const paso = (t) => {
      requestAnimationFrame(paso);
      if (document.hidden || t - ultimo < 50 || !E.mapa.getLayer('eventos-pulso')) return;
      ultimo = t;
      const p = ((t - t0) % 2200) / 2200;
      E.mapa.setPaintProperty('eventos-pulso', 'circle-radius', radioPulso(12 * p));
      E.mapa.setPaintProperty('eventos-pulso', 'circle-opacity', 0.38 * (1 - p));
    };
    requestAnimationFrame(paso);
  }

  // Anillo sobre una novedad (al pasar el mouse por su tarjeta o por el punto).
  function resaltarEvento(id) {
    if (!E.mapaListo) return;
    const ev = id && E.idx.evento[id];
    const l = (ev && ev.lugar) || {};
    const coord = l.coord || (l.pais && (E.datos.conflictos.etiquetas_paises || {})[l.pais]);
    E.mapa.getSource('resaltado').setData(coord ? { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: coord }, properties: {} }] } : vacio());
  }

  function alternarBase(on) {
    const m = E.mapa;
    if (!E.mapaListo) return;
    const P = paleta();
    const capas = ['ofm-agua', 'ofm-limites', 'ofm-rutas', 'ofm-lugares'];
    if (!on) { capas.forEach((id) => m.getLayer(id) && m.removeLayer(id)); if (m.getSource('ofm')) m.removeSource('ofm'); visibilidad(); return; }
    if (!m.getSource('ofm')) {
      m.addSource('ofm', { type: 'vector', url: 'https://tiles.openfreemap.org/planet',
        attribution: '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> Datos de <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>' });
    }
    const antes = 'paises-borde';
    m.addLayer({ id: 'ofm-agua', type: 'fill', source: 'ofm', 'source-layer': 'water', paint: { 'fill-color': P.agua } }, antes);
    m.addLayer({ id: 'ofm-limites', type: 'line', source: 'ofm', 'source-layer': 'boundary', minzoom: 3,
      filter: ['==', ['get', 'admin_level'], 4], paint: { 'line-color': P.limite, 'line-width': 0.7, 'line-dasharray': [3, 2] } }, antes);
    m.addLayer({ id: 'ofm-rutas', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 5,
      filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary']]],
      paint: { 'line-color': temaOscuro() ? '#5b5440' : '#c9b99a', 'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.5, 10, 2] } }, antes);
    m.addLayer({ id: 'ofm-lugares', type: 'symbol', source: 'ofm', 'source-layer': 'place', minzoom: 4.5,
      filter: ['in', ['get', 'class'], ['literal', ['city', 'town']]],
      layout: { 'text-field': ['coalesce', ['get', 'name:es'], ['get', 'name:latin'], ['get', 'name']], 'text-font': ['Open Sans Semibold'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 5, 10, 10, 13], 'text-max-width': 8 },
      paint: { 'text-color': P.ciudad, 'text-halo-color': P.halo, 'text-halo-width': 1.2 } }, 'eventos-pais');
    visibilidad();
  }

  // ------------------------------------------------------------- interacción
  function contenidoPopupEvento(ev) {
    const c = E.idx.conflicto[ev.conflicto];
    const l = ev.lugar || {};
    return `<div class="popup-cat"><i style="background:${colorCat(c.categoria)}"></i>${esc(c.nombre)}</div>
      <div class="popup-titulo">${esc(ev.titulo)}</div>
      <div class="popup-sub">${esc(lugarCorto(l))} · ${esc(relativo(ev.referencia))}</div>`;
  }

  function interacciones() {
    const m = E.mapa;
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: '290px' });
    const capasPais = ['paises-escenario', 'paises-participante', 'tierra'];
    const capasHover = ['eventos-punto', 'grupos', 'eventos-pais', 'candidatos-punto', 'zonas-relleno', 'mares-doc', 'regiones-actividad', ...capasPais];
    let paisHover = null;
    const marcarPais = (id) => {
      if (paisHover === id) return;
      if (paisHover) m.setFeatureState({ source: 'paises', id: paisHover }, { hover: false });
      paisHover = id;
      if (id) m.setFeatureState({ source: 'paises', id }, { hover: true });
    };
    const puedeHover = () => matchMedia('(hover: hover)').matches;
    m.on('mousemove', (e) => {
      const f = m.queryRenderedFeatures(e.point, { layers: capasHover.filter((l) => m.getLayer(l)) });
      m.getCanvas().style.cursor = f.length && f[0].layer.id !== 'tierra' ? 'pointer' : '';
      if (!f.length) { popup.remove(); marcarPais(null); resaltarEvento(null); return; }
      const x = f[0];
      let html = '';
      const pais = f.find((g) => capasPais.includes(g.layer.id));
      marcarPais(pais && pais.properties.rol ? pais.properties.id : null);
      if (x.layer.id === 'eventos-punto') {
        const ev = E.idx.evento[x.properties.id];
        if (ev) { html = contenidoPopupEvento(ev); resaltarEvento(ev.id); }
      } else {
        resaltarEvento(null);
        if (x.layer.id === 'grupos') {
          html = `<div class="popup-titulo">${x.properties.point_count} novedades</div><div class="popup-sub">Hacé clic para acercar</div>`;
        } else if (x.layer.id === 'eventos-pais') {
          html = `<div class="popup-titulo">${x.properties.n} novedad(es) en ${esc(nombrePais(x.properties.pais))}</div><div class="popup-sub">Ubicación conocida solo a nivel país: el círculo no indica un lugar exacto.</div>`;
        } else if (x.layer.id === 'candidatos-punto') {
          const c = (E.datos.candidatos.candidatos || []).find((v) => v.id === x.properties.id);
          if (c) html = `<div class="popup-titulo">${esc(c.nombre)}</div><div class="popup-sub">Detectado automáticamente · sin verificar</div>`;
        } else if (x.layer.id === 'zonas-relleno') {
          html = `<div class="popup-titulo">${esc(x.properties.nombre)}</div><div class="popup-sub">Zona en disputa de soberanía (Natural Earth). No indica control militar ni frentes.</div>`;
        } else if (x.layer.id === 'mares-doc') {
          html = popupMar(x.properties.id, x.properties.n);
        } else if (x.layer.id === 'regiones-actividad') {
          html = popupRegion(x.properties.id);
        } else if (pais && pais.properties.rol) {
          const id = pais.properties.id;
          const cs = (E.idx.paisConflictos[id] || []).filter((r) => E.categorias.has(E.idx.conflicto[r.id].categoria));
          html = `<div class="popup-titulo">${esc(nombrePais(id))}</div>` + (cs.length
            ? '<div class="popup-sub">' + cs.slice(0, 4).map((r) => `<span style="color:${colorCat(E.idx.conflicto[r.id].categoria)}">●</span> ${esc(E.idx.conflicto[r.id].nombre)}${r.rol === 'participante' ? ' (participa)' : ''}`).join('<br>') + (cs.length > 4 ? '<br>…' : '') + '</div>'
            : '');
        }
      }
      if (html && puedeHover()) popup.setLngLat(e.lngLat).setHTML(html).addTo(m);
      else popup.remove();
    });
    m.on('mouseout', () => { popup.remove(); marcarPais(null); resaltarEvento(null); });
    m.on('click', (e) => {
      popup.remove();
      const capas = capasHover.filter((l) => m.getLayer(l) && m.getLayoutProperty(l, 'visibility') !== 'none');
      const f = m.queryRenderedFeatures(e.point, { layers: capas });
      if (!f.length) return;
      const x = f[0];
      if (x.layer.id === 'grupos') {
        m.getSource('eventos').getClusterExpansionZoom(x.properties.cluster_id).then((z) => m.easeTo({ center: x.geometry.coordinates, zoom: z + 0.3, duration: 600 }));
      } else if (x.layer.id === 'eventos-punto') {
        abrirEvento(x.properties.id);
      } else if (x.layer.id === 'eventos-pais') {
        abrirVista({ tipo: 'pais', id: x.properties.pais });
      } else if (x.layer.id === 'candidatos-punto') {
        abrirVista({ tipo: 'candidato', id: x.properties.id });
      } else if (x.layer.id === 'zonas-relleno') {
        new maplibregl.Popup({ offset: 8 }).setLngLat(e.lngLat).setHTML(`<div class="popup-titulo">${esc(x.properties.nombre)}</div><div class="popup-sub">Zona en disputa de soberanía según ${esc(x.properties.fuente)}; consultado ${esc(fechaCorta(x.properties.fecha_consulta))}. No indica control militar ni líneas de frente.</div>`).addTo(m);
      } else if (x.layer.id === 'mares-doc') {
        new maplibregl.Popup({ offset: 8, maxWidth: '300px' }).setLngLat(e.lngLat).setHTML(popupMar(x.properties.id, x.properties.n, true)).addTo(m);
      } else if (x.layer.id === 'regiones-actividad') {
        abrirVista({ tipo: 'region', id: x.properties.id });
      } else {
        const pais = f.find((g) => capasPais.includes(g.layer.id));
        const id = pais && pais.properties.id;
        if (id && (E.idx.paisConflictos[id] || []).length) abrirVista({ tipo: 'pais', id });
      }
    });
  }

  function gruposDeRegion(id) { return regionesDocumentadas().filter(({ grupo }) => grupo.ids.includes(id)); }
  function gruposDeMar(id) { return regionesDocumentadas().filter(({ grupo }) => grupo.mares.includes(id)); }
  function popupRegion(id) {
    const r = E.reg.info[id] || {};
    const c = E.reg.conteo[id];
    const docs = gruposDeRegion(id);
    let html = `<div class="popup-titulo">${esc(r.n || id)} <span style="font-weight:400;color:var(--texto-3)">· ${esc(nombrePais(r.p))}</span></div><div class="popup-sub">`;
    html += c ? `${c.n} novedad(es) ubicada(s) aquí en ${E.horas} h` : `Sin novedades ubicadas aquí en ${E.horas} h`;
    if (docs.length) html += '<br>' + docs.slice(0, 2).map(({ grupo }) => esc(grupo.nota)).join('<br>');
    return html + '</div>';
  }
  function popupMar(id, nombre, conFuentes) {
    const docs = gruposDeMar(id);
    let html = `<div class="popup-titulo">${esc(nombre)}</div><div class="popup-sub">`;
    html += docs.map(({ conflicto, grupo }) => `<strong>${esc(conflicto.nombre)}</strong>: ${esc(grupo.nota)}`
      + (conFuentes ? '<br>Fuente: ' + grupo.fuentes.map((f) => `<a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">${esc(f.medio)}, ${esc(fechaCorta(f.fecha))}</a>`).join('; ') : '')).join('<br>');
    return html + '<br><em>Indica dónde se informaron incidentes, no su ubicación exacta.</em></div>';
  }

  // ------------------------------------------------------------------ panel
  function etiquetaPrincipal(ev) {
    if (ev.estado === 'declaracion_parte') return `<span class="etiqueta parte">Declaración de ${esc(Object.keys(ev.partes_con_fuente || {}).join(', ') || 'parte')}</span>`;
    if (ev.estado === 'varias_fuentes') return `<span class="etiqueta varias">${ev.fuentes_independientes} fuentes</span>`;
    return '<span class="etiqueta preliminar">Preliminar</span>';
  }

  function insigniasDetalle(ev) {
    const b = [];
    if (ev.estado === 'declaracion_parte') b.push(`<span class="etiqueta parte">Declaración de ${esc(Object.keys(ev.partes_con_fuente || {}).join(', ') || 'parte')}</span>`);
    else if (ev.estado === 'varias_fuentes') b.push(`<span class="etiqueta varias">${ev.fuentes_independientes} fuentes independientes</span>`);
    else b.push('<span class="etiqueta neutra">Reporte preliminar: un solo origen</span>');
    if (ev.estado !== 'declaracion_parte' && Object.keys(ev.partes_con_fuente || {}).length) b.push(`<span class="etiqueta parte">También declaración de ${esc(Object.keys(ev.partes_con_fuente).join(', '))}</span>`);
    if (ev.contrapuestas) b.push('<span class="etiqueta contrapuestas">Versiones contrapuestas</span>');
    if (ev.atribuida) b.push('<span class="etiqueta neutra">Afirmación atribuida</span>');
    if (ev.marcado_preliminar && ev.estado !== 'preliminar') b.push('<span class="etiqueta neutra">Titular preliminar</span>');
    return `<div class="insignias">${b.join('')}</div>`;
  }

  function lugarCorto(l) {
    if (!l || !l.nombre) return 'Sin ubicación';
    if (l.precision === 'pais') return l.nombre;
    const pais = l.pais ? nombrePais(l.pais) : '';
    return pais && l.nombre !== pais ? `${l.nombre}, ${pais}` : l.nombre;
  }

  function textoLugar(l) {
    if (!l || !l.nombre) return 'Sin ubicación';
    return `${lugarCorto(l)} · ${PRECISION[l.precision] || ''}`;
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
    const nArt = ev.n_articulos > 1 ? ` · ${ev.n_articulos} notas` : '';
    const t = el(`<article class="tarjeta" style="--cat:${colorCat(c.categoria)}" tabindex="0" data-evento="${esc(ev.id)}" aria-expanded="${abierto}">
      <div class="cabeza">${esReciente(ev) ? '<span class="nuevo" title="Últimas 3 horas"></span>' : ''}${mostrarConflicto ? `<span class="conflicto">${esc(c.nombre)}</span>` : ''}<span class="hora">${esc(relativo(ev.referencia))}</span></div>
      <h3>${esc(ev.titulo)}</h3>
      <div class="pie">${etiquetaPrincipal(ev)}${ev.contrapuestas ? '<span class="etiqueta contrapuestas">Contrapuestas</span>' : ''}<span>${esc(lugarCorto(l))}${esc(nArt)}</span></div>
    </article>`);
    if (abierto) t.appendChild(detalleEvento(ev));
    const alternar = (e) => {
      if (e.target.closest('a, button, .detalle')) return;
      E.eventoAbierto = E.eventoAbierto === ev.id ? null : ev.id;
      const nuevo = tarjetaEvento(ev, mostrarConflicto);
      t.replaceWith(nuevo);
      nuevo.focus({ preventScroll: true });
      if (E.eventoAbierto && l.coord) E.mapa.flyTo({ center: l.coord, zoom: Math.max(E.mapa.getZoom(), 5), padding: rellenoMapa(), speed: 1.2 });
    };
    t.addEventListener('click', alternar);
    t.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alternar(e); } });
    t.addEventListener('mouseenter', () => resaltarEvento(ev.id));
    t.addEventListener('mouseleave', () => resaltarEvento(null));
    return t;
  }

  function detalleEvento(ev) {
    const arts = (ev.articulos || []).map((k) => E.idx.articulo[k]).filter(Boolean);
    const l = ev.lugar || {};
    const d = el('<div class="detalle"></div>');
    let html = insigniasDetalle(ev);
    html += `<p class="linea"><strong>Corroboración:</strong> ${esc(ev.reglas || '')}</p>`;
    html += `<p class="linea"><strong>Ubicación:</strong> ${esc(textoLugar(l))}. ${esc(METODO[l.metodo] || '')}${(l.otros_lugares || []).length ? '. Otros lugares: ' + esc(l.otros_lugares.join(', ')) : ''}.</p>`;
    html += `<p class="linea"><strong>Fechas:</strong> ${esc(lineaFecha(ev))}${(ev.fechas_hecho || []).length ? ' · hecho (según GDELT): ' + esc(ev.fechas_hecho.map(fechaCorta).join(', ')) : ''}</p>`;
    if (sinTraducir(ev)) html += `<p class="nota-trad">Titular sin traducir (${esc(sinTraducir(ev))}).</p>`;
    else if (ev.titulo_traducido) html += '<p class="linea" style="color:var(--texto-3)">Titular con traducción automática.</p>';
    d.innerHTML = html;
    for (const a of arts) d.appendChild(bloqueArticulo(a));
    if (ev.articulos_omitidos) d.appendChild(el(`<p class="linea">Y ${ev.articulos_omitidos} nota(s) más sobre este acontecimiento.</p>`));
    return d;
  }

  function bloqueArticulo(a) {
    const traducido = a.titulo_es && a.idioma !== 'es';
    const tr = a.traduccion || {};
    const partes = [];
    partes.push(`<div><span class="fuente">${esc(a.organizacion || a.fuente_nombre || a.dominio)}</span> <span class="medio">`
      + (a.agencia ? `reproduce a ${esc(a.agencia)} · ` : '')
      + (a.pais_medio ? `medio de ${esc(nombrePais(a.pais_medio))}` : '')
      + (a.fuente_estatal_de ? ` · <em>${a.fuente_estatal_tipo === 'oficial' ? 'fuente oficial' : 'medio estatal'} de ${esc(nombrePais(a.fuente_estatal_de))}</em>` : '')
      + (a.idioma ? ` · ${esc(IDIOMAS[a.idioma] || a.idioma)}` : '') + '</span></div>');
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

  // Solo se avisa en la lista cuando los datos están demorados o fallaron (las advertencias de rutina
  // quedan en la pestaña Estado).
  function avisosDatos(cont) {
    const s = estadoActualizacion();
    if (s.nivel === 'error' || s.nivel === 'aviso') cont.appendChild(el(`<p class="alerta ${s.nivel}">${esc(s.detalle)}</p>`));
    if (!E.datos.eventos.eventos.length) cont.appendChild(el('<p class="alerta info">Todavía no hay novedades publicadas. Si el sitio es nuevo, la primera recopilación puede tardar hasta 30 minutos.</p>'));
  }

  function listaConMas(cont, evs, mostrarConflicto = true) {
    evs.slice(0, E.limiteLista).forEach((ev) => cont.appendChild(tarjetaEvento(ev, mostrarConflicto)));
    if (evs.length > E.limiteLista) {
      const b = el(`<button class="mas" type="button">Ver ${Math.min(40, evs.length - E.limiteLista)} más</button>`);
      b.onclick = () => { E.limiteLista += 40; renderPanel(); };
      cont.appendChild(b);
    }
  }

  function renderNovedades(cont) {
    avisosDatos(cont);
    let evs = eventosFiltrados(E.soloVarias ? (ev) => ev.fuentes_independientes >= 2 : null);
    if (E.orden === 'fuentes') evs = evs.slice().sort((a, b) => b.fuentes_independientes - a.fuentes_independientes || (b.referencia || '').localeCompare(a.referencia || ''));
    const cab = el(`<div class="encabezado-lista"><span><strong>${nf.format(evs.length)}</strong> novedades · ${E.horas} h</span>
      <div class="herramientas">
        <select class="selector" aria-label="Ordenar"><option value="recientes">Recientes</option><option value="fuentes">Más fuentes</option></select>
        <button type="button" class="chip-filtro" aria-pressed="${E.soloVarias}" title="Mostrar solo novedades con 2 o más fuentes independientes">2+ fuentes</button>
      </div></div>`);
    const sel = $('select', cab);
    sel.value = E.orden;
    sel.onchange = () => { E.orden = sel.value; E.limiteLista = 40; renderPanel(); };
    $('.chip-filtro', cab).onclick = () => { E.soloVarias = !E.soloVarias; E.limiteLista = 40; renderPanel(); };
    cont.appendChild(cab);
    if (!evs.length) cont.appendChild(mensajeVacio('No hay novedades en este período para las categorías elegidas.'));
    listaConMas(cont, evs);
  }

  function conteosConflicto(c) {
    const evs = E.idx.eventosPorConflicto[c.id] || [];
    const l24 = limitePeriodo(24), l72 = limitePeriodo(72), lp = limitePeriodo();
    let n24 = 0, n72 = 0, np = 0;
    for (const ev of evs) { const r = ev.referencia || ''; if (r >= l24) n24++; if (r >= l72) n72++; if (r >= lp) np++; }
    return { n24, n72, np };
  }

  function renderConflictos(cont) {
    const lista = E.datos.conflictos.conflictos.filter((c) => E.categorias.has(c.categoria))
      .map((c) => ({ c, n: conteosConflicto(c).np }));
    lista.sort((a, b) => b.n - a.n || a.c.nombre.localeCompare(b.c.nombre, 'es'));
    const max = Math.max(1, ...lista.map((x) => x.n));
    cont.appendChild(el(`<div class="encabezado-lista"><span><strong>${lista.length}</strong> situaciones en el registro</span><span class="herramientas">por novedades (${E.horas} h)</span></div>`));
    let separado = false;
    for (const { c, n } of lista) {
      if (!n && !separado) { cont.appendChild(el(`<p class="separador">Sin novedades en ${E.horas} h</p>`)); separado = true; }
      const paises = c.paises_escenario.map(nombrePais);
      const fila = el(`<div class="fila-conflicto" style="--cat:${colorCat(c.categoria)}" tabindex="0" role="button">
        <span class="punto"></span>
        <div><div class="nombre">${esc(c.nombre)}</div><div class="sub">${esc(CORTO[c.categoria] || nombreCat(c.categoria))} · ${esc(paises.slice(0, 3).join(', '))}${paises.length > 3 ? '…' : ''}</div></div>
        <div class="cuenta">${n ? nf.format(n) : '—'}${n ? `<div class="barra-mini" style="width:${Math.max(4, Math.round(42 * n / max))}px"></div>` : ''}</div>
      </div>`);
      const abrir = () => abrirVista({ tipo: 'conflicto', id: c.id });
      fila.onclick = abrir; fila.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); abrir(); } };
      cont.appendChild(fila);
    }
  }

  function renderVista(cont) {
    const v = E.vista;
    const volver = el('<button class="volver" type="button">← Volver</button>');
    volver.onclick = cerrarVista;
    cont.appendChild(volver);
    if (v.tipo === 'region') return fichaRegion(cont, v.id);
    if (v.tipo === 'conflicto') return fichaConflicto(cont, E.idx.conflicto[v.id]);
    if (v.tipo === 'pais') return fichaPais(cont, v.id);
    if (v.tipo === 'candidato') return fichaCandidato(cont, (E.datos.candidatos.candidatos || []).find((c) => c.id === v.id));
  }

  function cerrarVista() {
    E.vista = null; E.eventoAbierto = null; E.limiteLista = 40;
    renderPanel(); actualizarMapa(); resaltarSeleccion();
  }

  function fichaConflicto(cont, c) {
    if (!c) return cont.appendChild(mensajeVacio('Conflicto no encontrado.'));
    const evs = eventosFiltrados((ev) => ev.conflicto === c.id);
    const k = conteosConflicto(c);
    const nReg = Object.keys(conteoRegiones(evs)).length;
    const ue = (c.participantes_grupos || []).includes('UE');
    const participantes = ue ? 'Unión Europea (27 países)' + c.paises_participantes.filter((p) => !['AUT','BEL','BGR','HRV','CYP','CZE','DNK','EST','FIN','FRA','DEU','GRC','HUN','IRL','ITA','LVA','LTU','LUX','MLT','NLD','POL','PRT','ROU','SVK','SVN','ESP','SWE'].includes(p)).map((p) => ', ' + nombrePais(p)).join('') : c.paises_participantes.map(nombrePais).join(', ');
    const f = el(`<div class="ficha">
      <span class="categoria-ficha"><i style="background:${colorCat(c.categoria)}"></i>${esc(nombreCat(c.categoria))}</span>
      <h2>${esc(c.nombre)}</h2>
      <div class="cifras">
        <div class="cifra"><b>${nf.format(k.n24)}</b><span>novedades en 24 h</span></div>
        <div class="cifra"><b>${nf.format(k.n72)}</b><span>en 72 h</span></div>
        <div class="cifra"><b>${E.reg.listo ? nReg : '—'}</b><span>regiones con novedades</span></div>
      </div>
      <section><h4>Qué está pasando</h4><p>${esc(c.resumen)}</p>
        <p class="meta-zona">Resumen del registro, revisado el ${esc(fechaCorta(c.revisado))}${c.revision_pendiente ? ' (revisión pendiente)' : ''}. Fuentes al final.</p></section>
      <section class="zonas-conflicto"></section>
      <section><h4>Últimas novedades (${E.horas} h)</h4><div class="lista-eventos"></div></section>
      <section><details><summary>Actores y países</summary>
        <ul>${c.actores.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>
        <p style="margin-top:8px"><strong>Escenario:</strong> ${esc(c.paises_escenario.map(nombrePais).join(', ') || '—')}</p>
        ${c.paises_participantes.length ? `<p><strong>Participan o están involucrados:</strong> ${esc(participantes)}</p>` : ''}
      </details></section>
      <section><details><summary>Fuentes del registro</summary>
        <ul class="fuentes-registro">${c.fuentes.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.titulo)}</a> — ${esc(s.medio)}, ${esc(fechaCorta(s.fecha))}</li>`).join('')}</ul>
      </details></section>
      <p class="meta-zona">La falta de noticias no implica que el conflicto haya terminado.</p>
    </div>`);
    const lista = $('.lista-eventos', f);
    if (!evs.length) lista.appendChild(mensajeVacio('Sin novedades detectadas en este período.'));
    listaConMas(lista, evs, false);
    seccionZonas($('.zonas-conflicto', f), c, evs);
    cont.appendChild(f);
  }

  // Zonas específicas: regiones documentadas por el registro y regiones con más novedades.
  function seccionZonas(sec, c, evs) {
    let html = '<h4>Zonas</h4>';
    const conteo = Object.entries(conteoRegiones(evs)).sort((a, b) => b[1].n - a[1].n);
    if (E.reg.listo && conteo.length) {
      html += `<p class="meta-zona">Con más novedades (${E.horas} h)</p><div class="chips">${conteo.slice(0, 8).map(([id, x]) => chipRegion(id).replace('</button>', ` · ${x.n}</button>`)).join('')}</div>`;
    }
    const grupos = c.regiones || [];
    if (grupos.length) {
      html += grupos.map((g) => `<div class="grupo-zona" style="--cat:${colorCat(c.categoria)}">
        <p><strong>${esc(g.nota)}</strong></p>
        ${g.ids.length ? `<div class="chips">${g.ids.map(chipRegion).join('')}</div>` : ''}
        ${g.mares.length ? `<p class="meta-zona">Áreas marítimas: ${esc(g.nombres_mares.join(', '))}</p>` : ''}
        ${g.precision ? `<p class="meta-zona">${esc(g.precision)}</p>` : ''}
        <p class="meta-zona">Según ${g.fuentes.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.medio)}</a> (${esc(fechaCorta(s.fecha))})`).join('; ')}</p>
      </div>`).join('');
    } else if (!conteo.length) {
      html += '<p class="meta-zona">Sin regiones documentadas ni novedades con ubicación precisa en el período.</p>';
    }
    html += '<p class="meta-zona">Las regiones son divisiones administrativas: indican dónde se informaron hechos, no control territorial ni frentes.</p>';
    sec.innerHTML = html;
    activarChips(sec);
  }

  function fichaRegion(cont, id) {
    const r = E.reg.info[id];
    if (!r) return cont.appendChild(mensajeVacio(E.reg.listo ? 'Región no encontrada.' : 'Cargando regiones…'));
    const evs = eventosFiltrados((ev) => E.reg.deEvento[ev.id] === id);
    const docs = gruposDeRegion(id);
    const porConflicto = {};
    evs.forEach((ev) => { porConflicto[ev.conflicto] = (porConflicto[ev.conflicto] || 0) + 1; });
    const f = el(`<div class="ficha">
      <span class="categoria-ficha"><i style="background:#8c8c8c"></i>Región de ${esc(nombrePais(r.p))}</span>
      <h2>${esc(r.n)}</h2>
      <p class="meta-zona">División administrativa${r.t ? ' (' + esc(TIPOS_REGION[r.t] || r.t) + ')' : ''} según Natural Earth. No indica quién controla el territorio.</p>
      <section class="docs-sec"><h4>Según las fuentes del registro</h4><div class="docs"></div></section>
      <section><h4>Novedades ubicadas aquí (${E.horas} h)</h4>
        <p class="resumen-region"></p><div class="lista-eventos"></div></section>
      <p><button class="boton-suave ver-pais" type="button">Ver todo ${esc(nombrePais(r.p))}</button></p>
    </div>`);
    const d = $('.docs', f);
    if (docs.length) {
      d.innerHTML = docs.map(({ conflicto, grupo }) => `<div class="grupo-zona" style="--cat:${colorCat(conflicto.categoria)}">
        <p><strong>${esc(grupo.nota)}</strong> — <a href="#" data-conflicto="${esc(conflicto.id)}">${esc(conflicto.nombre)}</a></p>
        ${grupo.precision ? `<p class="meta-zona">${esc(grupo.precision)}</p>` : ''}
        <p class="meta-zona">Según ${grupo.fuentes.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.titulo)}</a> — ${esc(s.medio)}, ${esc(fechaCorta(s.fecha))}`).join('; ')}</p></div>`).join('');
      $$('[data-conflicto]', d).forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); abrirVista({ tipo: 'conflicto', id: a.dataset.conflicto }); }));
    } else {
      $('.docs-sec', f).remove();
    }
    $('.resumen-region', f).textContent = evs.length
      ? Object.entries(porConflicto).sort((a, b) => b[1] - a[1]).map(([cid, n]) => `${E.idx.conflicto[cid].nombre}: ${n}`).join(' · ')
      : '';
    const le = $('.lista-eventos', f);
    if (!evs.length) le.appendChild(mensajeVacio('Sin novedades con ubicación precisa en esta región en el período. Puede haber noticias ubicadas solo a nivel país.'));
    listaConMas(le, evs);
    $('.ver-pais', f).onclick = () => abrirVista({ tipo: 'pais', id: r.p });
    cont.appendChild(f);
  }

  function fichaPais(cont, iso) {
    const rels = (E.idx.paisConflictos[iso] || []).filter((r) => E.categorias.has(E.idx.conflicto[r.id].categoria));
    const evs = eventosFiltrados((ev) => (ev.lugar || {}).pais === iso);
    const f = el(`<div class="ficha"><span class="categoria-ficha"><i style="background:#8c8c8c"></i>País</span><h2>${esc(nombrePais(iso))}</h2>
      <section><h4>Conflictos y situaciones</h4><div class="lista-conf"></div></section>
      <section class="regiones-pais"></section>
      <section><h4>Novedades ubicadas en el país (${E.horas} h)</h4><div class="lista-eventos"></div></section></div>`);
    const lc = $('.lista-conf', f);
    if (!rels.length) lc.appendChild(mensajeVacio('Sin conflictos del registro en las categorías elegidas.'));
    for (const r of rels) {
      const c = E.idx.conflicto[r.id];
      const n = conteosConflicto(c).np;
      const fila = el(`<div class="fila-conflicto" style="--cat:${colorCat(c.categoria)}" tabindex="0" role="button"><span class="punto"></span>
        <div><div class="nombre">${esc(c.nombre)}</div><div class="sub">${esc(CORTO[c.categoria] || nombreCat(c.categoria))} · ${r.rol === 'escenario' ? 'escenario' : 'participa'}</div></div>
        <div class="cuenta">${n ? nf.format(n) : '—'}</div></div>`);
      fila.onclick = () => abrirVista({ tipo: 'conflicto', id: c.id });
      fila.onkeydown = (e) => { if (e.key === 'Enter') fila.onclick(); };
      lc.appendChild(fila);
    }
    const conteo = Object.entries(conteoRegiones(evs)).sort((a, b) => b[1].n - a[1].n);
    const sr = $('.regiones-pais', f);
    if (conteo.length) {
      sr.innerHTML = `<h4>Regiones con novedades (${E.horas} h)</h4><div class="chips">${conteo.slice(0, 12).map(([id, x]) => chipRegion(id).replace('</button>', ` · ${x.n}</button>`)).join('')}</div>`;
      activarChips(sr);
    } else sr.remove();
    const le = $('.lista-eventos', f);
    if (!evs.length) le.appendChild(mensajeVacio('Sin novedades con ubicación en este país en el período.'));
    listaConMas(le, evs);
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
      <details><summary>Borrador para incorporarlo al registro</summary><pre style="white-space:pre-wrap;font-size:12px">${esc(borrador)}</pre></details></div>`);
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
      <dt>Última actualización</dt><dd>${esc(absoluto(est.ultimo_exito))} (${esc(relativo(est.ultimo_exito) || 'nunca')})</dd>
      <dt>Último ciclo</dt><dd>${esc(absoluto(est.generado))} · ${est.ciclo_ok ? 'correcto' : 'con fallas'} · ${esc(est.duracion_s)} s</dd>
      <dt>Feeds RSS</dt><dd>${r.ok || 0} de ${r.total || 0} disponibles${r.error ? ' · ' + r.error + ' con error' : ''}${r.bloqueadas ? ' · ' + r.bloqueadas + ' bloqueadas por robots.txt' : ''}</dd>
      <dt>GDELT</dt><dd>${ultimoG ? 'último archivo ' + esc(absoluto(ultimoG)) : 'sin archivos procesados'}${g.archivos_faltantes ? ' · ' + g.archivos_faltantes + ' faltantes' : ''}</dd>
      <dt>Traducción</dt><dd>${esc(t.motor || '—')}: ${t.traducidos || 0} nuevas, ${t.desde_cache || 0} reutilizadas, ${t.fallidos || 0} fallidas${(t.sin_modelo || []).length ? ' · sin modelo: ' + esc(t.sin_modelo.join(', ')) : ''}</dd>
      <dt>Alertas Telegram</dt><dd>${tg.configurado ? (tg.vinculado ? 'activas' + (tg.pausado ? ' (en pausa)' : '') : 'bot configurado, chat sin vincular') : 'no configuradas'}</dd>
    </dl>`));
    if ((est.advertencias || []).length) cont.appendChild(el(`<div class="alerta info"><strong>Advertencias del último ciclo</strong><ul>${est.advertencias.map((a) => `<li>${esc(a)}</li>`).join('')}</ul></div>`));
    if ((est.errores || []).length) cont.appendChild(el(`<div class="alerta error"><strong>Errores del último ciclo</strong><ul>${est.errores.slice(0, 6).map((a) => `<li>${esc(a)}</li>`).join('')}</ul></div>`));
    const filas = (est.fuentes || []).map((f) => `<tr><td>${esc(f.nombre)}<br><small>${esc(f.tipo)} · ${esc(IDIOMAS[f.idioma] || f.idioma)}${f.pais ? ' · ' + esc(nombrePais(f.pais)) : ''}${f.propiedad === 'estatal' ? ' · estatal' : ''}</small></td>
      <td class="${f.estado === 'ok' ? 'estado-fuente-ok' : f.estado === 'error' ? 'estado-fuente-error' : 'estado-fuente-otro'}">${esc({ ok: 'disponible', error: 'error', bloqueada_robots: 'bloqueada (robots.txt)', sin_datos: 'sin datos' }[f.estado] || f.estado)}${f.error ? '<br><small>' + esc(f.error) + '</small>' : ''}</td>
      <td><small>${f.ultimo_ok ? esc(relativo(f.ultimo_ok)) : '—'}</small></td></tr>`).join('');
    cont.appendChild(el(`<section class="ficha"><details><summary>Fuentes RSS (${(est.fuentes || []).length})</summary>
      <table class="tabla-fuentes"><thead><tr><th>Fuente</th><th>Estado</th><th>Último dato</th></tr></thead><tbody>${filas}</tbody></table></details></section>`));
    cont.appendChild(el(`<section class="ficha"><details open><summary>Cobertura y limitaciones</summary>
      <ul style="font-size:13px;color:var(--texto-2);padding-left:18px">
        <li>No se capturan todos los conflictos ni todas las noticias del mundo: solo lo que publican estas fuentes y lo que indexa GDELT.</li>
        <li>GDELT entrega titulares y metadatos, no el texto completo; la geolocalización y la clasificación son automáticas y pueden fallar.</li>
        <li>Las traducciones son automáticas (modelos abiertos, calidad variable). Algunos idiomas no tienen modelo.</li>
        <li>Las etiquetas de verificación cuentan orígenes; no confirman hechos.</li>
        <li>La actualización programada de GitHub Actions puede demorarse en horas de alta demanda.</li>
      </ul></details></section>`));
    cont.appendChild(el(`<p class="meta-zona" style="margin:12px 4px">Datos: ${esc(g.cita || 'The GDELT Project')}. Geografía: Natural Earth (dominio público). Mapa: MapLibre GL JS. Traducción: Argos Translate.</p>`));
  }

  function abrirVista(v) {
    E.vista = v; E.eventoAbierto = null; E.limiteLista = 40;
    renderPanel();
    panelNormal();
    actualizarMapa();
    if (v.tipo === 'region') encuadrarCaja(E.reg.cajas[v.id], 6.5);
    else if (v.tipo === 'conflicto') {
      // Si el registro documenta regiones, se encuadran esas zonas; si no, los países escenario.
      const c = E.idx.conflicto[v.id];
      const cajas = (c.regiones || []).flatMap((g) => g.ids.map((i) => E.reg.cajas[i])).filter(Boolean);
      if (cajas.length) encuadrarCaja(cajas.reduce((b, x) => [Math.min(b[0], x[0]), Math.min(b[1], x[1]), Math.max(b[2], x[2]), Math.max(b[3], x[3])]), 5.5);
      else encuadrar(c.paises_escenario);
    } else if (v.tipo === 'pais') encuadrar([v.id]);
    else if (v.tipo === 'candidato') { const c = (E.datos.candidatos.candidatos || []).find((x) => x.id === v.id); if (c) encuadrar([c.pais]); }
    const cp = $('#contenido-panel');
    if (cp) cp.scrollTop = 0;
  }

  function abrirEvento(id) {
    const ev = E.idx.evento[id];
    if (!ev) return;
    // Si se está viendo el conflicto o la región de la novedad, se la abre ahí mismo.
    const v = E.vista;
    const dentro = v && ((v.tipo === 'conflicto' && v.id === ev.conflicto) || (v.tipo === 'region' && E.reg.deEvento[id] === v.id)
      || (v.tipo === 'pais' && (ev.lugar || {}).pais === v.id));
    if (!dentro) { E.vista = null; E.pestana = 'novedades'; actualizarMapa(); }
    E.eventoAbierto = id;
    const lista = dentro ? null : eventosFiltrados();
    if (lista) { const pos = lista.findIndex((x) => x.id === id); if (pos >= E.limiteLista) E.limiteLista = pos + 10; }
    else E.limiteLista = Math.max(E.limiteLista, 200);
    renderPanel(); panelNormal();
    const t = $(`[data-evento="${CSS.escape(id)}"]`);
    if (t) t.scrollIntoView({ block: 'start', behavior: movimientoReducido() ? 'auto' : 'smooth' });
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
  function encuadrarCaja(b, maxZoom) {
    if (!E.mapaListo || !b) return;
    E.mapa.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: rellenoMapa(), maxZoom: maxZoom || 6, duration: movimientoReducido() ? 0 : 1000 });
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
    if (b[2] - b[0] > 250) {
      const et = (E.datos.conflictos.etiquetas_paises || {})[paises[0]];
      if (et) E.mapa.flyTo({ center: et, zoom: 2.4, padding: rellenoMapa() });
      return;
    }
    encuadrarCaja(b, 5.5);
  }

  // ------------------------------------------------- regiones (admin-1)
  // Las regiones son divisiones administrativas de Natural Earth: se usan para contar dónde caen
  // las novedades geolocalizadas y para mostrar las regiones afectadas que documenta el registro.
  // No representan control territorial ni frentes.
  function cajaGeom(coords) {
    let b = [180, 90, -180, -90];
    const recorrer = (c) => { if (typeof c[0] === 'number') { if (c[0] < b[0]) b[0] = c[0]; if (c[1] < b[1]) b[1] = c[1]; if (c[0] > b[2]) b[2] = c[0]; if (c[1] > b[3]) b[3] = c[1]; } else c.forEach(recorrer); };
    recorrer(coords);
    return b;
  }
  function enAnillo(anillo, x, y) {
    let dentro = false;
    for (let i = 0, j = anillo.length - 1; i < anillo.length; j = i++) {
      const [xi, yi] = anillo[i], [xj, yj] = anillo[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) dentro = !dentro;
    }
    return dentro;
  }
  function enGeometria(g, x, y) {
    const polis = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
    return polis.some((p) => enAnillo(p[0], x, y) && !p.slice(1).some((h) => enAnillo(h, x, y)));
  }
  function indexarRegiones() {
    const R = E.reg;
    R.info = {}; R.cajas = {}; R.porPais = {};
    for (const f of E.geo.regiones.features) {
      const p = f.properties;
      R.info[p.id] = { id: p.id, n: p.n, p: p.p, t: p.t, et: p.lx != null ? [p.lx, p.ly] : null, geom: f.geometry };
      R.cajas[p.id] = cajaGeom(f.geometry.coordinates);
      (R.porPais[p.p] = R.porPais[p.p] || []).push(p.id);
    }
    R.listo = true;
    asignarRegiones();
  }
  function regionDePunto(pais, x, y) {
    const R = E.reg;
    const candidatos = (pais && R.porPais[pais]) || [];
    for (const id of candidatos) {
      const b = R.cajas[id];
      if (x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3] && enGeometria(R.info[id].geom, x, y)) return id;
    }
    return null;
  }
  function asignarRegiones() {
    if (!E.reg.listo || !E.datos.eventos) return;
    const d = {};
    for (const ev of E.datos.eventos.eventos) {
      const l = ev.lugar || {};
      if (l.coord && l.precision !== 'pais') {
        const id = regionDePunto(l.pais, l.coord[0], l.coord[1]);
        if (id) d[ev.id] = id;
      }
    }
    E.reg.deEvento = d;
  }
  // Grupos de regiones documentadas (registro) de los conflictos visibles.
  function regionesDocumentadas(filtroConflicto) {
    const salida = [];
    for (const c of E.datos.conflictos.conflictos) {
      if (c.estado !== 'activo' || !E.categorias.has(c.categoria)) continue;
      if (filtroConflicto && c.id !== filtroConflicto) continue;
      for (const g of c.regiones || []) salida.push({ conflicto: c, grupo: g });
    }
    return salida;
  }
  function conteoRegiones(evs) {
    const conteo = {};
    for (const ev of evs) {
      const id = E.reg.deEvento[ev.id];
      if (!id) continue;
      const c = conteo[id] = conteo[id] || { n: 0, cats: new Set(), conflictos: {} };
      c.n++;
      const cat = E.idx.conflicto[ev.conflicto].categoria;
      c.cats.add(cat);
      c.conflictos[ev.conflicto] = (c.conflictos[ev.conflicto] || 0) + 1;
    }
    return conteo;
  }
  const nombreRegion = (id) => (E.reg.info[id] ? E.reg.info[id].n : id);
  const TIPOS_REGION = { Province: 'provincia', State: 'estado', Region: 'región', Oblast: 'óblast', Governorate: 'gobernación',
    District: 'distrito', Department: 'departamento', Prefecture: 'prefectura', County: 'condado', Republic: 'república',
    Territory: 'territorio', Emirate: 'emirato', City: 'ciudad', 'Federal City': 'ciudad federal', 'Autonomous Region': 'región autónoma',
    'Autonomous Province': 'provincia autónoma', 'Capital District': 'distrito capital', 'Federal District': 'distrito federal',
    'Independent Component City': 'ciudad', 'Highly Urbanized City': 'ciudad', 'Autonomous Okrug': 'distrito autónomo', Municipality: 'municipio' };
  const chipRegion = (id) => `<button class="chip" type="button" data-region="${esc(id)}">${esc(nombreRegion(id))}</button>`;
  function activarChips(raiz) {
    $$('[data-region]', raiz).forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); abrirVista({ tipo: 'region', id: b.dataset.region }); }));
  }

  // ------------------------------------------------------------ búsqueda
  function iniciarBusqueda() {
    const input = $('#buscar'), lista = $('#sugerencias');
    let opciones = [], sel = -1;
    const cerrar = () => { lista.hidden = true; input.setAttribute('aria-expanded', 'false'); sel = -1; };
    const elegir = (o) => { cerrar(); input.value = ''; input.blur(); abrirVista({ tipo: o.tipo, id: o.id }); };
    input.addEventListener('input', () => {
      const q = norm(input.value);
      if (q.length < 2) return cerrar();
      const confs = E.datos.conflictos.conflictos.filter((c) => norm(c.nombre).includes(q) || c.actores.some((a) => norm(a).includes(q)))
        .map((c) => ({ tipo: 'conflicto', id: c.id, texto: c.nombre, sub: CORTO[c.categoria] || nombreCat(c.categoria), color: colorCat(c.categoria) }));
      const paises = Object.entries(E.datos.conflictos.paises).filter(([, n]) => norm(n).includes(q))
        .map(([iso, n]) => ({ tipo: 'pais', id: iso, texto: n, sub: (E.idx.paisConflictos[iso] || []).length ? (E.idx.paisConflictos[iso].length + ' conflicto(s)') : 'país' }));
      const regiones = Object.values(E.reg.info).filter((r) => norm(r.n).includes(q))
        .map((r) => ({ tipo: 'region', id: r.id, texto: r.n, sub: 'región · ' + nombrePais(r.p), n: (E.reg.conteo[r.id] || {}).n || 0 }))
        .sort((a, b) => b.n - a.n);
      opciones = [...confs.slice(0, 6), ...paises.sort((a, b) => (b.sub === 'país' ? 0 : 1) - (a.sub === 'país' ? 0 : 1)).slice(0, 5), ...regiones.slice(0, 5)];
      lista.innerHTML = opciones.length ? opciones.map((o, i) => `<li role="option" id="op-${i}" aria-selected="false"><span class="punto" style="background:${o.color || 'var(--superficie-3)'}"></span>${esc(o.texto)}<span class="tipo">${esc(o.sub)}</span></li>`).join('') : '<li role="option" aria-disabled="true">Sin resultados</li>';
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
      else if (e.key === 'Escape') { cerrar(); e.stopPropagation(); }
    });
    input.addEventListener('blur', () => setTimeout(cerrar, 150));
  }

  // ------------------------------------------------------------ controles
  // Leyenda de categorías que también sirve de filtro (clic: mostrar/ocultar; doble clic: solo esa).
  function renderCategorias() {
    const cont = $('#leyenda-categorias');
    if (!cont || !E.datos.conflictos) return;
    const conteo = conteoPorCategoria();
    const cats = Object.entries(E.datos.conflictos.categorias);
    const ocultas = cats.some(([k]) => !E.categorias.has(k));
    cont.innerHTML = cats.map(([k, v]) => `<button type="button" class="chip-cat" style="--c:${v.color}" data-cat="${esc(k)}" aria-pressed="${E.categorias.has(k)}"
      title="${esc(v.nombre)}${v.descripcion ? ': ' + esc(v.descripcion) : ''}. Clic para mostrar u ocultar; doble clic para ver solo esta."><span class="punto"></span>${esc(CORTO[k] || v.nombre)}<span class="n">${nf.format(conteo[k] || 0)}</span></button>`).join('')
      + (ocultas ? '<button type="button" class="chip-cat todas" data-todas>Ver todas</button>' : '');
    $$('[data-cat]', cont).forEach((b) => {
      b.addEventListener('click', () => {
        const k = b.dataset.cat;
        if (E.categorias.has(k)) E.categorias.delete(k); else E.categorias.add(k);
        cambioFiltros();
      });
      b.addEventListener('dblclick', () => { E.categorias = new Set([b.dataset.cat]); cambioFiltros(); });
    });
    const todas = $('[data-todas]', cont);
    if (todas) todas.addEventListener('click', () => { Object.keys(E.datos.conflictos.categorias).forEach((k) => E.categorias.add(k)); cambioFiltros(); });
  }
  function cambioFiltros() { E.limiteLista = 40; actualizarMapa(); renderPanel(); }

  function renderLeyenda() {
    const P = paleta();
    $('#leyenda').innerHTML = `
      <div class="item"><svg width="22" height="16"><circle cx="11" cy="8" r="5.5" fill="#D55E00" stroke="${P.puntoBorde}" stroke-width="1.4"/></svg>Novedad ubicada en una ciudad</div>
      <div class="item"><svg width="22" height="16"><circle cx="11" cy="8" r="5" fill="${P.tierra}" stroke="#D55E00" stroke-width="2.6"/></svg>Ubicada en una provincia o región</div>
      <div class="item"><svg width="22" height="22"><circle cx="11" cy="11" r="9" fill="${P.anilloFondo}" stroke="${P.anillo}" stroke-width="1.3"/><text x="11" y="15" font-size="10" text-anchor="middle" fill="${P.anilloTexto}">3</text></svg>Solo se conoce el país: no es un lugar exacto (al acercar)</div>
      <div class="item"><svg width="22" height="22"><circle cx="11" cy="11" r="9" fill="${P.grupo}" opacity=".9"/><text x="11" y="15" font-size="10" text-anchor="middle" fill="${P.grupoTexto}">12</text></svg>Grupo de novedades: hacé clic para acercar</div>
      <div class="item"><svg width="22" height="22"><circle cx="11" cy="11" r="10" fill="#D55E00" opacity=".22"/><circle cx="11" cy="11" r="5" fill="#D55E00"/></svg>Late: hay novedades de las últimas ${HORAS_RECIENTE} horas</div>
      <div class="item"><svg width="22" height="14"><rect width="22" height="14" rx="3" fill="#0072B2" fill-opacity=".66"/></svg>País escenario (color = categoría)</div>
      <div class="item"><svg width="22" height="14"><rect x="1.5" y="1.5" width="19" height="11" rx="2" fill="none" stroke="#0072B2" stroke-width="2.2"/></svg>Borde: el país participa sin ser escenario</div>
      <div class="item"><svg width="30" height="14"><rect width="10" height="14" fill="#D55E00" fill-opacity=".5"/><rect x="10" width="10" height="14" fill="#D55E00" fill-opacity=".72"/><rect x="20" width="10" height="14" fill="#D55E00" fill-opacity=".92"/></svg>Región con novedades (más intenso = más)</div>
      <div class="item"><svg width="22" height="14"><defs><pattern id="ld" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><line x1="0" y1="0" x2="0" y2="4" stroke="${P.bordeDoc}" stroke-width="1.2"/></pattern></defs><rect width="22" height="14" fill="url(#ld)" stroke="${P.bordeDoc}" stroke-width="1.2"/></svg>Región afectada según una fuente fechada</div>
      <div class="item"><svg width="22" height="14"><rect width="22" height="14" fill="url(#ld)" fill-opacity=".6" stroke="${P.mar}" stroke-dasharray="2 2"/></svg>Área marítima con incidentes informados</div>
      <div class="item"><svg width="22" height="14"><defs><pattern id="lz" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5" stroke="${P.bordeZona}" stroke-width="1.4"/></pattern></defs><rect width="22" height="14" fill="url(#lz)" stroke="${P.bordeZona}" stroke-dasharray="3 2"/></svg>Zona en disputa de soberanía</div>
      <div class="item"><svg width="22" height="22"><circle cx="11" cy="11" r="9" fill="${P.anilloFondo}" stroke="${P.anillo}" stroke-width="1.6"/><text x="11" y="15" font-size="11" text-anchor="middle" fill="${P.anilloTexto}">?</text></svg>Situación detectada automáticamente (sin verificar)</div>
      <p class="nota">Los colores identifican categorías, no gravedad. Los puntos más grandes tienen dos o más fuentes independientes. Las regiones y zonas no indican control territorial ni frentes de combate.</p>`;
  }

  function cerrarPopovers(excepto) {
    $$('.popover').forEach((p) => { if (p !== excepto) p.hidden = true; });
    $$('[aria-controls^="popover-"]').forEach((b) => { if (!excepto || b.getAttribute('aria-controls') !== excepto.id) b.setAttribute('aria-expanded', 'false'); });
  }
  function alternarPopover(boton) {
    const pop = document.getElementById(boton.getAttribute('aria-controls'));
    const abrir = pop.hidden;
    cerrarPopovers(abrir ? pop : null);
    pop.hidden = !abrir;
    boton.setAttribute('aria-expanded', String(abrir));
  }

  function iniciarControles() {
    $$('.segmentado button[data-horas]').forEach((b) => b.addEventListener('click', () => {
      $$('.segmentado button[data-horas]').forEach((x) => x.setAttribute('aria-checked', String(x === b)));
      E.horas = Number(b.dataset.horas);
      cambioFiltros();
    }));
    $$('input[data-capa]').forEach((cb) => cb.addEventListener('change', () => {
      E.capas[cb.dataset.capa] = cb.checked;
      if (cb.dataset.capa === 'base') alternarBase(cb.checked); else visibilidad();
    }));
    ['#btn-capas', '#btn-leyenda'].forEach((s) => $(s).addEventListener('click', (e) => { e.stopPropagation(); alternarPopover($(s)); }));
    document.addEventListener('click', (e) => { if (!e.target.closest('.popover, [aria-controls^="popover-"]')) cerrarPopovers(); });
    $$('.pestanas button').forEach((b) => b.addEventListener('click', () => {
      E.pestana = b.dataset.pestana; E.limiteLista = 40;
      if (E.vista) { E.vista = null; E.eventoAbierto = null; actualizarMapa(); resaltarSeleccion(); }
      renderPanel(); panelNormal();
    }));
    $('#btn-ayuda').addEventListener('click', () => $('#dialogo-ayuda').showModal());
    $('#asa').addEventListener('click', () => {
      const p = $('#panel');
      if (p.classList.contains('contraido')) estadoPanel('normal');
      else if (p.classList.contains('expandido')) estadoPanel('contraido');
      else estadoPanel('expandido');
    });
    $('#btn-panel').addEventListener('click', () => {
      const ocultar = panelVisible();
      document.body.dataset.escritorio = ocultar ? 'oculto' : 'visible';
      const b = $('#btn-panel');
      b.setAttribute('aria-expanded', String(!ocultar));
      b.title = ocultar ? 'Mostrar el panel' : 'Ocultar el panel';
    });
    $('#estado-actualizacion').addEventListener('click', () => {
      E.pestana = 'fuentes'; E.vista = null; actualizarMapa(); renderPanel(); panelNormal();
      if (!panelVisible()) $('#btn-panel').click();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape' || $('#dialogo-ayuda').open) return;
      if ($$('.popover').some((p) => !p.hidden)) { cerrarPopovers(); return; }
      if (E.vista) { cerrarVista(); return; }
      if (E.eventoAbierto) { E.eventoAbierto = null; renderPanel(); }
    });
  }
  function estadoPanel(modo) {
    const p = $('#panel');
    p.classList.toggle('contraido', modo === 'contraido');
    p.classList.toggle('expandido', modo === 'expandido');
    document.body.dataset.panel = modo;
  }
  function panelNormal() {
    if (esMovil()) { if ($('#panel').classList.contains('contraido')) estadoPanel('normal'); }
    else if (!panelVisible()) $('#btn-panel').click();
  }

  // ------------------------------------------------------- estado de datos
  function estadoActualizacion() {
    const est = E.datos.estado || {};
    const ultimo = est.ultimo_exito ? new Date(est.ultimo_exito).getTime() : null;
    const min = ultimo ? (Date.now() - ultimo) / 60000 : Infinity;
    const hace = ultimo ? (min < 60 ? Math.max(1, Math.round(min)) + ' min' : Math.round(min / 60) + ' h') : '';
    if (!ultimo) return { nivel: 'error', corto: 'Sin datos', detalle: 'Todavía no hubo una recopilación exitosa.' };
    if (min > 90) return { nivel: 'error', corto: `Desactualizado · ${hace}`, detalle: `Los datos están desactualizados: la última recopilación exitosa fue ${relativo(est.ultimo_exito)} (${absoluto(est.ultimo_exito)}). La recopilación automática puede estar fallando.` };
    if (min > 35) return { nivel: 'aviso', corto: `Demorado · ${hace}`, detalle: `La última recopilación exitosa fue ${relativo(est.ultimo_exito)}. Las ejecuciones programadas pueden demorarse.` };
    if (!est.ciclo_ok) return { nivel: 'aviso', corto: 'Con fallas', detalle: 'El último ciclo tuvo fallas; se muestran los datos de la última recopilación exitosa.' };
    return { nivel: 'ok', corto: `Hace ${hace}`, detalle: `Actualizado ${relativo(est.ultimo_exito)} (${absoluto(est.ultimo_exito)}).${(est.advertencias || []).length ? ' Hay advertencias menores sobre algunas fuentes (ver abajo).' : ''}` };
  }
  function renderEstado() {
    const s = estadoActualizacion();
    const p = $('#estado-actualizacion');
    p.className = 'estado estado-' + (s.nivel === 'ok' ? 'ok' : s.nivel === 'aviso' ? 'aviso' : 'error');
    p.textContent = s.corto;
    p.title = s.detalle + ' Clic para ver el estado de las fuentes.';
  }

  // Capas de detalle (regiones, mares, ciudades): se cargan después para no demorar el primer mapa.
  async function cargarDetalle() {
    try {
      const [regiones, mares, ciudades] = await Promise.all([cargarEstatico('geo/regiones.geojson'),
        cargarEstatico('geo/mares.geojson').catch(() => null), cargarEstatico('geo/ciudades.geojson').catch(() => null)]);
      E.geo.regiones = regiones; E.geo.mares = mares; E.geo.ciudades = ciudades;
      indexarRegiones();
      agregarCapasDetalle();
      if (E.vista) renderPanel();
    } catch (e) {
      avisoCapas('No se pudieron cargar las regiones del mapa. Se muestra el mapa por países.');
    }
  }

  async function refrescar() {
    try {
      const est = await cargarJSON('datos/estado.json');
      if (est.generado !== E.generado) {
        await cargarDatos();
        asignarRegiones();
        actualizarMapa(); renderPanel();
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
      const [paises, zonas] = await Promise.all([cargarEstatico('geo/paises.geojson'), cargarEstatico('geo/zonas.geojson')]);
      E.geo.paises = paises; E.geo.zonas = zonas;
      calcularBboxes();
      await cargarDatos();
    } catch (e) {
      const p = $('#estado-actualizacion');
      p.className = 'estado estado-error';
      p.textContent = 'Sin conexión con los datos';
      $('#contenido-panel').innerHTML = '<p class="alerta error">No se pudieron cargar los datos del mapa. Reintentá en unos minutos.</p>';
      return;
    }
    renderEstado(); renderCategorias(); renderLeyenda(); iniciarBusqueda(); renderPanel();
    if (window.maplibregl) iniciarMapa();
    cargarDetalle();
    if (esMovil()) estadoPanel('contraido'); else estadoPanel('normal');
    const mq = matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', renderLeyenda);
    setInterval(refrescar, 5 * 60 * 1000);
    setInterval(renderEstado, 60 * 1000);
  }
  iniciar();
})();
