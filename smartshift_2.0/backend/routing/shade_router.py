import hashlib
import itertools
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx
import requests as http_req

from shadow_calculator import Building, ShadowCalculator
from shadow_scheduler import _haversine, _point_in_polygon, parse_client_buildings
from solar_position import SunPosition

MAPBOX_TOKEN = (
    "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9"
    ".WI13BJqDyOu6G38-YP6hog"
)

BUILDING_FETCH_RADIUS = 300
DEFAULT_BUILDING_HEIGHT = 30.0
ROAD_TILEQUERY_RADIUS = 350
ROAD_SAMPLE_SPACING = 150
GRAPH_SEGMENT_LENGTH = 5
NODE_MERGE_DIST = 8
SHADOW_SAMPLE_SPACING = 5
MAX_TILEQUERY_CALLS = 60
MAX_REASONABLE_DETOUR_FACTOR = 1.35
MAX_REASONABLE_EXTRA_METERS = 1200
ENDPOINT_CONNECT_RADIUS = 120

WALK_ALLOWED = {
    "primary", "secondary", "tertiary", "street", "street_limited",
    "service", "path", "pedestrian", "track", "residential",
    "living_street", "footway", "steps", "cycleway", "unclassified",
}
CYCLE_ALLOWED = WALK_ALLOWED | {
    "primary_link", "secondary_link", "tertiary_link",
}


class ShadeRouter:
    """Road-realistic shade-aware routing engine."""

    TZ = 4.0
    WALK_SPEED = 1.4
    RUN_SPEED = 2.6   # m/s; used for time-along-route when mode is "running"
    CYCLE_SPEED = 4.0

    def __init__(self, alpha: float = 2.0, segment_length: float = GRAPH_SEGMENT_LENGTH):
        self.alpha = alpha
        self.seg_len = segment_length
        self._sc = ShadowCalculator()
        self._bldg_cache: Dict[str, List[Building]] = {}
        self._road_cache: Dict[str, list] = {}

    # ── public ────────────────────────────────────────────────────────

    def find_routes(
        self,
        start_lat: float, start_lon: float,
        end_lat: float, end_lon: float,
        mode: str = "walking",
        departure_time: Optional[datetime] = None,
        alpha: Optional[float] = None,
        k: int = 3,
        client_buildings: Optional[List[Dict]] = None,
        date_str: Optional[str] = None,
        current_minutes: Optional[int] = None,
    ) -> Dict:
        alpha = alpha if alpha is not None else self.alpha
        dep = self._resolve_time(departure_time, date_str, current_minutes)
        parsed = (
            parse_client_buildings(client_buildings)
            if client_buildings else None
        )
        allowed = WALK_ALLOWED if mode in ("walking", "running") else CYCLE_ALLOWED

        # Use realistic Directions routes to seed graph connectivity.
        candidates = self._fetch_directions(
            start_lon, start_lat, end_lon, end_lat, mode,
        )
        print(f"[shade-router] {len(candidates)} directions candidate route(s)")

        road_features = self._fetch_road_network(
            start_lon, start_lat, end_lon, end_lat, allowed, candidates,
        )
        print(f"[shade-router] {len(road_features)} road features from tilequery")

        G, src, tgt, candidate_paths = self._build_graph(
            road_features, candidates, start_lon, start_lat, end_lon, end_lat,
        )
        print(
            f"[shade-router] Graph: {G.number_of_nodes()} nodes, "
            f"{G.number_of_edges()} edges"
        )

        buildings = self._gather_buildings(
            candidates, road_features, start_lon, start_lat, end_lon, end_lat, parsed,
        )
        bldg_idx = self._spatial_index(buildings)
        sun = self._sun(
            dep, (start_lat + end_lat) / 2, (start_lon + end_lon) / 2,
        )

        shadow_polys: Dict[str, list] = {}
        if sun.is_daylight and sun.altitude > 0:
            for building in buildings:
                poly = self._sc.calculate_shadow_polygon(building, sun)
                if poly:
                    shadow_polys[building.id] = poly

        print(
            f"[shade-router] {len(buildings)} buildings, "
            f"{len(shadow_polys)} shadow polygons "
            f"(sun alt {sun.altitude:.1f}°)"
        )

        self._score_edges(G, sun, alpha, bldg_idx, shadow_polys, mode)

        try:
            shortest_path = nx.astar_path(
                G, src, tgt,
                weight="distance",
                heuristic=lambda u, v: self._h(G, u, v),
            )
            shortest_distance = self._path_distance(G, shortest_path)
        except nx.NetworkXNoPath:
            raise ValueError("Unable to connect start and destination on the road network.")

        try:
            best_shaded = nx.astar_path(
                G, src, tgt,
                weight="shade_cost",
                heuristic=lambda u, v: self._h(G, u, v),
            )
        except nx.NetworkXNoPath:
            # This should be rare because the graph is seeded with Directions paths.
            best_shaded = shortest_path

        distance_paths = self._shortest_paths_by_weight(
            G, src, tgt, "distance", max(k * 6, 10),
        )
        shade_paths = self._shortest_paths_by_weight(
            G, src, tgt, "shade_cost", max(k * 6, 10),
        )
        raw_paths = [shortest_path, best_shaded, *distance_paths, *shade_paths, *candidate_paths]
        if not raw_paths:
            raw_paths = [best_shaded, shortest_path]

        paths = self._filter_reasonable_paths(
            G, raw_paths, shortest_distance, keep=max(k * 4, 12),
        )
        if not paths:
            paths = [best_shaded]

        if shortest_path not in paths and not self._is_geo_duplicate(G, shortest_path, paths):
            if self._path_distance(G, shortest_path) <= self._reasonable_distance_limit(shortest_distance):
                paths.append(shortest_path)

        if len(paths) < k:
            self._append_fallback_paths(
                G, paths, candidate_paths, shortest_distance, k,
            )
        if len(paths) < k:
            self._append_fallback_paths(
                G, paths, raw_paths, shortest_distance, k,
                limit=self._fallback_distance_limit(shortest_distance),
                duplicate_threshold=0.92,
            )
        paths = self._deduplicate_paths(G, paths, max(k * 4, 12))

        if mode == "walking":
            speed = self.WALK_SPEED
        elif mode == "running":
            speed = self.RUN_SPEED
        else:
            speed = self.CYCLE_SPEED
        shadow_cache: Dict[str, Dict[str, list]] = {}
        routes = [
            self._path_to_route(
                G, path, idx, mode, speed, dep,
                alpha, buildings, bldg_idx, shadow_cache,
            )
            for idx, path in enumerate(paths)
        ]
        self._rank(routes)
        routes = routes[:k]

        avg_dur = sum(route["duration_seconds"] for route in routes) / max(len(routes), 1)
        return {
            "success": True,
            "routes": routes,
            "departure_time": dep.isoformat(),
            "travel_mode": mode,
            "update_interval_seconds": max(60, min(300, int(avg_dur / 5))),
            "route_count": len(routes),
            "graph_info": {
                "nodes": G.number_of_nodes(),
                "edges": G.number_of_edges(),
                "road_features": len(road_features),
                "candidate_routes": len(candidates),
                "buildings_used": len(buildings),
                "shadow_polys": len(shadow_polys),
                "shortest_distance_meters": round(shortest_distance, 1),
            },
        }

    def update_route_shadows(
        self,
        route_coordinates: List[List[float]],
        user_lat: float, user_lon: float,
        departure_time: datetime,
        elapsed_seconds: float,
        mode: str = "walking",
        total_duration_seconds: float = 0,
        client_buildings: Optional[List[Dict]] = None,
    ) -> Dict:
        parsed = (parse_client_buildings(client_buildings)
                  if client_buildings else [])
        now = departure_time + timedelta(seconds=elapsed_seconds)
        buildings = self._gather_route_buildings(route_coordinates, parsed)
        sun = self._sun(now, user_lat, user_lon)

        in_shadow = self._point_shaded(user_lat, user_lon, sun, buildings)

        closest = min(
            range(len(route_coordinates)),
            key=lambda i: _haversine(
                user_lat, user_lon,
                route_coordinates[i][1], route_coordinates[i][0],
            ),
        )
        remaining = route_coordinates[closest:]
        rem_dur = max(0, total_duration_seconds - elapsed_seconds)

        pct = self._estimate_remaining_shade_pct(
            remaining, now, rem_dur, buildings,
        )
        progress = min(100, elapsed_seconds / max(1, total_duration_seconds) * 100)

        return {
            "success": True,
            "current_in_shadow": in_shadow,
            "remaining_shade_pct": round(pct, 1),
            "reroute_suggested": pct < 25,
            "progress_pct": round(progress, 1),
            "sun_altitude": round(sun.altitude, 1),
            "sun_azimuth": round(sun.azimuth, 1),
        }

    # ── realistic base routes ─────────────────────────────────────────

    def _fetch_directions(self, s_lon, s_lat, e_lon, e_lat, mode):
        profile = "walking" if mode in ("walking", "running") else "cycling"
        base = f"https://api.mapbox.com/directions/v5/mapbox/{profile}"
        common = {
            "geometries": "geojson",
            "overview": "full",
            "access_token": MAPBOX_TOKEN,
        }

        routes: List[Dict] = []
        try:
            resp = http_req.get(
                f"{base}/{s_lon},{s_lat};{e_lon},{e_lat}",
                params={**common, "alternatives": "true"},
                timeout=15,
            )
            resp.raise_for_status()
            routes = resp.json().get("routes", [])
        except Exception as exc:
            print(f"[shade-router] Directions error: {exc}")

        if len(routes) < 3:
            mid_lon = (s_lon + e_lon) / 2
            mid_lat = (s_lat + e_lat) / 2
            dx, dy = e_lon - s_lon, e_lat - s_lat
            norm = max(math.hypot(dx, dy), 1e-8)
            perp_x, perp_y = -dy / norm, dx / norm

            for offset in (0.002, -0.002):
                if len(routes) >= 3:
                    break
                wp_lon = mid_lon + perp_x * offset
                wp_lat = mid_lat + perp_y * offset
                try:
                    resp = http_req.get(
                        f"{base}/{s_lon},{s_lat};{wp_lon},{wp_lat};{e_lon},{e_lat}",
                        params=common,
                        timeout=15,
                    )
                    resp.raise_for_status()
                    alt_routes = resp.json().get("routes", [])
                    if alt_routes:
                        routes.append(alt_routes[0])
                except Exception:
                    pass

        return routes

    # ── Road network from Tilequery ───────────────────────────────────

    def _fetch_road_network(
        self, s_lon, s_lat, e_lon, e_lat, allowed_classes, candidates,
    ):
        seen_geoms: Set[str] = set()
        features: List[Dict] = []
        calls = 0

        samples = self._candidate_corridor_samples(candidates)
        if not samples:
            samples = self._beeline_corridor_samples(s_lon, s_lat, e_lon, e_lat)

        for lon, lat in samples:
            if calls >= MAX_TILEQUERY_CALLS:
                break
            for feat in self._tilequery_roads(lon, lat):
                geom = feat.get("geometry", {})
                if geom.get("type") != "LineString":
                    continue
                road_class = feat.get("properties", {}).get("class", "")
                if road_class and road_class not in allowed_classes:
                    continue
                gkey = self._geom_key(geom)
                if gkey in seen_geoms:
                    continue
                seen_geoms.add(gkey)
                features.append(feat)
            calls += 1

        return features

    def _beeline_corridor_samples(self, s_lon, s_lat, e_lon, e_lat):
        beeline = _haversine(s_lat, s_lon, e_lat, e_lon)
        count = max(3, int(beeline / ROAD_SAMPLE_SPACING) + 1)
        dx, dy = e_lon - s_lon, e_lat - s_lat
        norm = max(math.hypot(dx, dy), 1e-8)
        px, py = -dy / norm, dx / norm
        offsets = (0.0, 0.0010, -0.0010)

        samples = []
        seen = set()
        for i in range(count):
            frac = i / max(count - 1, 1)
            base_lon = s_lon + frac * dx
            base_lat = s_lat + frac * dy
            for offset in offsets:
                key = (round(base_lon + px * offset, 6), round(base_lat + py * offset, 6))
                if key not in seen:
                    seen.add(key)
                    samples.append(key)
        return samples

    def _candidate_corridor_samples(self, candidates):
        samples = []
        seen = set()

        for route in candidates:
            coords = route.get("geometry", {}).get("coordinates", [])
            line_samples = self._sample_polyline(coords, ROAD_SAMPLE_SPACING)
            if not line_samples:
                continue

            for i, (lon, lat) in enumerate(line_samples):
                prev_lon, prev_lat = line_samples[max(i - 1, 0)]
                next_lon, next_lat = line_samples[min(i + 1, len(line_samples) - 1)]
                dx, dy = next_lon - prev_lon, next_lat - prev_lat
                norm = max(math.hypot(dx, dy), 1e-8)
                px, py = -dy / norm, dx / norm

                for offset in (0.0, 0.0010, -0.0010):
                    key = (round(lon + px * offset, 6), round(lat + py * offset, 6))
                    if key not in seen:
                        seen.add(key)
                        samples.append(key)

        return samples

    def _tilequery_roads(self, lon, lat):
        ck = f"rd_{round(lon, 4)}_{round(lat, 4)}"
        if ck in self._road_cache:
            return self._road_cache[ck]

        url = (
            f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/"
            f"tilequery/{lon},{lat}.json"
        )
        params = {
            "radius": ROAD_TILEQUERY_RADIUS,
            "layers": "road",
            "limit": 50,
            "access_token": MAPBOX_TOKEN,
        }
        try:
            resp = http_req.get(url, params=params, timeout=10)
            resp.raise_for_status()
            feats = resp.json().get("features", [])
        except Exception as exc:
            print(f"[shade-router] Tilequery error: {exc}")
            feats = []

        self._road_cache[ck] = feats
        return feats

    @staticmethod
    def _geom_key(geom):
        raw = str((geom.get("type", ""), geom.get("coordinates", [])))
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    # ── Graph construction ────────────────────────────────────────────

    def _build_graph(self, features, candidates, s_lon, s_lat, e_lon, e_lat):
        G = nx.DiGraph()
        merge_grid: Dict[Tuple[int, int], List[Tuple[str, float, float]]] = {}
        candidate_node_paths: List[List[str]] = []

        for f_idx, feat in enumerate(features):
            props = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            self._add_polyline(
                G,
                merge_grid,
                coords,
                route_idx=f_idx,
                road_class=props.get("class", "street"),
                is_oneway=str(props.get("oneway", "")).lower() == "true",
                source="tilequery",
            )

        for r_idx, route in enumerate(candidates):
            coords = route.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            nodes = self._add_polyline(
                G,
                merge_grid,
                coords,
                route_idx=10000 + r_idx,
                road_class="candidate",
                is_oneway=False,
                source="directions",
            )
            if nodes and len(nodes) >= 2:
                candidate_node_paths.append(nodes)

        if G.number_of_nodes() == 0:
            raise ValueError("Could not build a routable road graph for these points.")

        self._connect_endpoint(G, s_lon, s_lat, "S", outbound=True)
        self._connect_endpoint(G, e_lon, e_lat, "E", outbound=False)

        candidate_paths: List[List[str]] = []
        for nodes in candidate_node_paths:
            path = ["S", *nodes, "E"]
            if self._is_valid_path(G, path):
                candidate_paths.append(path)

        return G, "S", "E", candidate_paths

    def _add_polyline(self, G, merge_grid, coords, route_idx, road_class, is_oneway, source):
        sampled = self._sample_polyline(coords, self.seg_len)
        if len(sampled) < 2:
            return []

        nodes: List[str] = []
        for idx, (lon, lat) in enumerate(sampled):
            node_id = self._merge_or_create(
                G,
                merge_grid,
                lon,
                lat,
                f"{source}_{route_idx}_{idx}",
                route_idx,
                float(idx),
            )
            if not nodes or nodes[-1] != node_id:
                nodes.append(node_id)

        for i in range(len(nodes) - 1):
            u, v = nodes[i], nodes[i + 1]
            d = _haversine(
                G.nodes[u]["y"], G.nodes[u]["x"],
                G.nodes[v]["y"], G.nodes[v]["x"],
            )
            d = max(d, 0.1)
            self._add_edge(G, u, v, d, road_class, source)
            if not is_oneway:
                self._add_edge(G, v, u, d, road_class, source)

        return nodes

    @staticmethod
    def _add_edge(G, u, v, distance, road_class, source):
        if G.has_edge(u, v):
            edge = G[u][v]
            edge["distance"] = min(edge.get("distance", distance), distance)
            if not edge.get("road_class"):
                edge["road_class"] = road_class
            if source not in edge.get("source", ""):
                edge["source"] = f"{edge.get('source', '')},{source}".strip(",")
            return

        G.add_edge(
            u,
            v,
            distance=distance,
            road_class=road_class,
            source=source,
        )

    def _merge_or_create(self, G, grid, lon, lat, candidate_id, route_idx, progress):
        cell_size = 0.00008
        row, col = int(lat / cell_size), int(lon / cell_size)

        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                for existing_id, ex_lon, ex_lat in grid.get((row + d_row, col + d_col), []):
                    if _haversine(lat, lon, ex_lat, ex_lon) <= NODE_MERGE_DIST:
                        return existing_id

        G.add_node(candidate_id, x=lon, y=lat, route_idx=route_idx, progress=progress)
        grid.setdefault((row, col), []).append((candidate_id, lon, lat))
        return candidate_id

    def _connect_endpoint(self, G, lon, lat, label, outbound, n_connect=6):
        G.add_node(label, x=lon, y=lat)

        candidates = []
        for node_id, attrs in G.nodes(data=True):
            if node_id in ("S", "E"):
                continue
            d = _haversine(lat, lon, attrs.get("y", 0), attrs.get("x", 0))
            candidates.append((d, node_id))
        candidates.sort(key=lambda item: item[0])

        close = [item for item in candidates if item[0] <= ENDPOINT_CONNECT_RADIUS]
        chosen = close[:n_connect] if close else candidates[:1]

        for distance, node_id in chosen:
            if outbound:
                self._add_edge(G, label, node_id, max(distance, 0.1), "connector", "endpoint")
            else:
                self._add_edge(G, node_id, label, max(distance, 0.1), "connector", "endpoint")

    def _sample_polyline(self, coords, spacing_m):
        if not coords:
            return []
        if len(coords) == 1:
            return [(coords[0][0], coords[0][1])]

        cum = [0.0]
        for idx in range(1, len(coords)):
            seg_d = _haversine(
                coords[idx - 1][1], coords[idx - 1][0],
                coords[idx][1], coords[idx][0],
            )
            cum.append(cum[-1] + seg_d)

        total = cum[-1]
        if total < 1:
            return [(coords[0][0], coords[0][1]), (coords[-1][0], coords[-1][1])]

        targets = [0.0]
        cursor = spacing_m
        while cursor < total:
            targets.append(cursor)
            cursor += spacing_m
        if total - targets[-1] > 1.0:
            targets.append(total)

        sampled = []
        seg_idx = 0
        for target in targets:
            while seg_idx < len(cum) - 2 and cum[seg_idx + 1] < target:
                seg_idx += 1

            leg = max(cum[seg_idx + 1] - cum[seg_idx], 1e-10)
            frac = max(0.0, min(1.0, (target - cum[seg_idx]) / leg))
            next_idx = min(seg_idx + 1, len(coords) - 1)
            lon = coords[seg_idx][0] + frac * (coords[next_idx][0] - coords[seg_idx][0])
            lat = coords[seg_idx][1] + frac * (coords[next_idx][1] - coords[seg_idx][1])
            point = (lon, lat)
            if not sampled or _haversine(lat, lon, sampled[-1][1], sampled[-1][0]) > 0.5:
                sampled.append(point)

        if sampled[-1] != (coords[-1][0], coords[-1][1]):
            sampled.append((coords[-1][0], coords[-1][1]))
        return sampled

    # ── edge scoring with multi-point shadow sampling ─────────────────

    def _spatial_index(self, buildings):
        idx: Dict[Tuple[int, int], List[Building]] = {}
        cell_size = 0.003
        for building in buildings:
            cx, cy = building.get_centroid()
            idx.setdefault((int(cy / cell_size), int(cx / cell_size)), []).append(building)
        return idx

    def _score_edges(self, G, sun, alpha, bldg_idx, shadow_polys, mode):
        for u, v, data in G.edges(data=True):
            d = data.get("distance", 0.0)
            ux = G.nodes[u].get("x", 0.0)
            uy = G.nodes[u].get("y", 0.0)
            vx = G.nodes[v].get("x", 0.0)
            vy = G.nodes[v].get("y", 0.0)
            road_class = data.get("road_class", "street")

            shadow_fraction = self._edge_shadow_fraction(
                uy, ux, vy, vx, d, sun, bldg_idx, shadow_polys,
                road_class=road_class, mode=mode,
            )
            exposure = 1.0 - shadow_fraction

            data["sun_exposure"] = exposure
            data["shadow_fraction"] = shadow_fraction
            data["shade_cost"] = d * (1.0 + alpha * exposure)

    def _edge_shadow_fraction(
        self, lat1, lon1, lat2, lon2, distance, sun, bldg_idx, shadow_polys,
        road_class="street", mode="walking",
    ):
        if not sun.is_daylight or sun.altitude <= 0:
            return 1.0

        samples = max(2, int(distance / SHADOW_SAMPLE_SPACING) + 1)
        offsets = self._road_sampling_offsets(road_class, mode)
        profile_fracs: List[float] = []

        for offset_m in offsets:
            shaded = 0
            for idx in range(samples):
                frac = idx / max(samples - 1, 1)
                lat = lat1 + frac * (lat2 - lat1)
                lon = lon1 + frac * (lon2 - lon1)
                if abs(offset_m) > 1e-6:
                    lon, lat = self._offset_point_perpendicular(
                        lat, lon, lat1, lon1, lat2, lon2, offset_m,
                    )
                if self._exposure_at(lat, lon, sun, bldg_idx, shadow_polys) == 0.0:
                    shaded += 1
            profile_fracs.append(shaded / samples)

        if not profile_fracs:
            return 0.0
        if mode == "walking":
            return max(profile_fracs)
        if len(profile_fracs) == 1:
            return profile_fracs[0]
        center = profile_fracs[0]
        sides = profile_fracs[1:]
        return min(1.0, 0.7 * center + 0.3 * (sum(sides) / max(len(sides), 1)))

    def _road_sampling_offsets(self, road_class, mode):
        width = self._estimate_road_width_m(road_class)
        if width <= 3.5:
            return [0.0]

        side_offset = max(1.2, min(width / 2.5, 5.0))
        if mode == "walking":
            return [0.0, side_offset, -side_offset]
        return [0.0, side_offset * 0.5, -side_offset * 0.5]

    @staticmethod
    def _estimate_road_width_m(road_class):
        widths = {
            "primary": 18.0,
            "primary_link": 14.0,
            "secondary": 14.0,
            "secondary_link": 12.0,
            "tertiary": 11.0,
            "tertiary_link": 10.0,
            "street": 9.0,
            "street_limited": 8.0,
            "residential": 8.0,
            "service": 7.0,
            "unclassified": 8.0,
            "pedestrian": 6.0,
            "living_street": 6.0,
            "track": 5.0,
            "path": 3.0,
            "footway": 2.5,
            "steps": 2.0,
            "cycleway": 3.0,
            "candidate": 8.0,
            "connector": 4.0,
        }
        return widths.get(road_class, 8.0)

    def _offset_point_perpendicular(self, lat, lon, lat1, lon1, lat2, lon2, offset_m):
        dx_m = (lon2 - lon1) * self._sc.meters_per_degree_lon
        dy_m = (lat2 - lat1) * self._sc.METERS_PER_DEGREE_LAT
        norm = max(math.hypot(dx_m, dy_m), 1e-6)
        perp_x = -dy_m / norm
        perp_y = dx_m / norm
        dlon = (perp_x * offset_m) / self._sc.meters_per_degree_lon
        dlat = (perp_y * offset_m) / self._sc.METERS_PER_DEGREE_LAT
        return lon + dlon, lat + dlat

    def _exposure_at(self, lat, lon, sun, bldg_idx, shadow_polys, cell_size=0.003):
        if not sun.is_daylight or sun.altitude <= 0:
            return 0.0
        cell = (int(lat / cell_size), int(lon / cell_size))
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                for building in bldg_idx.get((cell[0] + dx, cell[1] + dy), []):
                    poly = shadow_polys.get(building.id)
                    if poly and _point_in_polygon(lon, lat, poly):
                        return 0.0
        return 1.0

    def _point_shaded(self, lat, lon, sun, buildings):
        if not sun.is_daylight or sun.altitude <= 0:
            return True
        for building in buildings:
            poly = self._sc.calculate_shadow_polygon(building, sun)
            if poly and _point_in_polygon(lon, lat, poly):
                return True
        return False

    # ── routing algorithms ────────────────────────────────────────────

    def _h(self, G, u, v):
        return _haversine(
            G.nodes[u]["y"], G.nodes[u]["x"],
            G.nodes[v]["y"], G.nodes[v]["x"],
        )

    def _yen(self, G, src, tgt, k):
        try:
            return list(
                itertools.islice(
                    nx.shortest_simple_paths(G, src, tgt, weight="shade_cost"),
                    k,
                )
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXNotImplemented):
            return []

    def _shortest_paths_by_weight(self, G, src, tgt, weight, k):
        try:
            return list(
                itertools.islice(
                    nx.shortest_simple_paths(G, src, tgt, weight=weight),
                    k,
                )
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXNotImplemented):
            return []

    def _reasonable_distance_limit(self, shortest_distance):
        return min(
            shortest_distance * MAX_REASONABLE_DETOUR_FACTOR,
            shortest_distance + MAX_REASONABLE_EXTRA_METERS,
        )

    def _fallback_distance_limit(self, shortest_distance):
        return min(
            shortest_distance * 1.6,
            shortest_distance + 1800,
        )

    def _filter_reasonable_paths(self, G, paths, shortest_distance, keep):
        limit = self._reasonable_distance_limit(shortest_distance)
        unique = []
        for path in paths:
            if not self._is_valid_path(G, path):
                continue
            if self._path_distance(G, path) > limit:
                continue
            if not self._is_geo_duplicate(G, path, unique):
                unique.append(path)
            if len(unique) >= keep:
                break
        return unique

    def _deduplicate_paths(self, G, paths, keep):
        unique = []
        for path in paths:
            if len(unique) >= keep:
                break
            if not self._is_geo_duplicate(G, path, unique):
                unique.append(path)
        return unique

    def _append_fallback_paths(
        self, G, target_paths, candidate_paths, shortest_distance, keep,
        limit=None, duplicate_threshold=0.85,
    ):
        limit = limit if limit is not None else self._reasonable_distance_limit(shortest_distance)
        for path in candidate_paths:
            if len(target_paths) >= keep:
                break
            if not path or not self._is_valid_path(G, path):
                continue
            if self._path_distance(G, path) > limit:
                continue
            if self._contains_exact_path(target_paths, path):
                continue
            if self._is_geo_duplicate(G, path, target_paths, threshold=duplicate_threshold):
                continue
            target_paths.append(path)

        if len(target_paths) >= keep:
            return

        for path in candidate_paths:
            if len(target_paths) >= keep:
                break
            if not path or not self._is_valid_path(G, path):
                continue
            if self._path_distance(G, path) > limit:
                continue
            if self._contains_exact_path(target_paths, path):
                continue
            target_paths.append(path)

    def _is_geo_duplicate(self, G, path, existing_paths, threshold=0.70):
        for existing in existing_paths:
            shared = len(set(path) & set(existing))
            overlap = shared / max(len(path), len(existing), 1)
            if overlap > threshold:
                return True
        return False

    @staticmethod
    def _contains_exact_path(existing_paths, candidate):
        return any(path == candidate for path in existing_paths)

    @staticmethod
    def _is_valid_path(G, path):
        return all(G.has_edge(path[i], path[i + 1]) for i in range(len(path) - 1))

    @staticmethod
    def _path_distance(G, path):
        total = 0.0
        for i in range(len(path) - 1):
            total += G[path[i]][path[i + 1]].get("distance", 0.0)
        return total

    def _evaluate_path_metrics(
        self, G, path, dep, speed, alpha, buildings, bldg_idx, shadow_cache, mode,
    ):
        total_distance = 0.0
        total_shade_cost = 0.0
        weighted_exposure = 0.0
        elapsed_seconds = 0.0

        for i in range(len(path) - 1):
            u = path[i]
            v = path[i + 1]
            edge = G[u][v]
            seg_d = edge.get("distance", 0.0)
            road_class = edge.get("road_class", "street")
            ux = G.nodes[u].get("x", 0.0)
            uy = G.nodes[u].get("y", 0.0)
            vx = G.nodes[v].get("x", 0.0)
            vy = G.nodes[v].get("y", 0.0)
            mid_lon = (ux + vx) / 2
            mid_lat = (uy + vy) / 2

            edge_time = departure_time + timedelta(seconds=elapsed_seconds + seg_d / max(speed, 0.1))
            sun = self._sun(edge_time, mid_lat, mid_lon)
            shadow_polys = self._shadow_polys_for_bucket(
                buildings, sun, edge_time, shadow_cache,
            )
            shadow_fraction = self._edge_shadow_fraction(
                uy, ux, vy, vx, seg_d, sun, bldg_idx, shadow_polys,
                road_class=road_class, mode=mode,
            )
            exposure = 1.0 - shadow_fraction

            total_distance += seg_d
            total_shade_cost += seg_d * (1.0 + alpha * exposure)
            weighted_exposure += exposure * seg_d
            elapsed_seconds += seg_d / max(speed, 0.1)

        return {
            "distance_meters": total_distance,
            "duration_seconds": elapsed_seconds,
            "avg_exposure": weighted_exposure / max(total_distance, 1.0),
            "shade_cost": total_shade_cost,
        }

    def _shadow_polys_for_bucket(self, buildings, sun, dt, shadow_cache):
        bucket = dt.strftime("%Y-%m-%dT%H:%M")
        if bucket in shadow_cache:
            return shadow_cache[bucket]

        shadow_polys: Dict[str, list] = {}
        if sun.is_daylight and sun.altitude > 0:
            for building in buildings:
                poly = self._sc.calculate_shadow_polygon(building, sun)
                if poly:
                    shadow_polys[building.id] = poly

        shadow_cache[bucket] = shadow_polys
        return shadow_polys

    # ── route building ────────────────────────────────────────────────

    def _path_to_route(
        self, G, path, rid, mode, speed, dep,
        alpha, buildings, bldg_idx, shadow_cache,
    ):
        coords: List[List[float]] = []

        for node in path:
            x = G.nodes[node].get("x")
            y = G.nodes[node].get("y")
            if x is None or y is None:
                continue
            if not coords or abs(x - coords[-1][0]) > 1e-8 or abs(y - coords[-1][1]) > 1e-8:
                coords.append([x, y])

        metrics = self._evaluate_path_metrics(
            G, path, dep, speed, alpha, buildings, bldg_idx, shadow_cache, mode,
        )
        total_distance = metrics["distance_meters"]
        avg_exp = metrics["avg_exposure"]
        shade_pct = round((1.0 - avg_exp) * 100, 1)
        duration_seconds = metrics["duration_seconds"]
        duration_minutes = round(duration_seconds / 60)
        sun_minutes = round(duration_minutes * avg_exp)

        if shade_pct >= 60:
            risk, risk_color = "LOW", "#22c55e"
        elif shade_pct >= 30:
            risk, risk_color = "MEDIUM", "#f59e0b"
        else:
            risk, risk_color = "HIGH", "#ef4444"

        distance_km = round(total_distance / 1000, 1)
        if shade_pct >= 70:
            reason = (
                f"{distance_km}km · {duration_minutes}min · {shade_pct}% shaded – "
                "strong building shade coverage"
            )
        elif shade_pct >= 40:
            reason = (
                f"{distance_km}km · {duration_minutes}min · {shade_pct}% shaded – "
                "balanced shade and travel time"
            )
        else:
            reason = (
                f"{distance_km}km · {duration_minutes}min · {shade_pct}% shaded – "
                f"faster route with ~{sun_minutes}min in direct sun"
            )

        return {
            "route_id": rid,
            "geometry": {"type": "LineString", "coordinates": coords},
            "distance_meters": round(total_distance, 1),
            "distance_km": distance_km,
            "duration_seconds": round(duration_seconds, 1),
            "duration_minutes": duration_minutes,
            "shade_coverage_pct": shade_pct,
            "sun_exposure_minutes": sun_minutes,
            "shade_score": round(shade_pct / 100, 3),
            "duration_score": 0.0,
            "final_score": 0.0,
            "label": "",
            "risk_level": risk,
            "risk_color": risk_color,
            "reason": reason,
            "optimisation_cost": metrics["shade_cost"],
        }

    def _rank(self, routes):
        if not routes:
            return

        max_duration = max(route["duration_seconds"] for route in routes)
        min_duration = min(route["duration_seconds"] for route in routes)
        duration_range = max(max_duration - min_duration, 1.0)

        for route in routes:
            duration_score = 1.0 - (route["duration_seconds"] - min_duration) / duration_range
            route["duration_score"] = round(duration_score, 3)
            route["final_score"] = round(
                (0.9 * route["shade_score"] + 0.1 * duration_score) * 100,
                1,
            )

        routes.sort(
            key=lambda route: (-route["final_score"], route["optimisation_cost"]),
        )

        if len(routes) == 1:
            routes[0]["label"] = "Best Route"
            return

        best_shade_idx = max(
            range(len(routes)),
            key=lambda idx: routes[idx]["shade_coverage_pct"],
        )
        shortest_idx = min(
            range(len(routes)),
            key=lambda idx: routes[idx]["duration_seconds"],
        )

        for idx, route in enumerate(routes):
            if idx == best_shade_idx:
                route["label"] = "Most Shaded"
            elif idx == shortest_idx:
                route["label"] = "Shortest"
            else:
                route["label"] = "Balanced"

    # ── building data ─────────────────────────────────────────────────

    def _gather_buildings(
        self, candidates, road_features, s_lon, s_lat, e_lon, e_lat, parsed,
    ):
        all_buildings: List[Building] = []
        seen: Set[str] = set()

        if parsed:
            for building in parsed:
                if building.id not in seen:
                    seen.add(building.id)
                    all_buildings.append(building)

        sample_points = []
        for route in candidates:
            coords = route.get("geometry", {}).get("coordinates", [])
            sample_points.extend(self._sample_polyline(coords, ROAD_SAMPLE_SPACING))

        feature_step = max(1, len(road_features) // 30) if road_features else 1
        for feat in road_features[::feature_step]:
            coords = feat.get("geometry", {}).get("coordinates", [])
            sample_points.extend(self._sample_polyline(coords, ROAD_SAMPLE_SPACING * 2))

        if not sample_points:
            sample_points = self._beeline_corridor_samples(s_lon, s_lat, e_lon, e_lat)

        for lon, lat in sample_points:
            for building in self._fetch_buildings(lat, lon):
                if building.id not in seen:
                    seen.add(building.id)
                    all_buildings.append(building)

        print(
            f"[shade-router] {len(all_buildings)} buildings from "
            f"{len(sample_points)} corridor samples"
        )
        return all_buildings

    def _gather_route_buildings(self, route_coordinates, parsed):
        buildings: List[Building] = []
        seen: Set[str] = set()

        for building in parsed:
            if building.id not in seen:
                seen.add(building.id)
                buildings.append(building)

        for lon, lat in self._sample_polyline(route_coordinates, ROAD_SAMPLE_SPACING):
            for building in self._fetch_buildings(lat, lon):
                if building.id not in seen:
                    seen.add(building.id)
                    buildings.append(building)

        return buildings

    def get_route_segment_shadows(
        self,
        route_coordinates: List[List[float]],
        departure_time: datetime,
        mode: str = "walking",
        client_buildings: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Debug/validation: return per-segment shadow fraction for a route.

        Args:
            route_coordinates: List of [lon, lat] points
            departure_time: When the route starts
            mode: "walking" or "cycling"
            client_buildings: Optional pre-fetched buildings

        Returns:
            {"segments": [{"lon", "lat", "shadow_fraction", "segment_index"}, ...], ...}
        """
        parsed = parse_client_buildings(client_buildings) if client_buildings else []
        buildings = self._gather_route_buildings(route_coordinates, parsed)
        bldg_idx = self._spatial_index(buildings)
        if mode == "walking":
            speed = self.WALK_SPEED
        elif mode == "running":
            speed = self.RUN_SPEED
        else:
            speed = self.CYCLE_SPEED

        sampled = self._sample_polyline(route_coordinates, self.seg_len)
        if len(sampled) < 2:
            return {"segments": [], "buildings_used": len(buildings)}

        segments_out: List[Dict] = []
        elapsed_seconds = 0.0
        total_time = 0.0
        total_shade_time = 0.0
        spd = max(speed, 0.1)

        for idx in range(len(sampled) - 1):
            lon1, lat1 = sampled[idx]
            lon2, lat2 = sampled[idx + 1]
            seg_d = _haversine(lat1, lon1, lat2, lon2)
            mid_lon = (lon1 + lon2) / 2
            mid_lat = (lat1 + lat2) / 2
            segment_time = seg_d / spd  # seconds in this segment
            total_time += segment_time

            edge_time = departure_time + timedelta(
              seconds=elapsed_seconds + segment_time)

            sun = self._sun(edge_time, mid_lat, mid_lon)
            shadow_polys: Dict[str, list] = {}
            if sun.is_daylight and sun.altitude > 0:
                for b in buildings:
                    poly = self._sc.calculate_shadow_polygon(b, sun)
                    if poly:
                        shadow_polys[b.id] = poly

            shadow_fraction = 0.0
            if sun.is_daylight and sun.altitude > 0:
                for b in buildings:
                    poly = shadow_polys.get(b.id)
                    if poly and _point_in_polygon(mid_lon, mid_lat, poly):
                        shadow_fraction = 1.0
                        break
            else:
                shadow_fraction = 1.0

            total_shade_time += shadow_fraction * segment_time
            segments_out.append({
                "lon": round(mid_lon, 6),
                "lat": round(mid_lat, 6),
                "shadow_fraction": round(shadow_fraction, 3),
                "segment_index": idx,
            })
            elapsed_seconds += segment_time

        weighted_shade_fraction = total_shade_time / total_time if total_time > 0 else 0.0
        return {
            "segments": segments_out,
            "buildings_used": len(buildings),
            "departure_time": departure_time.isoformat(),
            "weighted_shade_fraction": round(weighted_shade_fraction, 4),
            "total_route_time_seconds": round(total_time, 1),
            "total_shade_time_seconds": round(total_shade_time, 1),
        }

    def _estimate_remaining_shade_pct(self, remaining, now, rem_dur, buildings):
        if len(remaining) < 2:
            return 100.0

        sampled = self._sample_polyline(remaining, self.seg_len)
        if len(sampled) < 2:
            return 100.0

        total_distance = 0.0
        segment_distances = []
        for idx in range(len(sampled) - 1):
            seg_d = _haversine(
                sampled[idx][1], sampled[idx][0],
                sampled[idx + 1][1], sampled[idx + 1][0],
            )
            segment_distances.append(seg_d)
            total_distance += seg_d

        shaded = 0
        total = 0
        walked = 0.0
        for idx, seg_d in enumerate(segment_distances):
            mid_lon = (sampled[idx][0] + sampled[idx + 1][0]) / 2
            mid_lat = (sampled[idx][1] + sampled[idx + 1][1]) / 2
            t = now + timedelta(seconds=(rem_dur * ((walked + seg_d / 2) / max(total_distance, 1.0))))
            s = self._sun(t, mid_lat, mid_lon)
            if self._point_shaded(mid_lat, mid_lon, s, buildings):
                shaded += 1
            total += 1
            walked += seg_d

        return (shaded / max(total, 1)) * 100

    def _fetch_buildings(self, lat, lon) -> List[Building]:
        ck = f"{round(lat, 3)},{round(lon, 3)}"
        if ck in self._bldg_cache:
            return self._bldg_cache[ck]

        url = (
            f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/"
            f"tilequery/{lon},{lat}.json"
        )
        params = {
            "radius": BUILDING_FETCH_RADIUS,
            "layers": "building",
            "limit": 50,
            "access_token": MAPBOX_TOKEN,
        }
        try:
            resp = http_req.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            self._bldg_cache[ck] = []
            return []

        buildings: List[Building] = []
        for idx, feat in enumerate(data.get("features", [])):
            geom = feat.get("geometry", {})
            props = feat.get("properties", {})
            gtype = geom.get("type", "")

            if gtype == "Polygon":
                ring = geom.get("coordinates", [[]])[0]
                footprint = [(coord[0], coord[1]) for coord in ring]
                if len(footprint) < 3:
                    continue
            elif gtype == "Point":
                gc = geom.get("coordinates", [])
                if len(gc) < 2:
                    continue
                cx, cy = gc[0], gc[1]
                size = 0.00015
                footprint = [
                    (cx - size, cy - size),
                    (cx + size, cy - size),
                    (cx + size, cy + size),
                    (cx - size, cy + size),
                    (cx - size, cy - size),
                ]
            else:
                continue

            height = max(
                1.0,
                float(props.get("height") or DEFAULT_BUILDING_HEIGHT)
                - float(props.get("min_height") or 0),
            )
            buildings.append(
                Building(
                    id=f"b_{ck}_{idx}",
                    footprint=footprint,
                    height=height,
                    name=props.get("type", "building"),
                )
            )

        self._bldg_cache[ck] = buildings
        return buildings

    # ── helpers ───────────────────────────────────────────────────────

    def _resolve_time(self, dt, date_str, minutes):
        if dt:
            return dt
        if date_str and minutes is not None:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            return date_obj.replace(
                hour=int(minutes) // 60,
                minute=int(minutes) % 60,
            )
        return datetime.now()

    def _sun(self, dt, lat, lon) -> SunPosition:
        tz = self.TZ
        doy = dt.timetuple().tm_yday
        dec = 23.45 * math.sin(math.radians(360 / 365 * (284 + doy)))
        b_angle = math.radians(360 / 365 * (doy - 81))
        eot = 9.87 * math.sin(2 * b_angle) - 7.53 * math.cos(b_angle) - 1.5 * math.sin(b_angle)
        solar_time = dt.hour * 60 + dt.minute + eot + 4 * (lon - tz * 15)
        ha = solar_time / 4 - 180
        lat_r = math.radians(lat)
        dec_r = math.radians(dec)
        ha_r = math.radians(ha)
        sin_alt = (
            math.sin(lat_r) * math.sin(dec_r)
            + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r)
        )
        sin_alt = max(-1.0, min(1.0, sin_alt))
        alt = math.degrees(math.asin(sin_alt))
        cos_az = (math.sin(dec_r) - math.sin(lat_r) * sin_alt) / (
            math.cos(lat_r) * math.cos(math.asin(sin_alt)) + 1e-10
        )
        cos_az = max(-1.0, min(1.0, cos_az))
        az = math.degrees(math.acos(cos_az))
        if ha > 0:
            az = 360 - az
        return SunPosition(
            azimuth=az,
            altitude=alt,
            zenith=90 - alt,
            is_daylight=alt > 0,
        )
