import os
import time
import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("MissionLogger")
logging.basicConfig(level=logging.INFO)


class MissionLogger:
    """
    Records continuous mission telemetry (GPS, local odometry, temperature, humidity)
    and detected hazard events (camera snapshots, classification scores, wildfire risk ratings)
    to a dedicated mission session directory.
    """

    def __init__(self, base_dir: str = "missions"):
        # Put missions relative to the terraguard root or current working dir
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

        self.session_id = f"mission_{int(time.time())}"
        self.session_dir = os.path.join(self.base_dir, self.session_id)
        self.photos_dir = os.path.join(self.session_dir, "photos")
        os.makedirs(self.photos_dir, exist_ok=True)

        self.mission_file = os.path.join(self.session_dir, "mission.json")
        self.latest_symlink = os.path.join(self.base_dir, "latest_mission.json")

        self.start_time = time.time()
        self.breadcrumbs: List[Dict[str, Any]] = []
        self.hazards: List[Dict[str, Any]] = []

        self.last_breadcrumb_time: float = 0.0
        self.breadcrumb_interval: float = 1.0  # Log breadcrumb every 1 second while driving

        self._init_mission_file()
        logger.info(f"MissionLogger initialized. Session: {self.session_id} -> {self.session_dir}")

    def _init_mission_file(self):
        """Initializes the mission JSON record."""
        data = {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": None,
            "stats": {
                "total_breadcrumbs": 0,
                "total_hazards": 0,
                "high_risk_count": 0,
                "medium_risk_count": 0,
                "low_risk_count": 0
            },
            "breadcrumbs": [],
            "hazards": []
        }
        self._flush_data(data)

    def _flush_data(self, data: Optional[dict] = None):
        """Writes current mission data to disk."""
        if data is None:
            data = {
                "session_id": self.session_id,
                "start_time": self.start_time,
                "end_time": time.time(),
                "stats": {
                    "total_breadcrumbs": len(self.breadcrumbs),
                    "total_hazards": len(self.hazards),
                    "high_risk_count": sum(1 for h in self.hazards if h.get("final_risk") == "high_risk"),
                    "medium_risk_count": sum(1 for h in self.hazards if h.get("final_risk") == "medium_risk"),
                    "low_risk_count": sum(1 for h in self.hazards if h.get("final_risk") == "low_risk")
                },
                "breadcrumbs": self.breadcrumbs,
                "hazards": self.hazards
            }

        try:
            with open(self.mission_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            # Update pointer to latest mission
            try:
                with open(self.latest_symlink, "w", encoding="utf-8") as f:
                    json.dump({"latest_session_dir": os.path.abspath(self.session_dir), "session_id": self.session_id}, f, indent=2)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to flush mission data: {e}")

    def log_breadcrumb(self,
                       mode: str,
                       x: float,
                       y: float,
                       heading_deg: float,
                       lat: float = 0.0,
                       lng: float = 0.0,
                       has_gps_fix: bool = False,
                       speed_mps: float = 0.0,
                       temp_c: Optional[float] = None,
                       humidity_pct: Optional[float] = None,
                       force: bool = False):
        """Logs a path breadcrumb if interval elapsed or forced."""
        now = time.time()
        if not force and (now - self.last_breadcrumb_time < self.breadcrumb_interval):
            return

        self.last_breadcrumb_time = now

        entry = {
            "timestamp": now,
            "mode": mode,
            "x": round(x, 3),
            "y": round(y, 3),
            "heading_deg": round(heading_deg, 1),
            "lat": round(lat, 7) if has_gps_fix else None,
            "lng": round(lng, 7) if has_gps_fix else None,
            "has_gps_fix": bool(has_gps_fix),
            "speed_mps": round(speed_mps, 2),
            "temp_c": round(temp_c, 1) if temp_c is not None and temp_c > 0.0 else None,
            "humidity_pct": round(humidity_pct, 1) if humidity_pct is not None and humidity_pct > 0.0 else None
        }

        self.breadcrumbs.append(entry)

        # Periodically flush every 10 breadcrumbs
        if len(self.breadcrumbs) % 10 == 0:
            self._flush_data()

    def log_hazard_event(self,
                         direction: str,
                         visual_label: str,
                         confidence: float,
                         final_risk: str,
                         decision: str,
                         x: float,
                         y: float,
                         heading_deg: float,
                         lat: float = 0.0,
                         lng: float = 0.0,
                         has_gps_fix: bool = False,
                         temp_c: Optional[float] = None,
                         humidity_pct: Optional[float] = None,
                         jpeg_bytes: Optional[bytes] = None) -> str:
        """
        Records a detected hazard / scan event and saves the matching camera frame.
        Returns the photo filename.
        """
        now = time.time()
        timestamp_ms = int(now * 1000)
        photo_filename = None

        # Save camera snapshot if frame available
        if jpeg_bytes:
            photo_filename = f"hazard_{timestamp_ms}_{direction.lower()}.jpg"
            photo_path = os.path.join(self.photos_dir, photo_filename)
            try:
                with open(photo_path, "wb") as f:
                    f.write(jpeg_bytes)
                logger.info(f"Saved hazard snapshot: {photo_filename}")
            except Exception as e:
                logger.error(f"Failed to write hazard image: {e}")
                photo_filename = None

        hazard_entry = {
            "timestamp": now,
            "direction": direction.upper(),
            "visual_label": visual_label,
            "confidence": round(confidence, 3),
            "final_risk": final_risk,
            "decision": decision,
            "photo": photo_filename,
            "x": round(x, 3),
            "y": round(y, 3),
            "heading_deg": round(heading_deg, 1),
            "lat": round(lat, 7) if has_gps_fix else None,
            "lng": round(lng, 7) if has_gps_fix else None,
            "has_gps_fix": bool(has_gps_fix),
            "temp_c": round(temp_c, 1) if temp_c is not None and temp_c > 0.0 else None,
            "humidity_pct": round(humidity_pct, 1) if humidity_pct is not None and humidity_pct > 0.0 else None
        }

        self.hazards.append(hazard_entry)
        self._flush_data()
        logger.info(f"Logged Hazard Event: [{final_risk.upper()}] at dir={direction}, x={x:.2f}, y={y:.2f}")

        return photo_filename or ""

    def close(self):
        """Flushes and finalizes mission session."""
        self._flush_data()
        logger.info(f"Mission {self.session_id} finalized. Total breadcrumbs: {len(self.breadcrumbs)}, hazards: {len(self.hazards)}")
