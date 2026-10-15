/* Base cartográfica del mapa de conflictos (MapLibre GL JS).
 *
 * Capas de la base, de abajo hacia arriba:
 *  1. Base propia, siempre disponible y sin servicios externos: océano, tierra, límites entre
 *     países, ciudades y nombres de mares de Natural Earth (dominio público) servidos por este sitio.
 *  2. Relieve: "Blue Marble – relieve sombreado y batimetría" de NASA GIBS (sin clave ni registro;
 *     NASA pide reconocer el uso de GIBS). Alternativa opcional: "Blue Marble Next Generation"
 *     como vista satelital. Resolución máxima ~500 m: se desvanece al acercar mucho.
 *  3. Detalle al acercar (zoom ≥ 6): teselas vectoriales de OpenFreeMap (datos de OpenStreetMap;
 *     sin clave ni límite de uso; atribución obligatoria): costas precisas, ríos, rutas y ciudades.
 *
 * Si un servicio externo falla, el mapa sigue funcionando con la base propia.
 */
(function () {
  'use strict';

  const GIBS = (capa) => `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${capa}/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`;
  const ATRIB_GIBS = 'Relieve e imágenes: <a href="https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api" target="_blank" rel="noopener">NASA GIBS</a> (Blue Marble)';
  const OFM_URL = 'https://tiles.openfreemap.org/planet';
  const Z_DETALLE = 6;   // desde este zoom se piden teselas de OpenFreeMap (las de zoom bajo pesan mucho)
  const Z_CIUDADES = 6.5; // desde aquí las ciudades y límites salen de OpenFreeMap
  const Z_RELIEVE = 8.5;  // el relieve empieza a desvanecerse (resolución máxima de la imagen)

  // Paletas sobrias: mar azul profundo, tierra en tonos naturales; los colores de conflicto
  // quedan como acentos (los define app.js).
  const PALETAS = {
    claro: {
      espacio: '#d9e2ea', oceano: '#1f4566', tierra: '#e4dfcf', tierraCerca: '#ebe6d9',
      bosque: '#d3dcc1', pasto: '#e0e5cc', arena: '#efe7cf', hielo: '#f5f7f9', humedal: '#d6e0d0', urbano: '#e0dbd1',
      rio: '#2a587c', ruta: 'rgba(255,255,255,0.85)', rutaBorde: 'rgba(120,108,90,0.35)',
      limite: 'rgba(52,48,42,0.8)', limiteProv: 'rgba(60,56,50,0.4)', costa: 'rgba(30,60,90,0.55)',
      etiqueta: '#23211d', halo: 'rgba(255,253,247,0.92)', ciudad: '#2a2824', puntoCiudad: '#2f2b26', puntoBorde: '#ffffff',
      mar: '#c4d8ea', marHalo: 'rgba(14,36,56,0.5)', region: '#5c574f',
      relieve: { 'raster-saturation': -0.28, 'raster-contrast': -0.04, 'raster-brightness-min': 0.02, 'raster-brightness-max': 0.97 },
      satelite: { 'raster-saturation': -0.1, 'raster-contrast': 0, 'raster-brightness-min': 0, 'raster-brightness-max': 1 },
    },
    oscuro: {
      espacio: '#05090f', oceano: '#0c2033', tierra: '#2a2c29', tierraCerca: '#2d2f2c',
      bosque: '#273126', pasto: '#2c322a', arena: '#36332b', hielo: '#3a3f44', humedal: '#28302c', urbano: '#34332f',
      rio: '#1b3d5a', ruta: 'rgba(200,196,186,0.35)', rutaBorde: 'rgba(0,0,0,0.3)',
      limite: 'rgba(222,216,204,0.7)', limiteProv: 'rgba(222,216,204,0.3)', costa: 'rgba(150,190,225,0.5)',
      etiqueta: '#ece8df', halo: 'rgba(8,12,18,0.9)', ciudad: '#e4e0d7', puntoCiudad: '#e9e5dc', puntoBorde: '#10151b',
      mar: '#7fa6c8', marHalo: 'rgba(4,10,18,0.6)', region: '#a39d92',
      relieve: { 'raster-saturation': -0.4, 'raster-contrast': 0.05, 'raster-brightness-min': 0, 'raster-brightness-max': 0.58 },
      satelite: { 'raster-saturation': -0.2, 'raster-contrast': 0.05, 'raster-brightness-min': 0, 'raster-brightness-max': 0.8 },
    },
  };
  // Sobre la imagen satelital las etiquetas van claras con halo oscuro.
  const SOBRE_SATELITE = { etiqueta: '#ffffff', halo: 'rgba(0,0,0,0.78)', ciudad: '#f4f2ee', puntoCiudad: '#ffffff', puntoBorde: '#1a1a1a',
    limite: 'rgba(255,255,255,0.7)', limiteProv: 'rgba(255,255,255,0.35)', region: '#e2ded6' };

  // Muestra un elemento cuando su zoom mínimo (escala de Natural Earth, teselas de 256 px)
  // es menor o igual al zoom actual (teselas de 512 px, es decir, un nivel menos) + desfase.
  function filtroZoom(prop, desfase) {
    const pasos = ['step', ['zoom'], desfase];
    for (let z = 0.5; z <= 14; z += 0.5) pasos.push(z, z + desfase);
    return ['<=', ['coalesce', ['get', prop], 99], pasos];
  }

  function imagenPunto(r, relleno, borde, grosor, anillo) {
    const pr = 2, t = Math.ceil((r + grosor + 1) * 2);
    const c = document.createElement('canvas');
    c.width = c.height = t * pr;
    const x = c.getContext('2d');
    x.scale(pr, pr);
    x.beginPath(); x.arc(t / 2, t / 2, r, 0, Math.PI * 2);
    x.fillStyle = relleno; x.fill();
    x.lineWidth = grosor; x.strokeStyle = borde; x.stroke();
    if (anillo) { x.beginPath(); x.arc(t / 2, t / 2, r * 0.42, 0, Math.PI * 2); x.fillStyle = borde; x.fill(); }
    return { imagen: x.getImageData(0, 0, c.width, c.height), pixelRatio: pr };
  }

  async function detectarFuentes(base) {
    try {
      const r = await fetch(base + 'fonts/Noto%20Sans%20Regular/0-255.pbf', { method: 'HEAD', cache: 'force-cache' });
      if (r.ok) return { regular: ['Noto Sans Regular'], medio: ['Noto Sans Medium'], italica: ['Noto Sans Italic'], noto: true };
    } catch (e) { /* se usa la tipografía incluida en el repositorio */ }
    const os = ['Open Sans Semibold'];
    return { regular: os, medio: os, italica: os, noto: false };
  }

  async function cargarGeo(base, ruta) {
    try { const r = await fetch(base + ruta + '?g=3'); if (r.ok) return await r.json(); } catch (e) { /* capa opcional */ }
    return { type: 'FeatureCollection', features: [] };
  }

  /**
   * Crea el mapa con la base cartográfica.
   * op: { contenedor, base (URL del sitio), oscuro(): bool, paises (GeoJSON), alAviso(texto),
   *       modo: 'relieve'|'satelite'|'simple', globo: bool, detalle: bool, centro, zoom }
   */
  async function crear(op) {
    const fuentes = await detectarFuentes(op.base);
    const [limites, ciudades, maresEt] = await Promise.all([
      cargarGeo(op.base, 'geo/limites.geojson'), cargarGeo(op.base, 'geo/ciudades.geojson'), cargarGeo(op.base, 'geo/mares-et.geojson')]);
    const estado = { modo: op.modo || 'relieve', globo: op.globo !== false, detalle: op.detalle !== false,
      falloDetalle: false, falloRelieve: false, erroresDetalle: 0, erroresRelieve: 0 };
    const paleta = () => {
      const P = PALETAS[op.oscuro() ? 'oscuro' : 'claro'];
      return estado.modo === 'satelite' ? Object.assign({}, P, SOBRE_SATELITE) : P;
    };
    const P = paleta();

    const mapa = new maplibregl.Map({
      container: op.contenedor,
      style: {
        version: 8,
        glyphs: op.base + 'fonts/{fontstack}/{range}.pbf',
        projection: { type: estado.globo ? 'globe' : 'mercator' },
        sky: { 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 0.9, 3, 0.6, 5.5, 0] },
        sources: {
          'base-paises': { type: 'geojson', data: op.paises, attribution: 'Geografía: <a href="https://www.naturalearthdata.com/" target="_blank" rel="noopener">Natural Earth</a>' },
          'base-limites': { type: 'geojson', data: limites },
          'base-ciudades': { type: 'geojson', data: ciudades },
          'base-mares': { type: 'geojson', data: maresEt },
          relieve: { type: 'raster', tiles: [GIBS('BlueMarble_ShadedRelief_Bathymetry')], tileSize: 256, maxzoom: 8, attribution: ATRIB_GIBS },
          satelite: { type: 'raster', tiles: [GIBS('BlueMarble_NextGeneration')], tileSize: 256, maxzoom: 8, attribution: ATRIB_GIBS },
          ofm: { type: 'vector', url: OFM_URL },
        },
        layers: [],
      },
      center: op.centro || [25, 22], zoom: op.zoom != null ? op.zoom : 1.3, minZoom: 0.4, maxZoom: 14,
      attributionControl: false, dragRotate: false, pitchWithRotate: false, renderWorldCopies: true,
    });
    mapa.touchZoomRotate.disableRotation();

    // Fallos de servicios externos: tras varios errores se deja de pedir esa capa.
    let listo = false;
    mapa.on('error', (e) => {
      if (!e) return;
      const texto = String((e.error && e.error.message) || '');
      if (!e.sourceId && texto.includes('openfreemap')) e.sourceId = 'ofm';
      if (!e.sourceId) return;
      // Un error sin tesela es del índice (TileJSON): el servicio no responde, se descarta enseguida.
      if (e.sourceId === 'ofm' && !estado.falloDetalle && (++estado.erroresDetalle >= 4 || !e.tile)) {
        estado.falloDetalle = true; if (listo) actualizar();
        op.alAviso && op.alAviso('No se pudo cargar el detalle de OpenFreeMap (ríos, rutas y costas precisas). Se usa la base propia.');
      }
      if ((e.sourceId === 'relieve' || e.sourceId === 'satelite') && !estado.falloRelieve && ++estado.erroresRelieve >= 6) {
        estado.falloRelieve = true;
        if (estado.modo === 'satelite') estado.modo = 'relieve';
        if (listo) actualizar();
        op.alAviso && op.alAviso('No se pudo cargar el relieve de NASA GIBS. Se usa el mapa simple.');
      }
    });

    await new Promise((ok) => mapa.on('load', ok));
    // Íconos de ciudades (se regeneran al cambiar el tema).
    const iconos = () => {
      const Q = paleta();
      return { 'ciudad': imagenPunto(2.4, Q.puntoCiudad, Q.puntoBorde, 1.2), 'capital': imagenPunto(3.6, Q.puntoBorde, Q.puntoCiudad, 1.4, true) };
    };
    for (const [id, im] of Object.entries(iconos())) mapa.addImage(id, im.imagen, { pixelRatio: im.pixelRatio });

    const nombre = ['coalesce', ['get', 'name:es'], ['get', 'name:latin'], ['get', 'name']];
    const capas = [
      { id: 'fondo', type: 'background', paint: { 'background-color': P.oceano } },
      { id: 'base-tierra', type: 'fill', source: 'base-paises', paint: { 'fill-color': P.tierra, 'fill-antialias': false } },
      // Detalle de la cobertura del suelo (debajo del relieve: aparece cuando el relieve se desvanece).
      { id: 'ofm-cobertura', type: 'fill', source: 'ofm', 'source-layer': 'landcover', minzoom: 7,
        filter: ['in', ['get', 'class'], ['literal', ['wood', 'grass', 'sand', 'ice', 'wetland', 'rock', 'farmland']]],
        paint: { 'fill-color': ['match', ['get', 'class'], 'wood', P.bosque, 'grass', P.pasto, 'farmland', P.pasto, 'sand', P.arena,
          'ice', P.hielo, 'wetland', P.humedal, P.tierraCerca], 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0, 9, 0.75] } },
      { id: 'ofm-urbano', type: 'fill', source: 'ofm', 'source-layer': 'landuse', minzoom: 9,
        filter: ['in', ['get', 'class'], ['literal', ['residential', 'commercial', 'industrial', 'retail']]],
        paint: { 'fill-color': P.urbano, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0, 11, 0.8] } },
      { id: 'relieve', type: 'raster', source: 'relieve', paint: Object.assign({ 'raster-fade-duration': 200 }, P.relieve) },
      { id: 'satelite', type: 'raster', source: 'satelite', layout: { visibility: 'none' }, paint: Object.assign({ 'raster-fade-duration': 200 }, P.satelite) },
      { id: 'ancla-tinte', type: 'background', layout: { visibility: 'none' } },
      // Agua con costas precisas al acercar (tapa los bordes simplificados de los países).
      { id: 'ofm-agua', type: 'fill', source: 'ofm', 'source-layer': 'water', minzoom: Z_DETALLE,
        paint: { 'fill-color': P.oceano, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], Z_DETALLE, 0, 7.5, 1] } },
      { id: 'ofm-rios', type: 'line', source: 'ofm', 'source-layer': 'waterway', minzoom: 7,
        filter: ['any', ['==', ['get', 'class'], 'river'], ['all', ['>=', ['zoom'], 11], ['in', ['get', 'class'], ['literal', ['canal', 'stream']]]]],
        paint: { 'line-color': P.rio, 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 0.6, 12, 2.2] } },
      { id: 'ofm-rutas-borde', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 9,
        filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary']]],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': P.rutaBorde, 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 1.6, 14, 6] } },
      { id: 'ofm-rutas', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 7,
        filter: ['any', ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary']]],
          ['all', ['>=', ['zoom'], 10], ['in', ['get', 'class'], ['literal', ['secondary', 'tertiary']]]],
          ['all', ['>=', ['zoom'], 12.5], ['in', ['get', 'class'], ['literal', ['minor', 'service']]]]],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': P.ruta, 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 0.5, 10, 1.2, 14, 4],
          'line-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.4, 9, 0.9] } },
      { id: 'base-costa', type: 'line', source: 'base-paises', layout: { visibility: 'none' },
        paint: { 'line-color': P.costa, 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.4, 6, 1] } },
      { id: 'ancla-zonas', type: 'background', layout: { visibility: 'none' } },
      { id: 'base-limites', type: 'line', source: 'base-limites', maxzoom: Z_CIUDADES, filter: ['!=', ['get', 'd'], 1],
        layout: { 'line-join': 'round' },
        paint: { 'line-color': P.limite, 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.5, 4, 0.9, 6, 1.2] } },
      { id: 'base-limites-disputa', type: 'line', source: 'base-limites', maxzoom: Z_CIUDADES, filter: ['==', ['get', 'd'], 1],
        paint: { 'line-color': P.limite, 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.5, 4, 0.9, 6, 1.2], 'line-dasharray': [3, 2] } },
      { id: 'ofm-limites-prov', type: 'line', source: 'ofm', 'source-layer': 'boundary', minzoom: Z_CIUDADES,
        filter: ['all', ['==', ['get', 'admin_level'], 4], ['!=', ['get', 'maritime'], 1]],
        paint: { 'line-color': P.limiteProv, 'line-width': ['interpolate', ['linear'], ['zoom'], 6.5, 0.5, 12, 1.2], 'line-dasharray': [3, 2] } },
      { id: 'ofm-limites', type: 'line', source: 'ofm', 'source-layer': 'boundary', minzoom: Z_CIUDADES,
        filter: ['all', ['==', ['get', 'admin_level'], 2], ['!=', ['get', 'maritime'], 1], ['!=', ['get', 'disputed'], 1]],
        layout: { 'line-join': 'round' },
        paint: { 'line-color': P.limite, 'line-width': ['interpolate', ['linear'], ['zoom'], 6.5, 1.2, 12, 2.2] } },
      { id: 'ofm-limites-disputa', type: 'line', source: 'ofm', 'source-layer': 'boundary', minzoom: Z_CIUDADES,
        filter: ['all', ['==', ['get', 'admin_level'], 2], ['!=', ['get', 'maritime'], 1], ['==', ['get', 'disputed'], 1]],
        paint: { 'line-color': P.limite, 'line-width': ['interpolate', ['linear'], ['zoom'], 6.5, 1.2, 12, 2.2], 'line-dasharray': [3, 2] } },
      { id: 'ancla-etiquetas', type: 'background', layout: { visibility: 'none' } },
      // Nombres de océanos y mares.
      { id: 'base-mares', type: 'symbol', source: 'base-mares', filter: filtroZoom('z', 1),
        layout: { 'text-field': ['case', ['==', ['get', 'o'], 1], ['upcase', ['get', 'n']], ['get', 'n']], 'text-font': fuentes.italica,
          'text-size': ['case', ['==', ['get', 'o'], 1], 13, 11.5], 'text-letter-spacing': ['case', ['==', ['get', 'o'], 1], 0.3, 0.04],
          'text-max-width': 7, 'text-padding': 6 },
        paint: { 'text-color': P.mar, 'text-halo-color': P.marHalo, 'text-halo-width': 0.8 } },
      { id: 'ofm-agua-nombres', type: 'symbol', source: 'ofm', 'source-layer': 'water_name', minzoom: Z_DETALLE,
        filter: ['==', ['geometry-type'], 'Point'],
        layout: { 'text-field': nombre, 'text-font': fuentes.italica, 'text-size': 11.5, 'text-max-width': 7 },
        paint: { 'text-color': P.mar, 'text-halo-color': P.marHalo, 'text-halo-width': 0.8 } },
      { id: 'ofm-agua-nombres-linea', type: 'symbol', source: 'ofm', 'source-layer': 'water_name', minzoom: Z_DETALLE,
        filter: ['==', ['geometry-type'], 'LineString'],
        layout: { 'text-field': nombre, 'text-font': fuentes.italica, 'text-size': 11.5, 'symbol-placement': 'line' },
        paint: { 'text-color': P.mar, 'text-halo-color': P.marHalo, 'text-halo-width': 0.8 } },
      // Ciudades: propias (Natural Earth, nombres en español) con zoom bajo; de OpenFreeMap al acercar.
      { id: 'base-ciudades', type: 'symbol', source: 'base-ciudades', filter: filtroZoom('z', 0.4), maxzoom: Z_CIUDADES,
        layout: { 'icon-image': ['case', ['==', ['get', 'cap'], 1], 'capital', 'ciudad'], 'symbol-sort-key': ['get', 'k'],
          'text-field': ['get', 'n'], 'text-font': ['case', ['==', ['get', 'cap'], 1], ['literal', fuentes.medio], ['literal', fuentes.regular]],
          'text-size': ['interpolate', ['linear'], ['zoom'], 2, ['case', ['==', ['get', 'cap'], 1], 11.5, 11], 6, ['case', ['==', ['get', 'cap'], 1], 13.5, 12.5]],
          'text-variable-anchor': ['right', 'left', 'top', 'bottom'], 'text-radial-offset': 0.55, 'text-justify': 'auto',
          'text-max-width': 8, 'text-padding': 3 },
        paint: { 'text-color': P.ciudad, 'text-halo-color': P.halo, 'text-halo-width': 1.4 } },
      { id: 'ofm-lugares', type: 'symbol', source: 'ofm', 'source-layer': 'place', minzoom: Z_CIUDADES,
        filter: ['any', ['==', ['get', 'class'], 'city'], ['all', ['>=', ['zoom'], 8], ['==', ['get', 'class'], 'town']],
          ['all', ['>=', ['zoom'], 10.5], ['==', ['get', 'class'], 'village']]],
        layout: { 'icon-image': ['case', ['<=', ['coalesce', ['get', 'capital'], 9], 2], 'capital', 'ciudad'],
          'symbol-sort-key': ['coalesce', ['get', 'rank'], 20],
          'text-field': nombre, 'text-font': ['case', ['==', ['get', 'class'], 'city'], ['literal', fuentes.medio], ['literal', fuentes.regular]],
          'text-size': ['interpolate', ['linear'], ['zoom'], 6, ['match', ['get', 'class'], 'city', 12.5, 'town', 11.5, 11],
            12, ['match', ['get', 'class'], 'city', 16, 'town', 13.5, 12]],
          'text-variable-anchor': ['right', 'left', 'top', 'bottom'], 'text-radial-offset': 0.55, 'text-justify': 'auto',
          'text-max-width': 8, 'text-padding': 3 },
        paint: { 'text-color': P.ciudad, 'text-halo-color': P.halo, 'text-halo-width': 1.4 } },
    ];
    capas.forEach((c) => mapa.addLayer(c));

    const CAPAS_OFM = capas.filter((c) => c.source === 'ofm').map((c) => c.id);
    const visible = (id, on) => mapa.getLayer(id) && mapa.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    const usarDetalle = () => estado.detalle && !estado.falloDetalle && estado.modo !== 'simple';

    // Aplica modo de base, detalle y fallos a la visibilidad de las capas.
    function actualizar() {
      const Q = paleta();
      const detalle = usarDetalle();
      const raster = estado.modo === 'relieve' && !estado.falloRelieve;
      visible('relieve', raster);
      visible('satelite', estado.modo === 'satelite');
      CAPAS_OFM.forEach((id) => visible(id, detalle));
      if (detalle && estado.modo === 'satelite') ['ofm-cobertura', 'ofm-urbano', 'ofm-agua'].forEach((id) => visible(id, false));
      visible('base-costa', estado.modo === 'simple' || (!raster && estado.modo !== 'satelite'));
      // Con el detalle activo, desde zoom 8 la tierra es el fondo y el agua la dibuja OpenFreeMap;
      // sin detalle, el fondo es siempre mar y la tierra sale de los polígonos propios.
      mapa.setPaintProperty('fondo', 'background-color', detalle && estado.modo !== 'satelite'
        ? ['step', ['zoom'], Q.oceano, 8, Q.tierraCerca] : Q.oceano);
      mapa.setLayerZoomRange('base-tierra', 0, detalle && estado.modo !== 'satelite' ? 8 : 24);
      const desvanecer = detalle ? ['interpolate', ['linear'], ['zoom'], Z_RELIEVE, 1, 9.5, 0] : 1;
      mapa.setPaintProperty('relieve', 'raster-opacity', desvanecer);
      mapa.setPaintProperty('satelite', 'raster-opacity', 1);
      ['base-limites', 'base-limites-disputa'].forEach((id) => mapa.setLayerZoomRange(id, 0, detalle ? Z_CIUDADES : 24));
      mapa.setLayerZoomRange('base-ciudades', 0, detalle ? Z_CIUDADES : 24);
      mapa.setLayerZoomRange('base-mares', 0, detalle ? Z_DETALLE : 24);
      document.documentElement.dataset.base = estado.modo;
    }

    function aplicarTema() {
      const Q = paleta();
      const pintar = (id, prop, v) => mapa.getLayer(id) && mapa.setPaintProperty(id, prop, v);
      pintar('base-tierra', 'fill-color', Q.tierra);
      pintar('ofm-cobertura', 'fill-color', ['match', ['get', 'class'], 'wood', Q.bosque, 'grass', Q.pasto, 'farmland', Q.pasto, 'sand', Q.arena,
        'ice', Q.hielo, 'wetland', Q.humedal, Q.tierraCerca]);
      pintar('ofm-urbano', 'fill-color', Q.urbano);
      Object.entries(Q.relieve).forEach(([k, v]) => pintar('relieve', k, v));
      Object.entries(Q.satelite).forEach(([k, v]) => pintar('satelite', k, v));
      pintar('ofm-agua', 'fill-color', Q.oceano);
      pintar('ofm-rios', 'line-color', Q.rio);
      pintar('ofm-rutas', 'line-color', Q.ruta); pintar('ofm-rutas-borde', 'line-color', Q.rutaBorde);
      pintar('base-costa', 'line-color', Q.costa);
      ['base-limites', 'base-limites-disputa', 'ofm-limites', 'ofm-limites-disputa'].forEach((id) => pintar(id, 'line-color', Q.limite));
      pintar('ofm-limites-prov', 'line-color', Q.limiteProv);
      ['base-mares', 'ofm-agua-nombres', 'ofm-agua-nombres-linea'].forEach((id) => { pintar(id, 'text-color', Q.mar); pintar(id, 'text-halo-color', Q.marHalo); });
      ['base-ciudades', 'ofm-lugares'].forEach((id) => { pintar(id, 'text-color', Q.ciudad); pintar(id, 'text-halo-color', Q.halo); });
      for (const [id, im] of Object.entries(iconos())) mapa.updateImage(id, im.imagen);
      document.querySelector(':root').style.setProperty('--espacio', Q.espacio);
      actualizar();
    }

    listo = true;
    actualizar();
    aplicarTema();

    return {
      mapa, fuentes, paleta, estado,
      establecerBase(modo) { estado.modo = modo; if (modo !== 'simple') estado.falloRelieve = false; aplicarTema(); },
      establecerDetalle(on) { estado.detalle = on; actualizar(); },
      establecerGlobo(on) { estado.globo = on; mapa.setProjection({ type: on ? 'globe' : 'mercator' }); },
      aplicarTema,
      textoEstado() {
        if (estado.modo === 'simple') return 'Mapa simple: solo datos propios, sin servicios externos.';
        const partes = [];
        partes.push(estado.falloRelieve ? 'Relieve de NASA no disponible (se usa el mapa simple).' : estado.modo === 'satelite' ? 'Imagen satelital: NASA Blue Marble.' : 'Relieve: NASA Blue Marble.');
        if (!estado.detalle) partes.push('Detalle al acercar desactivado.');
        else partes.push(estado.falloDetalle ? 'Detalle de OpenFreeMap no disponible.' : 'Detalle al acercar: OpenFreeMap.');
        return partes.join(' ');
      },
    };
  }

  window.Cartografia = { crear, PALETAS };
})();
