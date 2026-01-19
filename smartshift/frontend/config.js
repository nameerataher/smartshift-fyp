// Shared configuration and helpers for the Dubai LoD1 viewer.
export const GEOJSON_URL = '../data/gba_dubai/dubai_merged_height_override.geojson';

// Approx Dubai city bounds (keeps initial view sensible but doesn't restrict navigation)
export const bboxDubaiCity = [54.8, 24.8, 55.6, 25.6]; // west, south, east, north

// Start directly over Downtown Dubai so 3D extrusions are visible immediately.
export const downtownCenter = [55.2744, 25.1972]; // Burj Khalifa vicinity

export const SHADOW_ZOOM_MIN = 14;

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
  return [
    'coalesce',
    ['to-number', ['get', 'height_final']],
    ['to-number', ['get', 'height']],
    0
  ];
}

export function getHeightMeters(props) {
  const h = Number(props?.height_final ?? props?.height);
  return Number.isFinite(h) && h > 0 ? h : 20;
}
