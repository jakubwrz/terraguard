#!/usr/bin/env python3
"""
TerraGuard - Interactive Mission & Wildfire Hazard Map Visualizer
Generates an interactive Leaflet map from rover mission telemetry and hazard logs.
"""

import os
import sys
import json
import glob
import math
import base64
import webbrowser
from typing import Optional, Dict, Any, List


def find_latest_mission(base_dir: str = "missions") -> Optional[str]:
    """Finds the most recent mission directory or mission.json, prioritizing runs with GPS or movement."""
    candidate_bases = [
        base_dir,
        os.path.join("..", base_dir),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", base_dir)
    ]
    for b in candidate_bases:
        if os.path.isdir(b):
            # Scan all mission_* directories
            subdirs = sorted(glob.glob(os.path.join(b, "mission_*")), reverse=True)
            candidate_files = [os.path.join(s, "mission.json") for s in subdirs if os.path.exists(os.path.join(s, "mission.json"))]
            
            # 1. First choice: Recent mission with real GPS fix or hazard records
            for cf in candidate_files:
                try:
                    with open(cf, "r", encoding="utf-8") as f:
                        mdata = json.load(f)
                    has_gps = any(b.get("has_gps_fix") for b in mdata.get("breadcrumbs", []))
                    has_haz = len(mdata.get("hazards", [])) > 0
                    if has_gps or has_haz:
                        return cf
                except Exception:
                    pass
            
            # 2. Second choice: Check latest_mission.json pointer
            pointer = os.path.join(b, "latest_mission.json")
            if os.path.exists(pointer):
                try:
                    with open(pointer, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        sid = data.get("session_id")
                        if sid and os.path.exists(os.path.join(b, sid, "mission.json")):
                            return os.path.join(b, sid, "mission.json")
                        sdir = data.get("latest_session_dir")
                        if sdir and os.path.exists(os.path.join(sdir, "mission.json")):
                            return os.path.join(sdir, "mission.json")
                except Exception:
                    pass

            # 3. Fallback: most recent candidate file
            if candidate_files:
                return candidate_files[0]
    return None


def image_to_base64_uri(image_path: str) -> Optional[str]:
    """Converts a local image file to base64 data URI for standalone HTML embedding."""
    if not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        ext = os.path.splitext(image_path)[1].lower().replace(".", "")
        if ext == "jpg":
            ext = "jpeg"
        return f"data:image/{ext};base64,{encoded}"
    except Exception:
        return None


def haversine_dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS points in meters."""
    R = 6371000.0  # Earth radius in meters
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def generate_map_html(mission_data: dict, mission_dir: str, output_path: str) -> str:
    """Generates the interactive HTML map file."""
    session_id = mission_data.get("session_id", "mission_unknown")
    breadcrumbs = mission_data.get("breadcrumbs", [])
    hazards = list(mission_data.get("hazards", []))

    # Auto-link dataset photos if mission hazards array is empty
    if not hazards:
        start_t = mission_data.get("start_time", 0)
        end_t = mission_data.get("end_time") or (start_t + 7200)
        dataset_dirs = [
            "dataset",
            os.path.join("..", "dataset"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset")
        ]
        for dd in dataset_dirs:
            if os.path.isdir(dd):
                for jf in glob.glob(os.path.join(dd, "*", "photo_*.json")):
                    try:
                        with open(jf, "r", encoding="utf-8") as f:
                            pdata = json.load(f)
                        ts = pdata.get("timestamp", 0)
                        ts_sec = (ts / 1000.0) if ts > 1e11 else float(ts)
                        if (start_t - 60) <= ts_sec <= (end_t + 60):
                            closest_b = min(breadcrumbs, key=lambda b: abs(b.get("timestamp", 0) - ts_sec)) if breadcrumbs else {}
                            img_path = jf.replace(".json", ".jpg")
                            risk = pdata.get("risk_level", "medium_risk")
                            s_data = pdata.get("sensor_data", {})
                            hazards.append({
                                "timestamp": ts_sec,
                                "direction": f"ANGLE_{s_data.get('servo_angle', 0)}",
                                "visual_label": risk.replace("_", " "),
                                "confidence": 0.92,
                                "final_risk": risk,
                                "decision": "BLOCKED" if "high" in risk else ("CAUTION" if "med" in risk else "CLEAR"),
                                "photo": os.path.basename(img_path),
                                "_abs_photo_path": os.path.abspath(img_path),
                                "x": closest_b.get("x", 0.0),
                                "y": closest_b.get("y", 0.0),
                                "heading_deg": closest_b.get("heading_deg", 0.0),
                                "lat": closest_b.get("lat"),
                                "lng": closest_b.get("lng"),
                                "has_gps_fix": closest_b.get("has_gps_fix", False),
                                "temp_c": s_data.get("temperature_c"),
                                "humidity_pct": s_data.get("humidity_pct")
                            })
                    except Exception:
                        pass

    # Filter GPS breadcrumbs to remove cold-lock initial errors and satellite multipath spikes
    raw_gps = [b for b in breadcrumbs if b.get("has_gps_fix") and b.get("lat") and b.get("lng")]
    clean_gps = []
    for i in range(len(raw_gps)):
        pt = raw_gps[i]
        # Drop cold-lock initial jumps (e.g. first fix 450m away before satellite lock)
        if i == 0 and len(raw_gps) > 5:
            avg_next_lat = sum(raw_gps[k]["lat"] for k in range(1, 6)) / 5.0
            avg_next_lng = sum(raw_gps[k]["lng"] for k in range(1, 6)) / 5.0
            if haversine_dist(pt["lat"], pt["lng"], avg_next_lat, avg_next_lng) > 30.0:
                continue
        elif clean_gps:
            prev = clean_gps[-1]
            dist_prev = haversine_dist(prev["lat"], prev["lng"], pt["lat"], pt["lng"])
            dt = abs(pt.get("timestamp", 0) - prev.get("timestamp", 0))
            # If jump > 20m in < 5s, check if next point returns back to prev (single-point spike)
            if dist_prev > 20.0 and dt < 5.0:
                if i + 1 < len(raw_gps):
                    next_pt = raw_gps[i+1]
                    dist_next = haversine_dist(pt["lat"], pt["lng"], next_pt["lat"], next_pt["lng"])
                    dist_prev_to_next = haversine_dist(prev["lat"], prev["lng"], next_pt["lat"], next_pt["lng"])
                    if dist_next > 20.0 and dist_prev_to_next < 15.0:
                        continue
                else:
                    continue
        clean_gps.append(pt)

    gps_breadcrumbs = clean_gps
    has_gps = len(gps_breadcrumbs) > 0

    # Calculate statistics
    total_breadcrumbs = len(breadcrumbs)
    total_hazards = len(hazards)
    high_count = sum(1 for h in hazards if h.get("final_risk") == "high_risk")
    med_count = sum(1 for h in hazards if h.get("final_risk") == "medium_risk")
    low_count = sum(1 for h in hazards if h.get("final_risk") == "low_risk")

    all_temps = [b["temp_c"] for b in breadcrumbs if b.get("temp_c") is not None] + [h["temp_c"] for h in hazards if h.get("temp_c") is not None]
    all_hums = [b["humidity_pct"] for b in breadcrumbs if b.get("humidity_pct") is not None] + [h["humidity_pct"] for h in hazards if h.get("humidity_pct") is not None]
    max_temp = round(max(all_temps), 1) if all_temps else None
    min_hum = round(min(all_hums), 1) if all_hums else None

    # Calculate total path distance (Metric Odometry or GPS Haversine)
    total_dist_m = 0.0
    if has_gps:
        for i in range(1, len(gps_breadcrumbs)):
            d = haversine_dist(
                gps_breadcrumbs[i-1]["lat"], gps_breadcrumbs[i-1]["lng"],
                gps_breadcrumbs[i]["lat"], gps_breadcrumbs[i]["lng"]
            )
            # Filter out GPS jitter while stationary and large jumps
            if 0.6 < d < 50.0:
                total_dist_m += d
    else:
        for i in range(1, len(breadcrumbs)):
            dx = breadcrumbs[i]["x"] - breadcrumbs[i-1]["x"]
            dy = breadcrumbs[i]["y"] - breadcrumbs[i-1]["y"]
            step = math.sqrt(dx**2 + dy**2)
            if step < 10.0:
                total_dist_m += step

    # Embed hazard photos as base64 so map is 100% self-contained
    photos_dir = os.path.join(mission_dir, "photos")
    enriched_hazards = []
    for h in hazards:
        item = dict(h)
        if item.get("temp_c") is not None:
            item["temp_c"] = round(float(item["temp_c"]), 1)
        if item.get("humidity_pct") is not None:
            item["humidity_pct"] = round(float(item["humidity_pct"]), 1)
        pname = h.get("photo")
        if h.get("_abs_photo_path") and os.path.exists(h["_abs_photo_path"]):
            item["photo_b64"] = image_to_base64_uri(h["_abs_photo_path"])
        elif pname:
            ppath = os.path.join(photos_dir, pname)
            item["photo_b64"] = image_to_base64_uri(ppath)
        else:
            item["photo_b64"] = None
        enriched_hazards.append(item)

    # Compute map centers
    if has_gps:
        avg_lat = sum(b["lat"] for b in gps_breadcrumbs) / len(gps_breadcrumbs)
        avg_lng = sum(b["lng"] for b in gps_breadcrumbs) / len(gps_breadcrumbs)
        init_center = [avg_lat, avg_lng]
        init_zoom = 18
    else:
        # Local Cartesian fallback
        init_center = [0, 0]
        init_zoom = 2

    # Serialize data for JavaScript
    js_breadcrumbs = json.dumps(breadcrumbs)
    js_gps_breadcrumbs = json.dumps(gps_breadcrumbs)
    js_hazards = json.dumps(enriched_hazards)
    js_has_gps = "true" if has_gps else "false"
    js_init_center = json.dumps(init_center)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TerraGuard - Mission Map ({session_id})</title>
    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        header {{
            background: #1e293b;
            padding: 12px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #334155;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
            z-index: 1000;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .brand i {{
            font-size: 24px;
            color: #10b981;
        }}
        .brand h1 {{
            font-size: 20px;
            font-weight: 700;
            color: #f8fafc;
            letter-spacing: 0.5px;
        }}
        .brand span {{
            font-size: 13px;
            color: #94a3b8;
            margin-left: 8px;
            background: #334155;
            padding: 2px 8px;
            border-radius: 4px;
        }}
        .stats-bar {{
            display: flex;
            gap: 20px;
            font-size: 13px;
        }}
        .stat-card {{
            background: #0f172a;
            padding: 6px 14px;
            border-radius: 6px;
            border: 1px solid #334155;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .stat-card i {{ color: #38bdf8; }}
        .stat-val {{ font-weight: 700; color: #f8fafc; }}
        .stat-val.high {{ color: #ef4444; }}
        .stat-val.med {{ color: #f59e0b; }}
        .stat-val.low {{ color: #10b981; }}

        #main-container {{
            display: flex;
            flex: 1;
            position: relative;
        }}
        #map {{
            flex: 1;
            height: 100%;
            background: #0b1120;
        }}
        .legend {{
            background: rgba(30, 41, 59, 0.95);
            padding: 14px 16px;
            border-radius: 8px;
            border: 1px solid #475569;
            color: #f8fafc;
            font-size: 12px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5);
            line-height: 1.6;
        }}
        .legend h4 {{ font-size: 13px; margin-bottom: 6px; color: #38bdf8; }}
        .legend-item {{ display: flex; align-items: center; gap: 8px; margin-top: 4px; }}
        .legend-color {{
            width: 14px;
            height: 14px;
            border-radius: 50%;
            display: inline-block;
        }}
        .popup-card {{
            color: #0f172a;
            font-family: inherit;
            max-width: 280px;
        }}
        .popup-header {{
            font-weight: 700;
            font-size: 14px;
            margin-bottom: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .popup-badge {{
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
            text-transform: uppercase;
            font-weight: 700;
        }}
        .badge-high {{ background: #fee2e2; color: #b91c1c; }}
        .badge-med {{ background: #fef3c7; color: #b45309; }}
        .badge-low {{ background: #d1fae5; color: #047857; }}
        .popup-img {{
            width: 100%;
            border-radius: 6px;
            margin: 6px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.15);
            max-height: 160px;
            object-fit: cover;
        }}
        .popup-row {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            margin-top: 4px;
            color: #475569;
        }}
        .popup-row span:last-child {{ font-weight: 600; color: #0f172a; }}
        .gps-alert {{
            background: #b45309;
            color: #fff;
            padding: 4px 12px;
            font-size: 12px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
    </style>
</head>
<body>
    <header>
        <div class="brand">
            <i class="fa-solid fa-shield-halved"></i>
            <h1>TerraGuard</h1>
            <span>{session_id}</span>
            {"" if has_gps else '<div class="gps-alert"><i class="fa-solid fa-triangle-exclamation"></i> Indoor/Local Cartesian Mode (No GPS Lock)</div>'}
        </div>
        <div class="stats-bar">
            <div class="stat-card">
                <i class="fa-solid fa-route"></i>
                <span>Distance:</span>
                <span class="stat-val">{total_dist_m:.1f} m</span>
            </div>
            <div class="stat-card">
                <i class="fa-solid fa-fire"></i>
                <span>Hazards:</span>
                <span class="stat-val high">{high_count} High</span>
                <span class="stat-val med">{med_count} Med</span>
                <span class="stat-val low">{low_count} Low</span>
            </div>
            {f'<div class="stat-card"><i class="fa-solid fa-temperature-high"></i><span>Max Temp:</span><span class="stat-val">{max_temp:.1f}°C</span></div>' if max_temp else ''}
            {f'<div class="stat-card"><i class="fa-solid fa-droplet"></i><span>Min Hum:</span><span class="stat-val">{min_hum:.1f}%</span></div>' if min_hum else ''}
        </div>
    </header>

    <div id="main-container">
        <div id="map"></div>
    </div>

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script>
        const breadcrumbs = {js_breadcrumbs};
        const gpsBreadcrumbs = {js_gps_breadcrumbs};
        const hazards = {js_hazards};
        const hasGps = {js_has_gps};
        const initCenter = {js_init_center};

        let map;

        if (hasGps) {{
            // Real Geographic GPS Map
            map = L.map('map').setView(initCenter, {init_zoom});

            // Street Layer
            const streets = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; OpenStreetMap contributors',
                maxZoom: 22
            }});

            // Satellite Layer (Esri World Imagery)
            const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
                attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
                maxZoom: 20
            }});

            // Add default layer
            satellite.addTo(map);

            L.control.layers({{
                "Satellite View": satellite,
                "Street Map": streets
            }}).addTo(map);

            // Draw GPS Route Polyline (Filtered of cold-lock and multipath teleport glitches)
            const pathCoords = [];
            gpsBreadcrumbs.forEach(b => {{
                if (b.lat && b.lng) {{
                    pathCoords.push([b.lat, b.lng]);
                }}
            }});

            if (pathCoords.length > 0) {{
                const polyline = L.polyline(pathCoords, {{
                    color: '#38bdf8',
                    weight: 4,
                    opacity: 0.85,
                    dashArray: '2, 6'
                }}).addTo(map);

                // Start Marker (Green circle)
                L.circleMarker(pathCoords[0], {{
                    radius: 7,
                    fillColor: '#10b981',
                    color: '#fff',
                    weight: 2,
                    fillOpacity: 1
                }}).bindPopup("<b>🏁 Route Start</b>").addTo(map);

                // Current/End Marker (Blue circle)
                L.circleMarker(pathCoords[pathCoords.length - 1], {{
                    radius: 7,
                    fillColor: '#3b82f6',
                    color: '#fff',
                    weight: 2,
                    fillOpacity: 1
                }}).bindPopup("<b>🛑 Latest Position</b>").addTo(map);

                map.fitBounds(polyline.getBounds(), {{ padding: [40, 40] }});
            }}

            // Add Hazard Event Markers
            hazards.forEach(h => {{
                if (h.lat && h.lng) {{
                    const risk = h.final_risk || 'low_risk';
                    let markerColor = '#10b981';
                    let badgeClass = 'badge-low';
                    if (risk === 'high_risk') {{
                        markerColor = '#ef4444';
                        badgeClass = 'badge-high';
                    }} else if (risk === 'medium_risk') {{
                        markerColor = '#f59e0b';
                        badgeClass = 'badge-med';
                    }}

                    const marker = L.circleMarker([h.lat, h.lng], {{
                        radius: 10,
                        fillColor: markerColor,
                        color: '#fff',
                        weight: 2,
                        fillOpacity: 0.95
                    }}).addTo(map);

                    const imgTag = h.photo_b64 ? `<img src="${{h.photo_b64}}" class="popup-img" alt="Hazard Photo"/>` : '<div style="font-size:11px;color:#94a3b8;margin:6px 0;">(No photo available)</div>';
                    const tempText = (h.temp_c !== null && h.temp_c !== undefined) ? Number(h.temp_c).toFixed(1) + '°C' : 'N/A';
                    const humText = (h.humidity_pct !== null && h.humidity_pct !== undefined) ? Number(h.humidity_pct).toFixed(1) + '%' : 'N/A';
                    const confText = h.confidence ? `${{(h.confidence * 100).toFixed(1)}}%` : 'N/A';

                    marker.bindPopup(`
                        <div class="popup-card">
                            <div class="popup-header">
                                <span>${{h.direction}} Scan</span>
                                <span class="popup-badge ${{badgeClass}}">${{risk.replace('_', ' ')}}</span>
                            </div>
                            ${{imgTag}}
                            <div class="popup-row"><span>Decision:</span><span>${{h.decision || 'N/A'}}</span></div>
                            <div class="popup-row"><span>Visual Model:</span><span>${{h.visual_label}} (${{confText}})</span></div>
                            <div class="popup-row"><span>Ambient Weather:</span><span>🌡️ ${{tempText}} | 💧 ${{humText}}</span></div>
                            <div class="popup-row"><span>Local Pos:</span><span>x=${{h.x}}m, y=${{h.y}}m</span></div>
                            <div class="popup-row"><span>GPS:</span><span>${{h.lat.toFixed(6)}}, ${{h.lng.toFixed(6)}}</span></div>
                        </div>
                    `);
                }}
            }});

        }} else {{
            // Local Cartesian Metric Coordinate Map (Simple CRS)
            map = L.map('map', {{
                crs: L.CRS.Simple,
                minZoom: -3,
                maxZoom: 4
            }}).setView([0, 0], 2);

            // Draw Local Odometry Path (x -> lat, y -> lng mapping for flat plane)
            const localCoords = breadcrumbs.map(b => [b.y, b.x]);

            if (localCoords.length > 0) {{
                const polyline = L.polyline(localCoords, {{
                    color: '#38bdf8',
                    weight: 4,
                    opacity: 0.85
                }}).addTo(map);

                // Start Marker
                L.circleMarker(localCoords[0], {{
                    radius: 7,
                    fillColor: '#10b981',
                    color: '#fff',
                    weight: 2,
                    fillOpacity: 1
                }}).bindPopup("<b>🏁 Route Start (0, 0)</b>").addTo(map);

                // End Marker
                L.circleMarker(localCoords[localCoords.length - 1], {{
                    radius: 7,
                    fillColor: '#3b82f6',
                    color: '#fff',
                    weight: 2,
                    fillOpacity: 1
                }}).bindPopup("<b>🛑 Latest Position</b>").addTo(map);

                map.fitBounds(polyline.getBounds(), {{ padding: [50, 50] }});
            }}

            // Hazard Markers on Cartesian Map
            hazards.forEach(h => {{
                const risk = h.final_risk || 'low_risk';
                let markerColor = '#10b981';
                let badgeClass = 'badge-low';
                if (risk === 'high_risk') {{
                    markerColor = '#ef4444';
                    badgeClass = 'badge-high';
                }} else if (risk === 'medium_risk') {{
                    markerColor = '#f59e0b';
                    badgeClass = 'badge-med';
                }}

                const marker = L.circleMarker([h.y, h.x], {{
                    radius: 10,
                    fillColor: markerColor,
                    color: '#fff',
                    weight: 2,
                    fillOpacity: 0.95
                }}).addTo(map);

                const imgTag = h.photo_b64 ? `<img src="${{h.photo_b64}}" class="popup-img" alt="Hazard Photo"/>` : '<div style="font-size:11px;color:#94a3b8;margin:6px 0;">(No photo available)</div>';
                const tempText = (h.temp_c !== null && h.temp_c !== undefined) ? Number(h.temp_c).toFixed(1) + '°C' : 'N/A';
                const humText = (h.humidity_pct !== null && h.humidity_pct !== undefined) ? Number(h.humidity_pct).toFixed(1) + '%' : 'N/A';
                const confText = h.confidence ? `${{(h.confidence * 100).toFixed(1)}}%` : 'N/A';

                marker.bindPopup(`
                    <div class="popup-card">
                        <div class="popup-header">
                            <span>${{h.direction}} Scan</span>
                            <span class="popup-badge ${{badgeClass}}">${{risk.replace('_', ' ')}}</span>
                        </div>
                        ${{imgTag}}
                        <div class="popup-row"><span>Decision:</span><span>${{h.decision || 'N/A'}}</span></div>
                        <div class="popup-row"><span>Visual Model:</span><span>${{h.visual_label}} (${{confText}})</span></div>
                        <div class="popup-row"><span>Ambient Weather:</span><span>🌡️ ${{tempText}} | 💧 ${{humText}}</span></div>
                        <div class="popup-row"><span>Local Pos:</span><span>x=${{h.x}}m, y=${{h.y}}m</span></div>
                    </div>
                `);
            }});
        }}

        // Add Map Legend
        const legend = L.control({{ position: 'bottomright' }});
        legend.onAdd = function (map) {{
            const div = L.DomUtil.create('div', 'legend');
            div.innerHTML = `
                <h4><i class="fa-solid fa-map-location-dot"></i> Terrain Legend</h4>
                <div class="legend-item"><span class="legend-color" style="background:#ef4444;"></span> High Risk (Blocked/Fire)</div>
                <div class="legend-item"><span class="legend-color" style="background:#f59e0b;"></span> Medium Risk (Caution)</div>
                <div class="legend-item"><span class="legend-color" style="background:#10b981;"></span> Low Risk (Clear)</div>
                <div class="legend-item"><span class="legend-color" style="background:#38bdf8;"></span> Rover Trajectory Path</div>
            `;
            return div;
        }};
        legend.addTo(map);
    </script>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path


def main():
    target_json = None
    if len(sys.argv) > 1:
        target_json = sys.argv[1]
    else:
        target_json = find_latest_mission()

    if not target_json or not os.path.exists(target_json):
        print(f"[!] No valid mission.json found.")
        print(f"    Usage: python visualize_mission.py [path_to_mission.json]")
        sys.exit(1)

    mission_dir = os.path.dirname(os.path.abspath(target_json))
    out_html = os.path.join(mission_dir, "interactive_mission_map.html")

    print(f"[*] Loading mission data: {target_json}")
    with open(target_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"[*] Generating interactive map...")
    generate_map_html(data, mission_dir, out_html)
    print(f"[+] Map successfully generated: {out_html}")

    # Also save a top-level copy at missions/latest_mission_map.html for convenience
    base_missions_dir = os.path.dirname(mission_dir)
    if os.path.basename(base_missions_dir) == "missions":
        top_html = os.path.join(base_missions_dir, "latest_mission_map.html")
        try:
            import shutil
            shutil.copyfile(out_html, top_html)
            print(f"[+] Updated top-level shortcut: {top_html}")
        except Exception:
            pass

    # Launch in default web browser
    try:
        webbrowser.open(f"file://{os.path.abspath(out_html)}")
        print(f"[+] Opened interactive map in browser.")
    except Exception as e:
        print(f"[!] Could not open browser automatically: {e}")


if __name__ == "__main__":
    main()
