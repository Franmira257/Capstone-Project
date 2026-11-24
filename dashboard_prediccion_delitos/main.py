import asyncio
import base64
import json
import re
from datetime import datetime, timedelta, timezone
from html import escape
from io import StringIO

import httpx
import pandas as pd
from apify import Actor
from plotly.offline import get_plotlyjs

# Store con nombre: el link publico queda fijo entre ejecuciones
NOMBRE_STORE = 'dashboard-delitos'
# Solo se usa si no se puede leer el ID del store en tiempo de ejecucion
STORE_ID_FALLBACK = 'L5clvk5DrTpjhKgYY'

TZ_AR = timezone(timedelta(hours=-3))

# Limites aproximados de CABA (grados)
LON_MIN, LON_MAX = -58.5315, -58.3351
LAT_MIN, LAT_MAX = -34.7056, -34.5266
ANCHO_PX = 2000

URL_SATELITE = (
    'https://services.arcgisonline.com/ArcGIS/rest/services/'
    'World_Imagery/MapServer/export'
)

# El CSS va embebido: ya no hace falta styles.css
CSS = """
:root{--azul:#4b5bd6;--fondo:#f4f6fb;--texto:#1f2430;--suave:#5c6577;
  --borde:#e1e5ee;--rojo:#d94a38}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
  background:var(--fondo);color:var(--texto);line-height:1.45}
.wrap{max-width:1280px;margin:0 auto;padding:16px}
.topbar{display:flex;justify-content:space-between;align-items:center;
  flex-wrap:wrap;gap:12px;margin-bottom:6px}
.topbar h1{font-size:24px;margin:0}
.sub{margin:0 0 8px;font-size:13px;color:var(--suave)}
.btn{background:var(--azul);color:#fff;border:0;border-radius:8px;
  padding:10px 16px;cursor:pointer;font-size:14px;font-weight:600}
.btn:hover{filter:brightness(1.08)}
.btn-sec{background:#fff;color:var(--azul);border:1px solid var(--azul)}
.controles{display:flex;flex-wrap:wrap;gap:12px 18px;align-items:flex-end;
  background:#fff;border:1px solid var(--borde);border-radius:10px;
  padding:12px 14px;margin:12px 0}
.ctl{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--suave)}
.ctl label{font-weight:600}
.ctl select{padding:8px 10px;border:1px solid #c9cfdd;border-radius:6px;
  font-size:14px;background:#fff;color:var(--texto)}
.estado{font-size:13px;color:var(--suave);margin:4px 2px 10px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0}
.card{background:#fff;border:1px solid var(--borde);border-radius:10px;
  padding:12px 14px}
.card .t{font-size:11px;color:var(--suave);text-transform:uppercase;
  letter-spacing:.05em;font-weight:600}
.card .v{font-size:28px;font-weight:700;margin-top:4px}
.card .s{font-size:12px;color:var(--suave);margin-top:2px}
.graf{background:#fff;border:1px solid var(--borde);border-radius:10px;
  margin-bottom:16px;width:100%}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.desc{color:var(--suave);margin:6px 0}
.nota-box{background:#fff;border:1px solid var(--borde);border-radius:10px;
  padding:10px 14px;margin:8px 0 16px;font-size:14px}
.nota-box summary{cursor:pointer;font-weight:600}
.nota-box p{margin:8px 0 0;color:var(--suave)}
.nota{font-size:12px;color:#7a8396;margin:8px 0}
input[type=range]{width:150px}
.oculto{display:none !important}
@media (max-width:900px){
  .cards{grid-template-columns:repeat(2,1fr)}
  .grid2{grid-template-columns:1fr}
}
@media (max-width:520px){
  .wrap{padding:10px}
  .topbar h1{font-size:19px}
  .btn{width:100%}
  .card .v{font-size:22px}
  .controles{gap:10px}
  .ctl{width:100%}
  .ctl select,input[type=range]{width:100%}
}
"""


# ---------------------------------------------------------------------------
# Utilidades de descarga y lectura
# ---------------------------------------------------------------------------
def normalizar_url(valor: str) -> str:
    """Convierte un File ID o enlace de Google Drive en descarga directa."""
    v = valor.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{15,}', v):
        return f'https://drive.google.com/uc?export=download&id={v}'
    m = re.search(r'/d/([A-Za-z0-9_-]+)', v)
    if 'drive.google.com' in v and m:
        return f'https://drive.google.com/uc?export=download&id={m.group(1)}'
    return v


def decodificar(raw: bytes) -> str:
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1', errors='replace')


def leer_csv_texto(texto: str) -> pd.DataFrame:
    """Lee un CSV desde texto detectando coma o punto y coma."""
    lineas = texto.splitlines()
    primera = lineas[0] if lineas else ''
    sep = ';' if primera.count(';') > primera.count(',') else ','
    return pd.read_csv(StringIO(texto), sep=sep, low_memory=False)


def normalizar_texto_csv(texto: str) -> str:
    """Deshace escapes si el CSV llego como texto con \\n y \\" literales."""
    if '\n' not in texto and '\\n' in texto:
        texto = (
            texto.replace('\\r', '')
            .replace('\\n', '\n')
            .replace('\\"', '"')
        )
    return texto


def descargar_satelite():
    """Descarga una imagen satelital de CABA y la devuelve como data URI."""
    alto = round(ANCHO_PX * (LAT_MAX - LAT_MIN) / (LON_MAX - LON_MIN))
    params = {
        'bbox': f'{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}',
        'bboxSR': 4326,
        'imageSR': 4326,
        'size': f'{ANCHO_PX},{alto}',
        'format': 'jpg',
        'f': 'image',
    }
    r = httpx.get(
        URL_SATELITE, params=params, timeout=90, follow_redirects=True
    )
    r.raise_for_status()
    tipo = r.headers.get('content-type', '')
    if not tipo.startswith('image'):
        raise ValueError('Respuesta inesperada: ' + r.text[:200])
    b64 = base64.b64encode(r.content).decode()
    return 'data:image/jpeg;base64,' + b64


def parsear_contorno_geojson(gj: dict):
    """Convierte un dict GeoJSON en lineas x/y para Plotly."""
    xs, ys = [], []
    for feat in gj.get('features', []):
        geom = feat.get('geometry') or {}
        gtype = geom.get('type')
        coords = geom.get('coordinates') or []
        polis = coords if gtype == 'MultiPolygon' else [coords]
        for poli in polis:
            for anillo in poli:
                for punto in anillo:
                    xs.append(punto[0])
                    ys.append(punto[1])
                xs.append(None)
                ys.append(None)
    validos = [v for v in xs if v is not None]
    if not validos or max(abs(v) for v in validos) > 180:
        raise ValueError('El GeoJSON no esta en coordenadas lat/lon.')
    return {'x': xs, 'y': ys}


def cargar_contorno_desde_url(url: str):
    """Descarga y parsea un GeoJSON desde una URL."""
    r = httpx.get(normalizar_url(url), timeout=60, follow_redirects=True)
    r.raise_for_status()
    return parsear_contorno_geojson(r.json())


def cargar_df_desde_url(url: str) -> pd.DataFrame:
    """Descarga un CSV o JSON desde una URL y devuelve un DataFrame."""
    url = normalizar_url(url)
    r = httpx.get(url, timeout=90, follow_redirects=True)
    r.raise_for_status()
    ctype = r.headers.get('content-type', '').lower()
    if 'json' in ctype or url.lower().endswith('.json'):
        data = r.json()
        if isinstance(data, dict) and 'data' in data:
            data = data['data']
        return pd.DataFrame(data)
    texto = decodificar(r.content)
    if texto.lstrip().lower().startswith(('<!doctype html', '<html')):
        raise ValueError(
            'La URL devolvio una pagina HTML y no un CSV. '
            'Revisa que el archivo este compartido publicamente.'
        )
    return leer_csv_texto(texto)


async def cargar_df_desde_dataset(dataset_id: str) -> pd.DataFrame:
    """Lee todos los items de un dataset de Apify por su ID."""
    dataset = await Actor.open_dataset(id=dataset_id, force_cloud=True)
    items = []
    async for item in dataset.iterate_items():
        items.append(item)
    return pd.DataFrame(items)


def buscar_columna(df: pd.DataFrame, candidatos_exactos, prefijos):
    """Busca una columna por nombre exacto o por prefijo (case-insensitive)."""
    cols_map = {c.strip().lower(): c for c in df.columns}
    for cand in candidatos_exactos:
        key = cand.strip().lower()
        if key in cols_map:
            return cols_map[key]
    for pref in prefijos:
        p = pref.strip().lower()
        for low_c, orig_c in cols_map.items():
            if low_c.startswith(p):
                return orig_c
    return None


def a_lista(serie):
    """Convierte una serie a lista con None donde hay NaN."""
    return [None if pd.isna(v) else v for v in serie.tolist()]


def a_js(obj):
    """Serializa a JSON seguro para incrustar dentro de un <script>."""
    return json.dumps(obj, ensure_ascii=False).replace('</', '<\\/')


def fmt_comuna(v) -> str:
    """Muestra la comuna como entero (1.0 -> '1')."""
    if pd.isna(v):
        return 'Sin dato'
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------------------
# Construccion de datos para el dashboard
# ---------------------------------------------------------------------------
async def obtener_df_predicciones(inp: dict):
    """Obtiene el DataFrame de predicciones desde la fuente disponible.

    Orden de prioridad: dataset_id, lista 'predicciones', texto CSV, URL.
    """
    dataset_id = (inp.get('dataset_id') or '').strip()
    pred_input = inp.get('predicciones')
    texto = (inp.get('csv_predicciones_texto') or '').strip()
    url = (inp.get('csv_predicciones_url') or '').strip()

    if dataset_id:
        Actor.log.info(f'Leyendo predicciones del dataset {dataset_id}...')
        return await cargar_df_desde_dataset(dataset_id)

    if isinstance(pred_input, list) and len(pred_input) > 0:
        if len(pred_input) == 1 and isinstance(pred_input[0], list):
            return pd.DataFrame(pred_input[0])
        return pd.DataFrame(pred_input)

    if texto:
        Actor.log.info('Leyendo predicciones desde texto CSV...')
        return leer_csv_texto(normalizar_texto_csv(texto))

    if url:
        Actor.log.info('Leyendo predicciones desde URL...')
        return cargar_df_desde_url(url)

    return None


def construir_predicciones(df):
    """Arma la estructura compacta de predicciones.

    Los puntos (lat, lon, comuna, distancia) se guardan una sola vez y cada
    fila (punto x hora) solo guarda el indice del punto, la hora y la
    probabilidad. Asi el HTML pesa mucho menos.
    """
    if df is None or df.empty:
        return None

    col_comuna = buscar_columna(df, ['Comuna', 'comuna'], ['comuna'])
    col_hora = buscar_columna(
        df, ['Franja Horaria', 'franja_horaria', 'hora'], ['franja']
    )
    col_lat = buscar_columna(df, ['Latitud', 'latitud', 'lat'], ['lat'])
    col_lon = buscar_columna(df, ['Longitud', 'longitud', 'lon', 'lng'], ['lon'])
    col_dist = buscar_columna(
        df,
        ['distancia_luminaria_cercana_m'],
        ['distancia_luminaria', 'distancia'],
    )
    col_prob = buscar_columna(
        df,
        ['probabilidad_hurto_futura', 'probabilidad_hurto', 'probabilidad'],
        ['probabilidad_hurto', 'probabilidad'],
    )

    if col_prob is None or col_lat is None or col_lon is None:
        raise ValueError(
            'Faltan columnas de probabilidad, latitud o longitud. '
            f'Columnas recibidas: {list(df.columns)}'
        )

    work = pd.DataFrame({
        'comuna': df[col_comuna].map(fmt_comuna)
        if col_comuna else 'Sin dato',
        'hora': pd.to_numeric(df[col_hora], errors='coerce').round()
        if col_hora else float('nan'),
        'lat': pd.to_numeric(df[col_lat], errors='coerce').round(6),
        'lon': pd.to_numeric(df[col_lon], errors='coerce').round(6),
        'dist': pd.to_numeric(df[col_dist], errors='coerce').round(1)
        if col_dist else float('nan'),
        'prob': pd.to_numeric(df[col_prob], errors='coerce').round(4),
    })
    work = work.dropna(subset=['lat', 'lon', 'prob']).reset_index(drop=True)
    if work.empty:
        return None

    work['pt'] = work.groupby(['comuna', 'lat', 'lon'], sort=False).ngroup()
    pts = work.drop_duplicates('pt').sort_values('pt')

    return {
        'pt': work['pt'].tolist(),
        'hora': a_lista(work['hora'].astype('Int64')),
        'prob': work['prob'].tolist(),
        'plat': pts['lat'].tolist(),
        'plon': pts['lon'].tolist(),
        'pcom': pts['comuna'].tolist(),
        'pdist': a_lista(pts['dist']),
    }


APP_JS = r"""
const CFG = __CFG__;
const P = __PRED__;
const CONTORNO = __CONTORNO__;
const IMG = __IMG__;

const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n).toLocaleString('es-AR');
const pct = (v, d = 1) => (v * 100).toFixed(d).replace('.', ',') + '%';
const esNoche = (h) => h >= 20 || h <= 6;
const altoMapa = () => Math.max(420, Math.min(700, Math.round(window.innerWidth * 0.8)));
const CFG_GRAF = {responsive: true, displaylogo: false};
const CFG_MAPA = {
  responsive: true, displaylogo: false, scrollZoom: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d'],
};

function imagenesFondo() {
  return IMG ? [{
    source: IMG, xref: 'x', yref: 'y',
    x: CFG.lonMin, y: CFG.latMax,
    sizex: CFG.lonMax - CFG.lonMin, sizey: CFG.latMax - CFG.latMin,
    xanchor: 'left', yanchor: 'top', sizing: 'stretch', layer: 'below',
  }] : [];
}

function trazaContorno() {
  if (!CONTORNO) return null;
  return {
    type: 'scatter', mode: 'lines', x: CONTORNO.x, y: CONTORNO.y,
    line: {color: IMG ? '#ffffff' : '#444444', width: 1.5},
    hoverinfo: 'skip', showlegend: false,
  };
}

function layoutMapa(titulo, extra) {
  return Object.assign({
    title: {text: titulo},
    height: altoMapa(),
    margin: {t: 50, r: 10, b: 60, l: 70},
    dragmode: 'pan', plot_bgcolor: 'white', images: imagenesFondo(),
    xaxis: {
      range: [CFG.lonMin, CFG.lonMax], constrain: 'domain',
      showgrid: false, title: {text: 'Longitud'},
    },
    yaxis: {
      range: [CFG.latMin, CFG.latMax], showgrid: false,
      scaleanchor: 'x', scaleratio: 1.21, title: {text: 'Latitud'},
    },
  }, extra || {});
}

// ===================== VISTA PREDICCION =====================
const selHora = $('filtro-hora');
const selTurno = $('filtro-turno');
const selComuna = $('filtro-comuna');
const rngTam = $('tam-punto');
const btnPlay = $('btn-play');
let PMIN = 0;
let PMAX = 1;
let horasLista = [];
let timer = null;

function detenerAnim() {
  if (timer) { clearInterval(timer); timer = null; }
  btnPlay.textContent = '▶ Animar horas';
}

function pasoAnim() {
  if (!horasLista.length) return;
  const actual = selHora.value === '' ? -1 : horasLista.indexOf(Number(selHora.value));
  selHora.value = String(horasLista[(actual + 1) % horasLista.length]);
  renderPred();
}

btnPlay.addEventListener('click', () => {
  if (timer) { detenerAnim(); return; }
  btnPlay.textContent = '⏸ Pausar';
  pasoAnim();
  timer = setInterval(pasoAnim, 900);
});

function initFiltrosPred() {
  if (!P) return;

  // Escala de color fija (min/max reales) para comparar entre filtros
  if (P.prob.length) {
    PMIN = P.prob.reduce((a, v) => (v < a ? v : a), Infinity);
    PMAX = P.prob.reduce((a, v) => (v > a ? v : a), -Infinity);
    if (PMIN === PMAX) { PMIN = Math.max(0, PMIN - 0.05); PMAX = PMAX + 0.05; }
  }

  horasLista = Array.from(
    new Set(P.hora.filter((h) => h !== null).map(Number))
  ).sort((a, b) => a - b);

  const optH = document.createElement('option');
  optH.value = '';
  optH.textContent = 'Todas (promedio 0–23 h)';
  selHora.appendChild(optH);
  horasLista.forEach((h) => {
    const o = document.createElement('option');
    o.value = String(h);
    o.textContent = h + ' h';
    selHora.appendChild(o);
  });

  const comunas = Array.from(new Set(P.pcom)).sort(
    (a, b) => a.localeCompare(b, 'es', {numeric: true})
  );
  const optC = document.createElement('option');
  optC.value = '';
  optC.textContent = 'Todas las comunas';
  selComuna.appendChild(optC);
  comunas.forEach((c) => {
    const o = document.createElement('option');
    o.value = c;
    o.textContent = 'Comuna ' + c;
    selComuna.appendChild(o);
  });

  selHora.addEventListener('change', () => { detenerAnim(); renderPred(); });
  selTurno.addEventListener('change', renderPred);
  selComuna.addEventListener('change', renderPred);
  rngTam.addEventListener('input', renderPred);
}

function pasaFranja(h, hSel, tSel) {
  if (h === null || h === undefined) return false;
  if (hSel !== '') return String(h) === hSel;
  if (tSel === '') return true;
  return (tSel === 'noche') === esNoche(Number(h));
}

function descFranja(hSel, tSel) {
  if (hSel !== '') return hSel + ' h';
  if (tSel === 'noche') return 'noche (20–6 h)';
  if (tSel === 'dia') return 'día (7–19 h)';
  return 'promedio de las 24 h';
}

function renderPred() {
  const aviso = $('sin-pred');
  const conteo = $('conteo-pred');
  if (!P) {
    aviso.classList.remove('oculto');
    conteo.textContent = 'Sin datos de predicción cargados';
    return;
  }
  aviso.classList.add('oculto');

  const hSel = selHora.value;
  const tSel = selTurno.value;
  const cSel = selComuna.value;
  selTurno.disabled = hSel !== '';

  const npts = P.plat.length;
  const sumP = new Float64Array(npts);
  const nP = new Uint16Array(npts);
  const curvaS = new Array(24).fill(0);
  const curvaN = new Array(24).fill(0);
  const comS = new Map();
  const comN = new Map();
  let nFilas = 0;
  let suma = 0;

  for (let i = 0; i < P.prob.length; i++) {
    const k = P.pt[i];
    const c = P.pcom[k];
    const h = P.hora[i];
    const p = Number(P.prob[i]);
    const okC = cSel === '' || c === cSel;
    const okF = pasaFranja(h, hSel, tSel);

    if (okC && h !== null) {
      const hh = Math.round(Number(h));
      if (hh >= 0 && hh < 24) { curvaS[hh] += p; curvaN[hh] += 1; }
    }
    if (okF) {
      comS.set(c, (comS.get(c) || 0) + p);
      comN.set(c, (comN.get(c) || 0) + 1);
    }
    if (okC && okF) {
      sumP[k] += p;
      nP[k] += 1;
      nFilas += 1;
      suma += p;
    }
  }

  const ids = [];
  for (let k = 0; k < npts; k++) if (nP[k] > 0) ids.push(k);
  const medias = ids.map((k) => sumP[k] / nP[k]);

  const franja = descFranja(hSel, tSel);
  const ambito = cSel !== '' ? 'Comuna ' + cSel : 'toda la ciudad';
  conteo.textContent = 'Mostrando ' + fmt(nFilas) + ' de ' + fmt(P.prob.length) +
    ' registros · ' + fmt(ids.length) + ' puntos en el mapa';

  // ---- Tarjetas ----
  let kMax = -1;
  let vMax = -1;
  medias.forEach((m, j) => { if (m > vMax) { vMax = m; kMax = ids[j]; } });
  let hPico = null;
  let vPico = -1;
  for (let h = 0; h < 24; h++) {
    if (curvaN[h]) {
      const m = curvaS[h] / curvaN[h];
      if (m > vPico) { vPico = m; hPico = h; }
    }
  }
  let cPico = null;
  let vC = -1;
  comS.forEach((s, c) => {
    if (c === 'Sin dato') return;
    const m = s / comN.get(c);
    if (m > vC) { vC = m; cPico = c; }
  });

  $('c-prom').textContent = nFilas ? pct(suma / nFilas) : '–';
  $('c-prom-s').textContent = franja + ' · ' + ambito;
  $('c-max').textContent = kMax >= 0 ? pct(vMax) : '–';
  $('c-max-s').textContent = kMax >= 0 ? 'Punto en comuna ' + P.pcom[kMax] : '';
  $('c-hora').textContent = hPico !== null ? hPico + ' h' : '–';
  $('c-hora-s').textContent = hPico !== null
    ? 'Riesgo medio ' + pct(vPico) + ' · ' + ambito : '';
  $('c-comuna').textContent = cPico !== null ? 'Comuna ' + cPico : '–';
  $('c-comuna-s').textContent = cPico !== null
    ? 'Riesgo medio ' + pct(vC) + ' · ' + franja : '';

  // ---- Mapa ----
  const trazas = [];
  const cTrace = trazaContorno();
  if (cTrace) trazas.push(cTrace);

  trazas.push({
    type: 'scatter', mode: 'markers', showlegend: false,
    x: ids.map((k) => P.plon[k]),
    y: ids.map((k) => P.plat[k]),
    marker: {
      symbol: 'square', size: Number(rngTam.value), opacity: 0.78,
      color: medias, colorscale: 'YlOrRd', reversescale: true,
      cmin: PMIN, cmax: PMAX, showscale: true,
      colorbar: {title: {text: 'Riesgo'}, tickformat: '.0%'},
    },
    customdata: ids.map((k, j) => [
      P.pcom[k],
      nP[k],
      P.pdist[k] !== null ? Number(P.pdist[k]).toFixed(1) + ' m' : 'Sin dato',
      pct(medias[j]),
    ]),
    hovertemplate:
      '<b>Riesgo: %{customdata[3]}</b><br>' +
      'Comuna: %{customdata[0]}<br>' +
      'Franjas promediadas: %{customdata[1]}<br>' +
      'Distancia a luminaria: %{customdata[2]}<extra></extra>',
  });

  Plotly.react('graf-heatmap', trazas, layoutMapa(
    'Riesgo de hurto · ' + franja + (cSel !== '' ? ' · Comuna ' + cSel : '')
  ), CFG_MAPA);

  // ---- Curva por hora ----
  const lista = Array.from(comS.keys()).filter((c) => c !== 'Sin dato').sort(
    (a, b) => comS.get(b) / comN.get(b) - comS.get(a) / comN.get(a)
  );
  const vals = lista.map((c) => comS.get(c) / comN.get(c));
  const altoG = Math.max(360, 26 * lista.length + 90);

  const horasX = Array.from({length: 24}, (_, h) => h);
  const yCurva = horasX.map((h) => (curvaN[h] ? curvaS[h] / curvaN[h] : null));
  const trC = [{
    type: 'scatter', mode: 'lines+markers', x: horasX, y: yCurva,
    line: {color: '#636efa', width: 3}, marker: {size: 6},
    hovertemplate: '%{x} h: %{y:.1%}<extra></extra>', showlegend: false,
  }];
  if (hSel !== '' && yCurva[Number(hSel)] !== null) {
    trC.push({
      type: 'scatter', mode: 'markers', x: [Number(hSel)],
      y: [yCurva[Number(hSel)]],
      marker: {size: 14, color: '#EF553B', line: {color: '#ffffff', width: 2}},
      hoverinfo: 'skip', showlegend: false,
    });
  }
  Plotly.react('graf-curva', trC, {
    title: {text: 'Riesgo medio por hora · ' + ambito},
    xaxis: {title: {text: 'Hora del día'}, dtick: 2, range: [-0.5, 23.5]},
    yaxis: {title: {text: 'Riesgo medio'}, tickformat: '.0%'},
    height: altoG, margin: {t: 50, r: 20, b: 50, l: 65},
  }, CFG_GRAF);

  // ---- Ranking de comunas ----
  const maxV = vals.length ? Math.max(...vals) : 1;
  Plotly.react('graf-comunas', [{
    type: 'bar', orientation: 'h',
    x: vals, y: lista.map((c) => 'Comuna ' + c),
    marker: {color: lista.map((c) => (c === cSel ? '#EF553B' : '#636efa'))},
    text: vals.map((v) => pct(v)), textposition: 'outside', cliponaxis: false,
    hovertemplate: '%{y}: %{x:.1%}<extra></extra>',
  }], {
    title: {text: 'Comunas por riesgo medio · ' + franja},
    height: altoG, margin: {t: 50, r: 60, b: 40, l: 20},
    xaxis: {tickformat: '.0%', range: [0, maxV * 1.2]},
    yaxis: {type: 'category', autorange: 'reversed', automargin: true},
    showlegend: false,
  }, {responsive: true, displaylogo: false, displayModeBar: false});
}

initFiltrosPred();
renderPred();
"""


def armar_html(titulo, actualizado, css, app_js, hay_satelite):
    t = escape(titulo)
    h = '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
    h += '<meta name="viewport" content="width=device-width, initial-scale=1">'
    h += f'<title>{t}</title><style>{css}</style></head><body>'
    h += '<div class="wrap">'

    h += '<header class="topbar">'
    h += f'<h1>{t}</h1>'
    h += '</header>'
    h += f'<p class="sub">Datos actualizados el {escape(actualizado)} (hora de Argentina)</p>'

    # ---------------- Vista prediccion ----------------
    h += '<section id="vista-prediccion">'
    h += '<div class="controles">'
    h += (
        '<div class="ctl"><label for="filtro-hora">Franja horaria</label>'
        '<select id="filtro-hora"></select></div>'
    )
    h += (
        '<div class="ctl"><label for="filtro-turno">Turno</label>'
        '<select id="filtro-turno">'
        '<option value="">Todo el día</option>'
        '<option value="noche">Noche (20–6 h)</option>'
        '<option value="dia">Día (7–19 h)</option>'
        '</select></div>'
    )
    h += (
        '<div class="ctl"><label for="filtro-comuna">Comuna</label>'
        '<select id="filtro-comuna"></select></div>'
    )
    h += (
        '<div class="ctl"><label for="tam-punto">Tamaño de los puntos</label>'
        '<input type="range" id="tam-punto" min="6" max="26" value="12"></div>'
    )
    h += '<button type="button" id="btn-play" class="btn btn-sec">▶ Animar horas</button>'
    h += '</div>'
    h += '<p class="estado" id="conteo-pred"></p>'
    h += (
        '<p class="desc oculto" id="sin-pred">No se recibieron datos de '
        'predicción. Revisá el input del actor (dataset_id).</p>'
    )

    h += '<div class="cards">'
    for cid, titulo_c in (
        ('c-prom', 'Riesgo promedio'),
        ('c-max', 'Riesgo máximo'),
        ('c-hora', 'Hora de mayor riesgo'),
        ('c-comuna', 'Comuna de mayor riesgo'),
    ):
        h += (
            f'<div class="card"><div class="t">{titulo_c}</div>'
            f'<div class="v" id="{cid}">–</div>'
            f'<div class="s" id="{cid}-s"></div></div>'
        )
    h += '</div>'

    h += '<div id="graf-heatmap" class="graf"></div>'
    h += '<div class="grid2">'
    h += '<div id="graf-curva" class="graf"></div>'
    h += '<div id="graf-comunas" class="graf"></div>'
    h += '</div>'
    h += (
        '<details class="nota-box"><summary>Cómo leer estos gráficos</summary>'
        '<p>Cada cuadrado es un punto de la ciudad y su color indica el riesgo '
        'relativo de hurto que estima el modelo para la franja horaria y la '
        'comuna elegidas (más rojo, mayor riesgo). Con Todas las franjas se '
        'promedian las 24 horas. Es el puntaje de un modelo entrenado con '
        'delitos históricos: sirve para comparar zonas y horarios, pero no es '
        'la probabilidad real de que ocurra un hecho.</p></details>'
    )
    h += '</section>'

    if hay_satelite:
        h += (
            '<p class="nota">Imagen satelital: Esri, Maxar, Earthstar '
            'Geographics y comunidad de usuarios de GIS.</p>'
        )
    h += (
        '<p class="nota">Las probabilidades provienen de un modelo estadístico '
        'y son orientativas.</p>'
    )
    h += '</div>'
    h += '<script>' + get_plotlyjs() + '</script>'
    h += '<script>' + app_js + '</script>'
    h += '</body></html>'
    return h


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}

        titulo = inp.get('titulo') or 'Predicción de Hurto - CABA'
        contorno_url = (inp.get('contorno_url') or '').strip()

        datos_pred = None
        try:
            df_pred = await obtener_df_predicciones(inp)
            datos_pred = construir_predicciones(df_pred)
            if datos_pred is None:
                Actor.log.warning(
                    'No llegaron predicciones: revisa dataset_id, '
                    'predicciones, csv_predicciones_texto o '
                    'csv_predicciones_url en el input.'
                )
            else:
                Actor.log.info(
                    f'Predicciones cargadas: {len(datos_pred["prob"])} filas, '
                    f'{len(datos_pred["plat"])} puntos.'
                )
        except Exception as e:
            Actor.log.warning(
                f'No se pudo cargar predicciones: {e}. Si es un error de '
                'permisos, activa "Full permissions" en la configuracion '
                'del actor.'
            )

        try:
            img = await asyncio.to_thread(descargar_satelite)
        except Exception as e:
            img = None
            Actor.log.warning(f'No se pudo descargar el satelite: {e}')

        contorno = None
        if contorno_url:
            try:
                contorno = cargar_contorno_desde_url(contorno_url)
            except Exception as e:
                Actor.log.warning(f'No se pudo cargar contorno: {e}')

        cfg = {
            'lonMin': LON_MIN, 'lonMax': LON_MAX,
            'latMin': LAT_MIN, 'latMax': LAT_MAX,
        }

        app = (
            APP_JS
            .replace('__CFG__', a_js(cfg))
            .replace('__PRED__', a_js(datos_pred))
            .replace('__CONTORNO__', a_js(contorno))
            .replace('__IMG__', a_js(img))
        )

        actualizado = datetime.now(TZ_AR).strftime('%d/%m/%Y %H:%M')
        html = armar_html(titulo, actualizado, CSS, app, bool(img))

        # Store con nombre: el link publico es siempre el mismo
        kvs = await Actor.open_key_value_store(name=NOMBRE_STORE)
        await kvs.set_value(
            'dashboard.html', html, content_type='text/html; charset=utf-8'
        )

        store_id = getattr(kvs, 'id', None)
        if not isinstance(store_id, str) or not store_id:
            store_id = STORE_ID_FALLBACK
        Actor.log.info(
            'Dashboard listo: https://api.apify.com/v2/key-value-stores/'
            f'{store_id}/records/dashboard.html'
        )
