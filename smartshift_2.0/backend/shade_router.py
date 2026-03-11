"""
shade_router.py — Mapbox Directions + segment graph + A* + Yen's

Pipeline
--------
1. Mapbox Directions API  →  1–3 candidate walking / cycling routes
2. Split each polyline into ~15 m segments  →  directed graph
3. MERGE nodes from different routes that land on the same road
   (within NODE_MERGE_DIST)  →  graph branches only where routes diverge
4. Score every segment:  edge_cost = distance × (1 + α × exposure)
5. A*  →  optimal shaded path through the merged graph
6. Yen's K-shortest  →  2–3 *genuinely different* alternatives
7. Return GeoJSON polylines  →  render on Mapbox

"""

import math
import itertools
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import networkx as nx
import requests as http_req

from shadow_calculator import ShadowCalculator, Building
from solar_position import SunPosition
from shadow_scheduler import parse_client_buildings, _point_in_polygon, _haversine

MAPBOX_TOKEN = (
    "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9"
    ".WI13BJqDyOu6G38-YP6hog"
)
BUILDING_FETCH_RADIUS = 300
DEFAULT_BUILDING_HEIGHT = 30.0
SEGMENT_LENGTH = 15        # metres between sample nodes
NODE_MERGE_DIST = 10       # metres – nodes closer than this become ONE node


class ShadeRouter:
    """
    Hybrid routing engine.

    Mapbox supplies realistic road-following candidate routes;
    this class chops them into a fine-grained directed graph,
    *merges* nodes that occupy the same physical location so the
    graph branches only where routes truly diverge, scores each
    segment with shadow data, then runs A* and Yen's K-shortest
    to return shade-optimised alternatives.
    """

    TZ = 4.0               # Dubai UTC+4
    WALK_SPEED = 1.4       # m/s
    CYCLE_SPEED = 4.0      # m/s

    def __init__(self, alpha: float = 1.0, segment_length: float = SEGMENT_LENGTH):
        self.alpha = alpha
        self.seg_len = segment_length
        self._sc = ShadowCalculator()
        self._bldg_cache: Dict[str, List[Building]] = {}

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
        parsed = (parse_client_buildings(client_buildings)
                  if client_buildings else None)

        # 1 ── Mapbox candidates
        candidates = self._fetch_directions(
            start_lon, start_lat, end_lon, end_lat, mode,
        )
        if not candidates:
            raise ValueError("Mapbox returned no routes for the given points")

        # 2 ── build merged segment graph
        G, src, tgt, per_route_nodes = self._build_graph(
            candidates, start_lon, start_lat, end_lon, end_lat,
        )
        print(f"[shade-router] Segment graph: {G.number_of_nodes()} nodes, "
              f"{G.number_of_edges()} edges  "
              f"({len(candidates)} Mapbox candidates)")

        # 3 ── buildings along EVERY route corridor (not just the beeline)
        buildings = self._gather_buildings(candidates, parsed)
        bldg_idx = self._spatial_index(buildings)
        sun = self._sun(
            dep, (start_lat + end_lat) / 2, (start_lon + end_lon) / 2,
        )

        shadow_polys: Dict[str, list] = {}
        if sun.is_daylight and sun.altitude > 0:
            for b in buildings:
                poly = self._sc.calculate_shadow_polygon(b, sun)
                if poly:
                    shadow_polys[b.id] = poly

        print(f"[shade-router] {len(buildings)} buildings, "
              f"{len(shadow_polys)} shadow polygons  "
              f"(sun alt {sun.altitude:.1f}°)")

        # 4 ── score edges
        self._score_edges(G, sun, alpha, bldg_idx, shadow_polys)

        # 5 ── A* best path
        try:
            best = nx.astar_path(
                G, src, tgt,
                weight="shade_cost",
                heuristic=lambda u, v: self._h(G, u, v),
            )
        except nx.NetworkXNoPath:
            raise ValueError("No path found in the segment graph")

        # 6 ── Yen's K-shortest, then drop geographic duplicates
        paths = self._yen(G, src, tgt, k * 3)
        if not paths:
            paths = [best]
        paths = self._deduplicate_paths(G, paths, k)

        # if still fewer than k, add the raw Mapbox candidates as fallback
        if len(paths) < k:
            for rn in per_route_nodes:
                if len(paths) >= k:
                    break
                fallback = ["S"] + rn + ["E"]
                if self._is_valid_path(G, fallback):
                    if not self._is_geo_duplicate(G, fallback, paths):
                        paths.append(fallback)

        # 7 ── assemble response
        speed = self.WALK_SPEED if mode == "walking" else self.CYCLE_SPEED
        routes = [
            self._path_to_route(G, p, i, mode, speed, dep)
            for i, p in enumerate(paths)
        ]
        self._rank(routes)

        avg_dur = sum(r["duration_seconds"] for r in routes) / len(routes)
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
                "candidate_routes": len(candidates),
                "buildings_used": len(buildings),
                "shadow_polys": len(shadow_polys),
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
        sun = self._sun(now, user_lat, user_lon)

        in_shadow = self._point_shaded(user_lat, user_lon, sun, parsed)

        closest = min(
            range(len(route_coordinates)),
            key=lambda i: _haversine(
                user_lat, user_lon,
                route_coordinates[i][1], route_coordinates[i][0],
            ),
        )
        remaining = route_coordinates[closest:]
        rem_dur = max(0, total_duration_seconds - elapsed_seconds)

        shaded = total = 0
        step = max(1, len(remaining) // 15)
        for i in range(0, len(remaining), step):
            c = remaining[i]
            frac = i / max(len(remaining), 1)
            t = now + timedelta(seconds=frac * rem_dur)
            s = self._sun(t, c[1], c[0])
            if self._point_shaded(c[1], c[0], s, parsed):
                shaded += 1
            total += 1

        pct = (shaded / max(total, 1)) * 100
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

    # ── Mapbox Directions ─────────────────────────────────────────────

    def _fetch_directions(self, s_lon, s_lat, e_lon, e_lat, mode):
        """Fetch 1-3 candidate routes from Mapbox Directions API.

        If Mapbox returns fewer than 3 alternatives, perpendicular
        via-waypoint queries fill in the remaining slots so the
        segment graph always has enough diversity for Yen's.
        """
        profile = "walking" if mode == "walking" else "cycling"
        base = f"https://api.mapbox.com/directions/v5/mapbox/{profile}"
        common = {
            "geometries": "geojson",
            "overview": "full",
            "access_token": MAPBOX_TOKEN,
        }

        # ① direct request with alternatives
        routes: list = []
        try:
            r = http_req.get(
                f"{base}/{s_lon},{s_lat};{e_lon},{e_lat}",
                params={**common, "alternatives": "true"},
                timeout=15,
            )
            r.raise_for_status()
            routes = r.json().get("routes", [])
        except Exception as exc:
            print(f"[shade-router] Mapbox Directions error: {exc}")

        # ② generate via-waypoint alternatives if needed
        if len(routes) < 3:
            mid_lon = (s_lon + e_lon) / 2
            mid_lat = (s_lat + e_lat) / 2
            dx, dy = e_lon - s_lon, e_lat - s_lat
            norm = max(math.hypot(dx, dy), 1e-8)
            perp_x, perp_y = -dy / norm, dx / norm   # 90° rotation

            for offset in (0.002, -0.002):            # ~200 m each side
                if len(routes) >= 3:
                    break
                wp_lon = mid_lon + perp_x * offset
                wp_lat = mid_lat + perp_y * offset
                try:
                    r = http_req.get(
                        f"{base}/{s_lon},{s_lat};"
                        f"{wp_lon},{wp_lat};"
                        f"{e_lon},{e_lat}",
                        params=common, timeout=15,
                    )
                    r.raise_for_status()
                    wp = r.json().get("routes", [])
                    if wp:
                        routes.append(wp[0])
                except Exception:
                    pass

        print(f"[shade-router] {len(routes)} Mapbox candidate route(s)")
        return routes

    # ── segment graph construction ────────────────────────────────────

    def _build_graph(self, candidates, s_lon, s_lat, e_lon, e_lat):
        """Build a directed graph from Mapbox candidate polylines.

        Nodes from different routes that fall within NODE_MERGE_DIST
        of each other are **merged into one node**.  This means shared
        road stretches have a single chain of nodes; the graph only
        branches where the routes truly diverge — giving Yen's
        genuinely different alternatives to explore.

        Returns (G, source_id, target_id, per_route_node_lists).
        """
        G = nx.DiGraph()
        G.add_node("S", x=s_lon, y=s_lat)
        G.add_node("E", x=e_lon, y=e_lat)

        # spatial grid used by _merge_or_create to find existing nodes
        merge_grid: Dict[Tuple[int, int],
                         List[Tuple[str, float, float]]] = {}

        per_route_nodes: List[List[str]] = []

        for r_idx, route in enumerate(candidates):
            coords = route["geometry"]["coordinates"]
            nodes, _ = self._segment_polyline(G, coords, r_idx, merge_grid)
            per_route_nodes.append(nodes)

            first, last = nodes[0], nodes[-1]
            d0 = _haversine(s_lat, s_lon,
                            G.nodes[first]["y"], G.nodes[first]["x"])
            if not G.has_edge("S", first):
                G.add_edge("S", first, distance=max(d0, 0.1))

            d1 = _haversine(G.nodes[last]["y"], G.nodes[last]["x"],
                            e_lat, e_lon)
            if not G.has_edge(last, "E"):
                G.add_edge(last, "E", distance=max(d1, 0.1))

        return G, "S", "E", per_route_nodes

    # ── node merging ──────────────────────────────────────────────────

    def _merge_or_create(self, G, grid, lon, lat, candidate_id,
                         route_idx, progress):
        """Return an existing node within NODE_MERGE_DIST, or create a
        new one.  This collapses overlapping road segments across routes
        into shared nodes so the graph only branches at real junctions."""
        cs = 0.0001                       # ~11 m grid cell
        cr, cc = int(lat / cs), int(lon / cs)

        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for eid, ex, ey in grid.get((cr + dr, cc + dc), []):
                    if _haversine(lat, lon, ey, ex) <= NODE_MERGE_DIST:
                        return eid        # reuse existing node

        G.add_node(candidate_id, x=lon, y=lat,
                   route_idx=route_idx, progress=progress)
        grid.setdefault((cr, cc), []).append((candidate_id, lon, lat))
        return candidate_id

    def _segment_polyline(self, G, coords, r_idx, merge_grid):
        """Split a polyline into ~seg_len m segments, merging nodes
        that coincide with already-placed nodes from other routes."""
        cum = [0.0]
        for i in range(1, len(coords)):
            d = _haversine(coords[i-1][1], coords[i-1][0],
                           coords[i][1], coords[i][0])
            cum.append(cum[-1] + d)
        total = cum[-1]

        if total < 1:
            nid = self._merge_or_create(
                G, merge_grid, coords[0][0], coords[0][1],
                f"r{r_idx}_0", r_idx, 0.0,
            )
            return [nid], 0.0

        targets: List[float] = []
        t = 0.0
        while t < total:
            targets.append(t)
            t += self.seg_len
        if total - targets[-1] > 1.0:
            targets.append(total)

        nodes: List[str] = []
        seg_j = 0
        for s_idx, tgt in enumerate(targets):
            while seg_j < len(cum) - 2 and cum[seg_j + 1] < tgt:
                seg_j += 1
            leg = cum[seg_j + 1] - cum[seg_j] if seg_j + 1 < len(cum) else 1.0
            frac = max(0.0, min(1.0, (tgt - cum[seg_j]) / max(leg, 1e-10)))
            j2 = min(seg_j + 1, len(coords) - 1)
            lon = coords[seg_j][0] + frac * (coords[j2][0] - coords[seg_j][0])
            lat = coords[seg_j][1] + frac * (coords[j2][1] - coords[seg_j][1])

            nid = self._merge_or_create(
                G, merge_grid, lon, lat,
                f"r{r_idx}_{s_idx}", r_idx, tgt,
            )

            # skip consecutive duplicates created by merging
            if nodes and nodes[-1] == nid:
                continue
            nodes.append(nid)

            if len(nodes) >= 2:
                prev = nodes[-2]
                d = _haversine(G.nodes[prev]["y"], G.nodes[prev]["x"],
                               lat, lon)
                if not G.has_edge(prev, nid):
                    G.add_edge(prev, nid, distance=max(d, 0.1))

        return nodes, total

    # ── edge scoring ──────────────────────────────────────────────────

    def _spatial_index(self, buildings):
        idx: Dict[Tuple[int, int], List[Building]] = {}
        cs = 0.003
        for b in buildings:
            cx, cy = b.get_centroid()
            cell = (int(cy / cs), int(cx / cs))
            idx.setdefault(cell, []).append(b)
        return idx

    def _score_edges(self, G, sun, alpha, bldg_idx, shadow_polys):
        cs = 0.003
        for u, v, data in G.edges(data=True):
            d = data.get("distance", 0)
            ux = G.nodes[u].get("x", 0)
            uy = G.nodes[u].get("y", 0)
            vx = G.nodes[v].get("x", 0)
            vy = G.nodes[v].get("y", 0)
            mlat, mlon = (uy + vy) / 2, (ux + vx) / 2

            exp = self._exposure_at(mlat, mlon, sun, bldg_idx, shadow_polys, cs)
            data["sun_exposure"] = exp
            data["shade_cost"] = d * (1.0 + alpha * exp)

    def _exposure_at(self, lat, lon, sun, bldg_idx, shadow_polys, cs=0.003):
        if not sun.is_daylight or sun.altitude <= 0:
            return 0.0
        cell = (int(lat / cs), int(lon / cs))
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                for b in bldg_idx.get((cell[0] + dx, cell[1] + dy), []):
                    if b.id in shadow_polys:
                        if _point_in_polygon(lon, lat, shadow_polys[b.id]):
                            return 0.0
        return 1.0

    def _point_shaded(self, lat, lon, sun, buildings):
        if not sun.is_daylight or sun.altitude <= 0:
            return True
        for b in buildings:
            poly = self._sc.calculate_shadow_polygon(b, sun)
            if poly and _point_in_polygon(lon, lat, poly):
                return True
        return False

    # ── routing algorithms ────────────────────────────────────────────

    def _h(self, G, u, v):
        """Admissible haversine heuristic for A*."""
        return _haversine(
            G.nodes[u]["y"], G.nodes[u]["x"],
            G.nodes[v]["y"], G.nodes[v]["x"],
        )

    def _yen(self, G, src, tgt, k):
        """Yen's K-shortest simple paths (NetworkX)."""
        try:
            return list(itertools.islice(
                nx.shortest_simple_paths(G, src, tgt, weight="shade_cost"),
                k,
            ))
        except (nx.NetworkXNoPath, nx.NodeNotFound,
                nx.NetworkXNotImplemented):
            return []

    # ── deduplication ─────────────────────────────────────────────────

    def _deduplicate_paths(self, G, paths, keep):
        """Drop paths whose geographic trace overlaps > 70 % with an
        already-kept path.  Returns at most *keep* unique paths."""
        if len(paths) <= 1:
            return paths
        unique = [paths[0]]
        for p in paths[1:]:
            if len(unique) >= keep:
                break
            if not self._is_geo_duplicate(G, p, unique):
                unique.append(p)
        return unique

    def _is_geo_duplicate(self, G, path, existing_paths, threshold=0.70):
        for u in existing_paths:
            shared = len(set(path) & set(u))
            overlap = shared / max(len(path), len(u), 1)
            if overlap > threshold:
                return True
        return False

    @staticmethod
    def _is_valid_path(G, path):
        for i in range(len(path) - 1):
            if not G.has_edge(path[i], path[i + 1]):
                return False
        return True

    # ── route building ────────────────────────────────────────────────

    def _path_to_route(self, G, path, rid, mode, speed, dep):
        coords: List[List[float]] = []
        dist = exp_sum = exp_dist = edges = 0.0

        for node in path:
            x = G.nodes[node].get("x")
            y = G.nodes[node].get("y")
            if x is not None and y is not None:
                if not coords or (
                    abs(x - coords[-1][0]) > 1e-8
                    or abs(y - coords[-1][1]) > 1e-8
                ):
                    coords.append([x, y])

        for i in range(len(path) - 1):
            ed = G[path[i]][path[i + 1]]
            seg_d = ed.get("distance", 0)
            seg_e = ed.get("sun_exposure", 0.5)
            dist += seg_d
            exp_sum += seg_e
            exp_dist += seg_e * seg_d
            edges += 1

        avg_exp = exp_dist / max(dist, 1)
        shade_pct = round((1 - avg_exp) * 100, 1)
        dur_s = dist / speed
        dur_m = round(dur_s / 60)
        sun_min = round(dur_m * avg_exp)

        if shade_pct >= 60:
            risk, rc = "LOW", "#22c55e"
        elif shade_pct >= 30:
            risk, rc = "MEDIUM", "#f59e0b"
        else:
            risk, rc = "HIGH", "#ef4444"

        dk = round(dist / 1000, 1)
        if shade_pct >= 70:
            reason = (f"{dk}km · {dur_m}min · {shade_pct}% shaded – "
                      "excellent building shadow coverage")
        elif shade_pct >= 40:
            reason = (f"{dk}km · {dur_m}min · {shade_pct}% shaded – "
                      "moderate shadow along path")
        else:
            reason = (f"{dk}km · {dur_m}min · {shade_pct}% shaded – "
                      f"limited shade, ~{sun_min}min in direct sun")

        return {
            "route_id": rid,
            "geometry": {"type": "LineString", "coordinates": coords},
            "distance_meters": round(dist, 1),
            "distance_km": dk,
            "duration_seconds": round(dur_s, 1),
            "duration_minutes": dur_m,
            "shade_coverage_pct": shade_pct,
            "sun_exposure_minutes": sun_min,
            "shade_score": round(shade_pct / 100, 3),
            "duration_score": 0.0,
            "final_score": 0.0,
            "label": "",
            "risk_level": risk,
            "risk_color": rc,
            "reason": reason,
        }

    def _rank(self, routes):
        if not routes:
            return

        maxd = max(r["duration_seconds"] for r in routes)
        mind = min(r["duration_seconds"] for r in routes)
        rng = maxd - mind if maxd != mind else 1
        for r in routes:
            ds = 1.0 - (r["duration_seconds"] - mind) / rng
            r["duration_score"] = round(ds, 3)
            r["final_score"] = round(
                (0.75 * r["shade_score"] + 0.25 * ds) * 100, 1,
            )
        routes.sort(key=lambda r: r["final_score"], reverse=True)

        if len(routes) == 1:
            routes[0]["label"] = "Best Route"
            return

        # label based on actual characteristics
        best_shade_idx = max(range(len(routes)),
                            key=lambda i: routes[i]["shade_coverage_pct"])
        shortest_idx = min(range(len(routes)),
                          key=lambda i: routes[i]["duration_seconds"])

        for i, r in enumerate(routes):
            if i == best_shade_idx:
                r["label"] = "Most Shaded"
            elif i == shortest_idx:
                r["label"] = "Shortest"
            else:
                r["label"] = "Balanced"

    # ── building data ─────────────────────────────────────────────────

    def _gather_buildings(self, candidates, client_buildings):
        """Fetch buildings along every Mapbox candidate's actual polyline
        (not just the beeline) so shadow checks cover all the streets
        A* might consider."""
        if client_buildings:
            return client_buildings

        all_b: List[Building] = []
        seen: set = set()
        total_samples = 0

        for route in candidates:
            coords = route["geometry"]["coordinates"]
            # ~8 evenly-spaced samples per route polyline
            step = max(1, len(coords) // 8)
            for i in range(0, len(coords), step):
                lat, lon = coords[i][1], coords[i][0]
                for b in self._fetch_buildings(lat, lon):
                    if b.id not in seen:
                        seen.add(b.id)
                        all_b.append(b)
                total_samples += 1

        print(f"[shade-router] {len(all_b)} buildings from "
              f"{total_samples} corridor samples across "
              f"{len(candidates)} route(s)")
        return all_b

    def _fetch_buildings(self, lat, lon) -> List[Building]:
        ck = f"{round(lat, 3)},{round(lon, 3)}"
        if ck in self._bldg_cache:
            return self._bldg_cache[ck]
        url = (f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/"
               f"tilequery/{lon},{lat}.json")
        params = {
            "radius": BUILDING_FETCH_RADIUS, "layers": "building",
            "limit": 50, "access_token": MAPBOX_TOKEN,
        }
        try:
            r = http_req.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception:
            self._bldg_cache[ck] = []
            return []

        blds: List[Building] = []
        for idx, feat in enumerate(data.get("features", [])):
            geom = feat.get("geometry", {})
            props = feat.get("properties", {})
            gtype = geom.get("type", "")
            if gtype == "Polygon":
                ring = geom.get("coordinates", [[]])[0]
                fp = [(c[0], c[1]) for c in ring]
                if len(fp) < 3:
                    continue
            elif gtype == "Point":
                gc = geom.get("coordinates", [])
                if len(gc) < 2:
                    continue
                cx, cy = gc[0], gc[1]
                s = 0.00015
                fp = [(cx-s, cy-s), (cx+s, cy-s),
                      (cx+s, cy+s), (cx-s, cy+s), (cx-s, cy-s)]
            else:
                continue
            h = max(1.0, float(props.get("height") or DEFAULT_BUILDING_HEIGHT)
                    - float(props.get("min_height") or 0))
            blds.append(Building(
                id=f"b_{ck}_{idx}", footprint=fp,
                height=h, name=props.get("type", "building"),
            ))
        self._bldg_cache[ck] = blds
        return blds

    # ── helpers ───────────────────────────────────────────────────────

    def _resolve_time(self, dt, date_str, minutes):
        if dt:
            return dt
        if date_str and minutes is not None:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            return d.replace(hour=int(minutes) // 60, minute=int(minutes) % 60)
        return datetime.now()

    def _sun(self, dt, lat, lon) -> SunPosition:
        tz = self.TZ
        doy = dt.timetuple().tm_yday
        dec = 23.45 * math.sin(math.radians(360 / 365 * (284 + doy)))
        B = math.radians(360 / 365 * (doy - 81))
        EoT = 9.87 * math.sin(2*B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
        st = dt.hour * 60 + dt.minute + EoT + 4 * (lon - tz * 15)
        ha = st / 4 - 180
        la, de, hr = math.radians(lat), math.radians(dec), math.radians(ha)
        sa = (math.sin(la) * math.sin(de)
              + math.cos(la) * math.cos(de) * math.cos(hr))
        sa = max(-1.0, min(1.0, sa))
        alt = math.degrees(math.asin(sa))
        ca = (math.sin(de) - math.sin(la) * sa) / (
            math.cos(la) * math.cos(math.asin(sa)) + 1e-10
        )
        ca = max(-1.0, min(1.0, ca))
        az = math.degrees(math.acos(ca))
        if ha > 0:
            az = 360 - az
        return SunPosition(
            azimuth=az, altitude=alt,
            zenith=90 - alt, is_daylight=alt > 0,
        )
