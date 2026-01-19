import maplibregl from 'https://cdn.jsdelivr.net/npm/maplibre-gl@3.6.2/+esm';
import {
  GEOJSON_URL,
  bboxDubaiCity,
  downtownCenter,
  SHADOW_ZOOM_MIN,
  osmStyle,
  baseHeightExpr,
  getHeightMeters
} from './config.js';
import { setupSunShadowSystem } from './sunShadow.js';

const statusEl = document.getElementById('status');
const scaleEl = document.getElementById('scale');
const reloadBtn = document.getElementById('reload');
const sunDateEl = document.getElementById('sunDate');
const sunTimeEl = document.getElementById('sunTime');
const applySunBtn = document.getElementById('applySun');
const shadowToggleEl = document.getElementById('shadowToggle');
const computeShadowsBtn = document.getElementById('computeShadows');
const shadowMaxEl = document.getElementById('shadowMax');
const autoShadowsEl = document.getElementById('autoShadows');
const fastShadowsEl = document.getElementById('fastShadows');
const resetViewBtn = document.getElementById('resetView');
const timeSliderEl = document.getElementById('timeSlider');
const timeLabelEl = document.getElementById('timeLabel');

function setStatus(msg) {
  statusEl.textContent = msg;
}

function setHeightScale(map) {
  const scale = Math.max(1, Math.min(50, Number(scaleEl.value || 1)));
  if (map.getLayer('dubai-lod1')) {
    map.setPaintProperty('dubai-lod1', 'fill-extrusion-height', ['*', baseHeightExpr(), scale]);
  }
  setStatus(`Height scale set to ${scale}×`);
}

// Map setup
const map = new maplibregl.Map({
  container: 'map',
  style: osmStyle,
  center: downtownCenter,
  zoom: 16,
  minZoom: 9,
  maxZoom: 20,
  renderWorldCopies: false,
  pitch: 55,
  bearing: 0,
  antialias: true,
});

map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');

reloadBtn.addEventListener('click', () => {
  setStatus('Rendering is automatic. Zoom/pan/rotate and the extrusions will update.');
});

resetViewBtn.addEventListener('click', () => {
  map.easeTo({ center: downtownCenter, zoom: 16, pitch: 60, bearing: 0, duration: 800 });
});

scaleEl.addEventListener('change', () => setHeightScale(map));

map.on('load', () => {
  setStatus('Loading Dubai GeoJSON (this is large; first load may take time)…');

  map.addSource('dubai', {
    type: 'geojson',
    data: GEOJSON_URL,
  });

  map.addLayer({
    id: 'dubai-footprints',
    type: 'fill',
    source: 'dubai',
    paint: {
      'fill-color': [
        'match',
        ['get', 'height_src'],
        'osm_height', '#60a5fa',
        'osm_levels', '#34d399',
        '#fbbf24'
      ],
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0.10, 13, 0.25],
    },
  });

  map.addLayer({
    id: 'dubai-lod1',
    type: 'fill-extrusion',
    source: 'dubai',
    minzoom: 12,
    paint: {
      'fill-extrusion-color': [
        'match',
        ['get', 'height_src'],
        'osm_height', '#60a5fa',
        'osm_levels', '#34d399',
        '#fbbf24'
      ],
      'fill-extrusion-height': ['*', baseHeightExpr(), Math.max(1, Math.min(50, Number(scaleEl.value || 1)))],
      'fill-extrusion-base': 0,
      'fill-extrusion-opacity': 0.88,
    },
  });

  map.on('sourcedata', (e) => {
    if (e.sourceId !== 'dubai') return;
    if (e.isSourceLoaded) {
      const zoomHint = map.getZoom() < 13 ? ' Zoom in (13+) to see 3D.' : '';
      setStatus(`Dubai buildings loaded. Blue=OSM height, green=OSM levels, amber=computed.${zoomHint}`);
      setHeightScale(map);
    }
  });

  // Popups for building attributes (2D layer for easy hit-test)
  map.on('click', 'dubai-footprints', (e) => {
    const f0 = e.features?.[0];
    if (!f0) return;
    const p = f0.properties || {};
    const hFinal = p.height_final ?? '(missing)';
    const h = p.height ?? '(missing)';
    const src = p.height_src ?? '(missing)';
    const scale = Math.max(1, Math.min(50, Number(scaleEl.value || 1)));
    const used = Number.isFinite(Number(hFinal)) ? Number(hFinal) : (Number.isFinite(Number(h)) ? Number(h) : 0);
    const html = `
      <div style="font: 12px/1.2 system-ui; color: #0f172a;">
        <div><b>height_final</b>: ${hFinal}</div>
        <div><b>height</b>: ${h}</div>
        <div><b>height_src</b>: ${src}</div>
        <div><b>scale</b>: ${scale}×</div>
        <div><b>extrusion</b>: ${(used * scale).toFixed(2)} m</div>
      </div>
    `;
    new maplibregl.Popup({ closeOnClick: true })
      .setLngLat(e.lngLat)
      .setHTML(html)
      .addTo(map);
  });

  map.on('mouseenter', 'dubai-lod1', () => map.getCanvas().style.cursor = 'pointer');
  map.on('mouseleave', 'dubai-lod1', () => map.getCanvas().style.cursor = '');

  // Sun + shadow subsystem
  const shadowSystem = setupSunShadowSystem({
    map,
    ui: {
      sunDateEl,
      sunTimeEl,
      applySunBtn,
      shadowToggleEl,
      shadowMaxEl,
      autoShadowsEl,
      fastShadowsEl,
      scaleEl,
      timeSliderEl,
      timeLabelEl,
      computeShadowsBtn
    },
    setStatus,
    SHADOW_ZOOM_MIN,
    getHeightMeters
  });

  shadowSystem.setDefaultSunInputs();

  // Helpful note for reload button (no action needed)
  reloadBtn.addEventListener('click', () => {
    setStatus('Rendering is automatic. Zoom/pan/rotate and the extrusions will update.');
  });
});

map.on('error', (e) => {
  if (e?.error?.message && e.sourceId === 'dubai') {
    setStatus(`Failed to load buildings: ${e.error.message}`);
  }
});
