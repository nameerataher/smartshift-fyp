// Shared configuration and helpers for the Dubai LoD1 viewer.
// Municipality footprints with OSM/Landmark/GHSL heights
export const GEOJSON_URL = '../data/final/dubai_municipality_buildings.geojson';

// Approx Dubai city bounds (keeps initial view sensible but doesn't restrict navigation)
export const bboxDubaiCity = [54.8, 24.8, 55.6, 25.6]; // west, south, east, north

// Start over Downtown Dubai / Business Bay where the tall buildings are
export const downtownCenter = [55.275, 25.195]; // Near Burj Khalifa in municipality data

export const SHADOW_ZOOM_MIN = 14;

// Optional LOD2+ model overlay (glTF/GLB). Set URL and anchor to enable.
// Example: export const LOD2_MODEL_URL = '../data/dso.glb';
// Set to null to disable the LOD2 overlay.
export const LOD2_MODEL_URL = null;
export const LOD2_MODEL_ANCHOR = [55.384, 25.118]; // Dubai Silicon Oasis (lon, lat)
export const LOD2_MODEL_ALT_M = 0; // altitude in meters
export const LOD2_MODEL_SCALE = 1; // multiplier in meters (1 = real scale)
// glTF is Y-up; MapLibre custom layer uses Z-up, so rotate 90° on X by default.
export const LOD2_MODEL_ROTATION_DEG = [90, 0, 0];
// Recenter model around its bounding box (helps if origin is far away).
export const LOD2_MODEL_RECENTER = true;
// Optional model offset in meters: +X east, +Y north, +Z up.
export const LOD2_MODEL_OFFSET_M = [345, -590, 0];

export const osmStyle = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors'
    }
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }]
};

export function baseHeightExpr() {
  // Simple: just use height property (all heights from GHSL)
  return ['coalesce', ['to-number', ['get', 'height']], 5];
}

export function getHeightMeters(props) {
  const h = Number(props?.height);
  return Number.isFinite(h) && h > 0 ? h : 5;
}
