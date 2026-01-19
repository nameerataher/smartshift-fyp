import SunCalc from 'https://cdn.jsdelivr.net/npm/suncalc@1.9.0/+esm';
import polygonClipping from 'https://cdn.jsdelivr.net/npm/polygon-clipping@0.15.3/+esm';

// Utility projections for shadow geometry
function toWebMercator([lon, lat]) {
  const rMajor = 6378137.0;
  const x = rMajor * lon * Math.PI / 180.0;
  const y = rMajor * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI / 180.0) / 2));
  return [x, y];
}

function fromWebMercator([x, y]) {
  const rMajor = 6378137.0;
  const lon = (x / rMajor) * 180.0 / Math.PI;
  const lat = (2 * Math.atan(Math.exp(y / rMajor)) - Math.PI / 2) * 180.0 / Math.PI;
  return [lon, lat];
}

export function setupSunShadowSystem(options) {
  const {
    map,
    ui,
    setStatus,
    SHADOW_ZOOM_MIN,
    getHeightMeters
  } = options;

  const {
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
  } = ui;

  const SHADOW_SOURCE_ID = 'shadow';
  const SHADOW_LAYER_ID = 'shadow-layer';

  let autoTimer = null;
  let scrubTimer = null;
  let shadowJobToken = 0;
  const shadowCache = new Map();
  let currentSunKey = null;

  function setDefaultSunInputs() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    if (!sunDateEl.value) sunDateEl.value = `${y}-${m}-${d}`;
    if (!sunTimeEl.value) sunTimeEl.value = `${hh}:${mm}`;
    syncSliderToTime();
  }

  function syncSliderToTime() {
    if (!sunTimeEl.value) return;
    const [hh, mm] = sunTimeEl.value.split(':').map((v) => Number(v) || 0);
    const mins = Math.max(0, Math.min(1439, hh * 60 + mm));
    timeSliderEl.value = String(mins);
    timeLabelEl.textContent = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  }

  function setTimeFromSlider() {
    const mins = Number(timeSliderEl.value || 0);
    const hh = Math.floor(mins / 60);
    const mm = mins % 60;
    const hhStr = String(hh).padStart(2, '0');
    const mmStr = String(mm).padStart(2, '0');
    sunTimeEl.value = `${hhStr}:${mmStr}`;
    timeLabelEl.textContent = `${hhStr}:${mmStr}`;
  }

  function getSunForCenter() {
    const [lon, lat] = map.getCenter().toArray();
    const dateStr = sunDateEl.value;
    const timeStr = sunTimeEl.value;
    if (!dateStr || !timeStr) return null;
    const dt = new Date(`${dateStr}T${timeStr}:00`);
    const pos = SunCalc.getPosition(dt, lat, lon);
    return {
      altitude: pos.altitude * 180 / Math.PI,
      azimuth: (pos.azimuth * 180 / Math.PI) + 180
    };
  }

  function scheduleAuto() {
    if (!autoShadowsEl.checked) return;
    if (autoTimer) clearTimeout(autoTimer);
    autoTimer = setTimeout(() => {
      computeVisibleShadows();
    }, 150);
  }

  // Debounced scrub shadow updates for smooth slider playback.
  function scheduleScrubShadows() {
    if (scrubTimer) clearTimeout(scrubTimer);
    if (!fastShadowsEl.checked) fastShadowsEl.checked = true;
    scrubTimer = setTimeout(() => {
      computeVisibleShadows();
    }, 120);
  }

  function setStatusAndSun(sun) {
    setStatus(`Sun set. Alt ${sun.altitude.toFixed(1)}°, Az ${sun.azimuth.toFixed(1)}°`);
  }

  function updateShadowSource(features, fade = true) {
    const src = map.getSource(SHADOW_SOURCE_ID);
    if (!src || !src.setData) return;
    if (fade) map.setPaintProperty(SHADOW_LAYER_ID, 'fill-opacity', 0.0);
    src.setData({ type: 'FeatureCollection', features });
    if (fade) {
      setTimeout(() => {
        map.setPaintProperty(SHADOW_LAYER_ID, 'fill-opacity', 0.55);
      }, 40);
    }
  }

  function clearShadows(reason) {
    updateShadowSource([], false);
    if (reason) setStatus(reason);
  }

  function computeShadowPolygon(geom, heightM, sunAzimuthDeg, sunAltDeg, useFast) {
    if (!geom || sunAltDeg <= 0) return null;
    const length = heightM / Math.tan((sunAltDeg * Math.PI) / 180);
    if (!Number.isFinite(length) || length <= 0) return null;
    const az = (sunAzimuthDeg + 180) * Math.PI / 180;
    const dx = Math.sin(az) * length;
    const dy = Math.cos(az) * length;
    const closeRing = (ring) => {
      if (!ring.length) return ring;
      const first = ring[0];
      const last = ring[ring.length - 1];
      if (first[0] !== last[0] || first[1] !== last[1]) {
        return [...ring, first];
      }
      return ring;
    };
    const toWM = (ring) => ring.map((pt) => toWebMercator(pt));
    const fromWM = (ring) => ring.map((pt) => fromWebMercator(pt));
    const shiftWM = (ring) => ring.map(([x, y]) => [x + dx, y + dy]);
    const unionAll = (polys) => {
      if (!polys.length) return null;
      let acc = polys[0];
      for (let i = 1; i < polys.length; i += 1) {
        acc = polygonClipping.union(acc, polys[i]);
      }
      return acc;
    };
    const simplifyRing = (ring) => {
      const n = ring.length;
      if (n <= 120) return ring;
      const step = n > 400 ? 4 : 2;
      const out = [];
      for (let i = 0; i < n; i += step) out.push(ring[i]);
      if (out[out.length - 1] !== ring[n - 1]) out.push(ring[n - 1]);
      return out;
    };
    const buildShadowWM = (outer) => {
      const base = closeRing(simplifyRing(outer));
      const baseWM = closeRing(toWM(base));
      const shiftedWM = closeRing(shiftWM(baseWM));
      const pieces = [
        [baseWM],
        [shiftedWM]
      ];
      for (let i = 0; i < baseWM.length - 1; i += 1) {
        const a = baseWM[i];
        const b = baseWM[i + 1];
        const a2 = shiftedWM[i];
        const b2 = shiftedWM[i + 1];
        const quad = [a, b, b2, a2, a];
        pieces.push([quad]);
      }
      return unionAll(pieces);
    };
    const buildShadowWMFast = (outer) => {
      const base = closeRing(simplifyRing(outer));
      const baseWM = closeRing(toWM(base));
      const shiftedWM = closeRing(shiftWM(baseWM));
      const pieces = [
        [baseWM],
        [shiftedWM]
      ];
      for (let i = 0; i < baseWM.length - 1; i += 1) {
        const a = baseWM[i];
        const b = baseWM[i + 1];
        const a2 = shiftedWM[i];
        const b2 = shiftedWM[i + 1];
        const quad = [a, b, b2, a2, a];
        pieces.push([quad]);
      }
      return pieces;
    };
    const wmToLonLat = (mp) => mp.map((poly) => poly.map((ring) => fromWM(ring)));
    if (geom.type === 'Polygon') {
      const outer = geom.coordinates[0];
      const shadowWM = useFast ? buildShadowWMFast(outer) : buildShadowWM(outer);
      if (!shadowWM) return null;
      const shadowLL = wmToLonLat(shadowWM);
      return useFast || shadowLL.length > 1
        ? { type: 'MultiPolygon', coordinates: shadowLL }
        : { type: 'Polygon', coordinates: shadowLL[0] };
    }
    if (geom.type === 'MultiPolygon') {
      const parts = [];
      geom.coordinates.forEach((poly) => {
        const outer = poly[0];
        const shadowWM = useFast ? buildShadowWMFast(outer) : buildShadowWM(outer);
        if (shadowWM) parts.push(shadowWM);
      });
      if (!parts.length) return null;
      if (useFast) {
        const flattened = parts.flat();
        const shadowLL = wmToLonLat(flattened);
        return { type: 'MultiPolygon', coordinates: shadowLL };
      }
      const merged = unionAll(parts);
      if (!merged) return null;
      const shadowLL = wmToLonLat(merged);
      return shadowLL.length === 1
        ? { type: 'Polygon', coordinates: shadowLL[0] }
        : { type: 'MultiPolygon', coordinates: shadowLL };
    }
    return null;
  }

  function getFeatureKey(feature) {
    if (feature.id != null) return `id:${feature.id}`;
    const pid = feature.properties?.id ?? feature.properties?.osm_id ?? null;
    if (pid != null) return `pid:${pid}`;
    return `geom:${JSON.stringify(feature.geometry?.bbox ?? feature.geometry?.coordinates?.[0]?.[0] ?? '')}`;
  }

  function sunKey(sun, scale) {
    const a = Math.round(sun.altitude * 10) / 10;
    const z = Math.round(sun.azimuth * 10) / 10;
    return `${a}|${z}|${scale}|${fastShadowsEl.checked ? 'fast' : 'union'}`;
  }

  async function computeVisibleShadows() {
    const myToken = ++shadowJobToken;
    if (map.getZoom() < SHADOW_ZOOM_MIN) {
      clearShadows(`Zoom in to ${SHADOW_ZOOM_MIN}+ to show shadows.`);
      return;
    }
    const sun = getSunForCenter();
    if (!sun) {
      setStatus('Set a date/time to compute sun position.');
      return;
    }
    const scale = Math.max(1, Math.min(50, Number(scaleEl.value || 1)));
    const key = sunKey(sun, scale);
    if (key !== currentSunKey) {
      shadowCache.clear();
      currentSunKey = key;
    }
    const rawMax = Number(shadowMaxEl.value || 0);
    const maxCount = rawMax <= 0 ? Infinity : Math.max(10, Math.min(5000, rawMax));
    const layers = map.getZoom() >= 13 ? ['dubai-lod1'] : ['dubai-footprints'];
    const raw = map.queryRenderedFeatures({ layers });
    if (!raw.length) {
      if (!map.isSourceLoaded('dubai')) {
        setStatus('Buildings are still loading. Please wait a moment.');
      } else {
        setStatus('No buildings visible here. Try zooming in or moving to Dubai.');
      }
      return;
    }
    const seen = new Set();
    const features = [];
    for (const f of raw) {
      const keyF = getFeatureKey(f);
      if (seen.has(keyF)) continue;
      seen.add(keyF);
      features.push(f);
      if (features.length >= maxCount) break;
    }
    const shadows = [];
    const batchSize = 150;
    for (let i = 0; i < features.length; i += batchSize) {
      if (myToken !== shadowJobToken) return;
      const slice = features.slice(i, i + batchSize);
      for (const f of slice) {
        const cacheKey = `${getFeatureKey(f)}|${key}`;
        let geom = shadowCache.get(cacheKey);
        if (!geom) {
          const heightM = getHeightMeters(f.properties) * scale;
          geom = computeShadowPolygon(f.geometry, heightM, sun.azimuth, sun.altitude, fastShadowsEl.checked);
          if (geom) shadowCache.set(cacheKey, geom);
        }
        if (!geom) continue;
        shadows.push({ type: 'Feature', properties: {}, geometry: geom });
      }
      setStatus(`Rendering shadows: ${Math.min(i + batchSize, features.length)}/${features.length}…`);
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    updateShadowSource(shadows, true);
    const maxLabel = Number.isFinite(maxCount) && maxCount !== Infinity ? ` (max ${maxCount})` : '';
    setStatus(`Shadows rendered: ${shadows.length}/${features.length} visible buildings${maxLabel}.`);
  }

  function wireEvents() {
    applySunBtn.addEventListener('click', () => {
      const sun = getSunForCenter();
      if (!sun) {
        setStatus('Set a date/time to compute sun position.');
        return;
      }
      setStatusAndSun(sun);
      if (autoShadowsEl.checked) {
        computeVisibleShadows();
      }
    });

    timeSliderEl.addEventListener('input', () => {
      setTimeFromSlider();
      scheduleScrubShadows();
    });

    sunTimeEl.addEventListener('change', () => {
      syncSliderToTime();
    });

    fastShadowsEl.addEventListener('change', () => {
      shadowCache.clear();
      currentSunKey = null;
      scheduleAuto();
    });

    if (computeShadowsBtn) {
      computeShadowsBtn.addEventListener('click', () => {
        computeVisibleShadows();
      });
    }

    map.on('click', 'dubai-lod1', (e) => {
      if (!shadowToggleEl.checked) return;
      const feature = e.features?.[0];
      if (!feature) return;
      const sun = getSunForCenter();
      if (!sun) {
        setStatus('Set a date/time to compute sun position.');
        return;
      }
      const heightM = getHeightMeters(feature.properties);
      const scale = Math.max(1, Math.min(50, Number(scaleEl.value || 1)));
      let shadowGeom = null;
      try {
        shadowGeom = computeShadowPolygon(feature.geometry, heightM * scale, sun.azimuth, sun.altitude, fastShadowsEl.checked);
      } catch (err) {
        console.error(err);
        setStatus('Shadow error: failed to compute geometry.');
        return;
      }
      if (!shadowGeom) {
        setStatus('No shadow (sun below horizon or invalid geometry).');
        return;
      }
      const shadowFeature = {
        type: 'Feature',
        properties: { height: heightM },
        geometry: shadowGeom
      };
      updateShadowSource([shadowFeature], true);
      setStatus(`Shadow drawn. Height ${heightM.toFixed(1)} m.`);
    });

    map.on('moveend', scheduleAuto);
    map.on('zoomend', () => {
      if (map.getZoom() < SHADOW_ZOOM_MIN) {
        clearShadows(`Zoom in to ${SHADOW_ZOOM_MIN}+ to show shadows.`);
      } else {
        scheduleAuto();
      }
    });
    map.on('rotateend', scheduleAuto);
    map.on('pitchend', scheduleAuto);
  }

  function addShadowLayer() {
    map.addSource(SHADOW_SOURCE_ID, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });
    map.addLayer({
      id: SHADOW_LAYER_ID,
      type: 'fill',
      source: SHADOW_SOURCE_ID,
      paint: {
        'fill-color': '#0f172a',
        'fill-opacity': 0.55,
        'fill-opacity-transition': { duration: 300, delay: 0 }
      }
    });
  }

  // Initialize: add shadow layer, wire UI + map events
  addShadowLayer();
  wireEvents();

  return {
    setDefaultSunInputs,
    syncSliderToTime,
    setTimeFromSlider,
    computeVisibleShadows,
    scheduleAuto,
    clearShadows
  };
}
