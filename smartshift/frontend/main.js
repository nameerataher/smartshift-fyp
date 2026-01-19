import maplibregl from 'https://cdn.jsdelivr.net/npm/maplibre-gl@3.6.2/+esm';
import {
  GEOJSON_URL,
  bboxDubaiCity,
  downtownCenter,
  SHADOW_ZOOM_MIN,
  osmStyle,
  baseHeightExpr,
  getHeightMeters,
  LOD2_MODEL_URL,
  LOD2_MODEL_ANCHOR,
  LOD2_MODEL_ALT_M,
  LOD2_MODEL_SCALE,
  LOD2_MODEL_ROTATION_DEG,
  LOD2_MODEL_RECENTER,
  LOD2_MODEL_OFFSET_M
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
const lod2OffsetXEl = document.getElementById('lod2OffsetX');
const lod2OffsetYEl = document.getElementById('lod2OffsetY');
const lod2OffsetZEl = document.getElementById('lod2OffsetZ');
const applyLod2OffsetBtn = document.getElementById('applyLod2Offset');

const LOD2_OFFSET_STORAGE_KEY = 'smartshift:lod2Offset';
const lod2Offset = Array.isArray(LOD2_MODEL_OFFSET_M) ? [...LOD2_MODEL_OFFSET_M] : [0, 0, 0];
let lod2ShadowData = null;
let shadowSystem = null;

function loadStoredLod2Offset() {
  try {
    const raw = localStorage.getItem(LOD2_OFFSET_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length >= 3) {
      lod2Offset[0] = Number(parsed[0]) || 0;
      lod2Offset[1] = Number(parsed[1]) || 0;
      lod2Offset[2] = Number(parsed[2]) || 0;
    }
  } catch (err) {
    console.warn('Failed to load LOD2 offset from storage', err);
  }
}

function persistLod2Offset() {
  try {
    localStorage.setItem(LOD2_OFFSET_STORAGE_KEY, JSON.stringify(lod2Offset));
  } catch (err) {
    console.warn('Failed to persist LOD2 offset', err);
  }
}

function syncLod2OffsetInputs() {
  if (!lod2OffsetXEl || !lod2OffsetYEl || !lod2OffsetZEl) return;
  lod2OffsetXEl.value = String(lod2Offset[0]);
  lod2OffsetYEl.value = String(lod2Offset[1]);
  lod2OffsetZEl.value = String(lod2Offset[2]);
}

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

function addLod2Overlay(map) {
  if (!LOD2_MODEL_URL) {
    return;
  }

  const modelOrigin = LOD2_MODEL_ANCHOR;
  const modelAltitude = Number(LOD2_MODEL_ALT_M || 0);
  const modelRotate = (LOD2_MODEL_ROTATION_DEG || [0, 0, 0]).map((d) => (d * Math.PI) / 180);

  Promise.all([
    import('./vendor/three/three.module.js'),
    import('./vendor/three/GLTFLoader.js')
  ])
    .then(([THREE, loaderMod]) => {
      const { GLTFLoader } = loaderMod;
      const modelAsMercator = maplibregl.MercatorCoordinate.fromLngLat(modelOrigin, modelAltitude);
      const modelScale = modelAsMercator.meterInMercatorCoordinateUnits() * (Number(LOD2_MODEL_SCALE) || 1);
      const rotationX = new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(1, 0, 0), modelRotate[0]);
      const rotationY = new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(0, 1, 0), modelRotate[1]);
      const rotationZ = new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(0, 0, 1), modelRotate[2]);
      const rotationMatrix = new THREE.Matrix4().multiply(rotationX).multiply(rotationY).multiply(rotationZ);
      const customLayer = {
        id: 'lod2-overlay',
        type: 'custom',
        renderingMode: '3d',
        onAdd(mapInstance, gl) {
          this.camera = new THREE.Camera();
          this.scene = new THREE.Scene();

          const directional = new THREE.DirectionalLight(0xffffff, 0.9);
          directional.position.set(0, -70, 100).normalize();
          this.scene.add(directional);

          const ambient = new THREE.AmbientLight(0xffffff, 0.5);
          this.scene.add(ambient);

          this.renderer = new THREE.WebGLRenderer({
            canvas: mapInstance.getCanvas(),
            context: gl,
            antialias: true
          });
          this.renderer.autoClear = false;

          const loader = new GLTFLoader();
          loader.load(
            LOD2_MODEL_URL,
            (gltf) => {
              this.model = gltf.scene;
              // Recentering helps if the model origin is far from its geometry.
              if (LOD2_MODEL_RECENTER) {
                const box = new THREE.Box3().setFromObject(this.model);
                const center = box.getCenter(new THREE.Vector3());
                this.model.position.sub(center);
                const size = box.getSize(new THREE.Vector3());
                setStatus(
                  `LOD2 model loaded (size ~${size.x.toFixed(1)}×${size.y.toFixed(1)}×${size.z.toFixed(1)} m).`
                );
              } else {
                setStatus('LOD2 model loaded.');
              }
              this.scene.add(this.model);
              try {
                this.model.updateWorldMatrix(true, true);
                const triangles = [];
                this.model.traverse((obj) => {
                  if (!obj.isMesh || !obj.geometry?.attributes?.position) return;
                  const geom = obj.geometry;
                  const pos = geom.attributes.position;
                  const index = geom.index;
                  const world = obj.matrixWorld;
                  const v = new THREE.Vector3();
                  const pushTri = (ia, ib, ic) => {
                    const coords = new Float32Array(9);
                    v.fromBufferAttribute(pos, ia).applyMatrix4(world).applyMatrix4(rotationMatrix);
                    coords[0] = v.x; coords[1] = v.y; coords[2] = v.z;
                    v.fromBufferAttribute(pos, ib).applyMatrix4(world).applyMatrix4(rotationMatrix);
                    coords[3] = v.x; coords[4] = v.y; coords[5] = v.z;
                    v.fromBufferAttribute(pos, ic).applyMatrix4(world).applyMatrix4(rotationMatrix);
                    coords[6] = v.x; coords[7] = v.y; coords[8] = v.z;
                    triangles.push(coords);
                  };
                  if (index) {
                    for (let i = 0; i < index.count; i += 3) {
                      pushTri(index.getX(i), index.getX(i + 1), index.getX(i + 2));
                    }
                  } else {
                    for (let i = 0; i < pos.count; i += 3) {
                      pushTri(i, i + 1, i + 2);
                    }
                  }
                });
                lod2ShadowData = {
                  triangles,
                  originMercator: modelAsMercator,
                  meterToMercator: modelScale,
                  getOffsetMeters: () => [...lod2Offset]
                };
                if (shadowSystem?.setLod2ShadowSource) {
                  shadowSystem.setLod2ShadowSource(() => lod2ShadowData);
                }
              } catch (err) {
                console.error('Failed to build LOD2 shadow triangles', err);
              }
              mapInstance.triggerRepaint();
            },
            undefined,
            (err) => {
              console.error('LOD2 model load failed', err);
              setStatus('Failed to load LOD2 model.');
            }
          );
        },
        render(gl, matrix) {
          if (!this.model) return;
          const offsetMercator = {
            x: (Number(lod2Offset[0]) || 0) * modelScale,
            y: (Number(lod2Offset[1]) || 0) * modelScale,
            z: (Number(lod2Offset[2]) || 0) * modelScale
          };
          const m = new THREE.Matrix4().fromArray(matrix);
          const l = new THREE.Matrix4()
            .makeTranslation(
              modelAsMercator.x + offsetMercator.x,
              modelAsMercator.y + offsetMercator.y,
              modelAsMercator.z + offsetMercator.z
            )
            .scale(new THREE.Vector3(modelScale, -modelScale, modelScale))
            .multiply(rotationX)
            .multiply(rotationY)
            .multiply(rotationZ);

          this.camera.projectionMatrix = m.multiply(l);
          this.renderer.resetState();
          this.renderer.render(this.scene, this.camera);
          map.triggerRepaint();
        }
      };

      if (!map.getLayer(customLayer.id)) {
        map.addLayer(customLayer);
      }
    })
    .catch((err) => {
      console.error('Failed to load Three.js modules', err);
      setStatus('LOD2 overlay disabled (Three.js failed to load).');
    });
}

const initialCenter = LOD2_MODEL_URL ? LOD2_MODEL_ANCHOR : downtownCenter;
const initialZoom = LOD2_MODEL_URL ? 16 : 16;

// Map setup
const map = new maplibregl.Map({
  container: 'map',
  style: osmStyle,
  center: initialCenter,
  zoom: initialZoom,
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
  map.easeTo({ center: initialCenter, zoom: initialZoom, pitch: 60, bearing: 0, duration: 800 });
});

scaleEl.addEventListener('change', () => setHeightScale(map));
loadStoredLod2Offset();
syncLod2OffsetInputs();

applyLod2OffsetBtn?.addEventListener('click', () => {
  lod2Offset[0] = Number(lod2OffsetXEl?.value) || 0;
  lod2Offset[1] = Number(lod2OffsetYEl?.value) || 0;
  lod2Offset[2] = Number(lod2OffsetZEl?.value) || 0;
  persistLod2Offset();
  setStatus(`LOD2 offset set to E ${lod2Offset[0]}m, N ${lod2Offset[1]}m, U ${lod2Offset[2]}m.`);
  map.triggerRepaint();
});

[lod2OffsetXEl, lod2OffsetYEl, lod2OffsetZEl].forEach((el) => {
  el?.addEventListener('change', () => applyLod2OffsetBtn?.click());
});

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

  addLod2Overlay(map);

  // Sun + shadow subsystem
  shadowSystem = setupSunShadowSystem({
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
  if (lod2ShadowData && shadowSystem.setLod2ShadowSource) {
    shadowSystem.setLod2ShadowSource(() => lod2ShadowData);
  }

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

