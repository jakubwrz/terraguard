import os
import json
import math
import time
import logging
from typing import List, Dict, Tuple, Optional, Any

from mission_logger import MissionLogger

logger = logging.getLogger("RoverStateMachine")
logging.basicConfig(level=logging.INFO)


class RoverStateMachine:
    """
    Coordinates Rover Operational Logic:
    - MODE 1: MANUAL RECORDING (Teach Mode)
      - Receives BLE joystick commands.
      - Drives motors via RPC bridge.
      - Records [x, y, theta] breadcrumbs every 1m or 15 degrees.
      
    - MODE 2: AUTONOMOUS PLAYBACK (Repeat Mode)
      - Navigates through recorded waypoints sequentially.
      - Stop-and-Scan Loop: stop -> pan camera -45, 0, 45 -> run classification.
      - Detours around hazards, then recalculates heading to the current target.
    """

    def __init__(self, bridge: Any, fusion: Any, vision: Any):
        self.bridge = bridge
        self.fusion = fusion
        self.vision = vision
        self.mission_logger = MissionLogger()

        # Mode definitions: "IDLE", "TEACH", "REPEAT"
        # Mode definitions: "IDLE", "TEACH", "WAYPOINTS", "REPEAT"
        self.mode = "IDLE"
        self.waypoints: List[Dict[str, float]] = []
        self.current_wp_index = 0

        # Autonomous navigation sub-states: "DRIVING", "SCANNING", "DETOURING"
        self.nav_state = "DRIVING"
        self.detour_angle: float = 0.0
        self.detour_start_time: float = 0.0
        self.detour_duration: float = 2.0  # seconds to drive in detour direction

        # Scanning results
        self.scan_results = {"left": "CLEAR", "center": "CLEAR", "right": "CLEAR"}

        # Target thresholds
        self.WP_REACHED_RADIUS = 0.4  # meters to count waypoint as reached
        self.ALIGN_ANGLE_TOLERANCE = math.radians(10.0) # 10 degrees

        # Manual control watchdog tracking
        self.last_manual_time: float = 0.0
        self.is_manual_driving: bool = False

        # Environmental sensors cache for wildfire risk fusion
        self.current_temp: Optional[float] = None
        self.current_humidity: Optional[float] = None

        # Camera servo angle tracking and BLE notification handle
        self.current_servo_angle: int = 0
        self.ble_server: Any = None

    def set_mode(self, new_mode: str):
        """Transitions between IDLE, TEACH (Manual), WAYPOINTS (Record Path), and REPEAT (Drive) modes."""
        new_mode = new_mode.upper()
        if new_mode == "DRIVE":
            new_mode = "REPEAT"
        if new_mode == "MANUAL":
            new_mode = "TEACH"

        if new_mode not in ["IDLE", "TEACH", "WAYPOINTS", "REPEAT"]:
            logger.error(f"Invalid mode: {new_mode}")
            return

        prev_mode = self.mode
        logger.info(f"Transitioning mode: {prev_mode} -> {new_mode}")
        self.mode = new_mode
        self.bridge.call("set_motor_speeds", 0, 0) # Safe stop

        # If exiting WAYPOINTS mode, capture final stop position and save route to disk
        if prev_mode == "WAYPOINTS" and new_mode != "WAYPOINTS":
            if self.waypoints:
                final_wp = {"x": round(self.fusion.x, 3), "y": round(self.fusion.y, 3), "theta": round(self.fusion.theta, 3)}
                last_wp = self.waypoints[-1]
                if math.sqrt((final_wp["x"] - last_wp["x"])**2 + (final_wp["y"] - last_wp["y"])**2) > 0.1:
                    self.waypoints.append(final_wp)
                logger.info(f"Route recording completed! Captured {len(self.waypoints)} waypoints.")
                try:
                    os.makedirs("missions", exist_ok=True)
                    with open("missions/latest_route.json", "w") as f:
                        json.dump(self.waypoints, f, indent=2)
                    logger.info("Route waypoints saved to disk: missions/latest_route.json")
                    if self.ble_server:
                        self.ble_server.send_notification(f"💾 Route Saved! {len(self.waypoints)} WPs recorded.")
                except Exception as e:
                    logger.warning(f"Could not persist route: {e}")

        if self.mode == "TEACH":
            logger.info("Teach Mode active. Manual driving & photo capture enabled. Waypoint recording OFF.")
            if self.ble_server:
                self.ble_server.send_notification("📷 Teach Mode Active. Manual driving & risk photos.")
        elif self.mode == "WAYPOINTS":
            self.waypoints.clear()
            self.current_wp_index = 0
            self.bridge.call("reset_encoders")
            self.bridge.call("reset_imu_heading")
            time.sleep(0.05)
            cur_l = self.bridge.call("get_encoder_left") or 0
            cur_r = self.bridge.call("get_encoder_right") or 0
            # Anchor origin waypoint at (0, 0) facing forward (0.0 rad)
            self.fusion.reset(0.0, 0.0, 0.0, ticks_l=cur_l, ticks_r=cur_r)
            self.waypoints.append({"x": 0.0, "y": 0.0, "theta": 0.0})
            logger.info("Waypoints Mode active. Encoders & IMU zeroed. Initial Waypoint #1 dropped at (0, 0). Start driving!")
            if self.ble_server:
                self.ble_server.send_notification("📍 Waypoints Recording Active. Origin (0,0). Drive to record path!")
        elif self.mode == "REPEAT":
            # Auto-restore route from disk if memory is empty
            if not self.waypoints and os.path.exists("missions/latest_route.json"):
                try:
                    with open("missions/latest_route.json", "r") as f:
                        self.waypoints = json.load(f)
                    logger.info(f"Loaded {len(self.waypoints)} waypoints from disk (missions/latest_route.json).")
                except Exception as e:
                    logger.warning(f"Failed loading latest_route.json: {e}")

            # Prune duplicate/stationary waypoints (e.g. repeated stationary rotation at end of route)
            clean_wps = []
            for wp in self.waypoints:
                if not clean_wps:
                    clean_wps.append(wp)
                else:
                    d = math.sqrt((wp["x"] - clean_wps[-1]["x"])**2 + (wp["y"] - clean_wps[-1]["y"])**2)
                    if d >= 0.25 or wp.get("has_photo"):
                        clean_wps.append(wp)
            self.waypoints = clean_wps

            if len(self.waypoints) < 2:
                logger.warning(f"Insufficient waypoints ({len(self.waypoints)}) for autonomous playback!")
                if self.ble_server:
                    self.ble_server.send_notification("⚠️ No route recorded! Drive in Teach/Waypoints first.")
                self.set_mode("IDLE")
                return

            self.current_wp_index = 0
            self.nav_state = "DRIVING"
            self.bridge.call("reset_encoders")
            self.bridge.call("reset_imu_heading")
            time.sleep(0.05)
            cur_l = self.bridge.call("get_encoder_left") or 0
            cur_r = self.bridge.call("get_encoder_right") or 0
            self.fusion.reset(0.0, 0.0, 0.0, ticks_l=cur_l, ticks_r=cur_r)
            logger.info(f"Drive / Repeat Mode active. Origin zeroed. Route ready with {len(self.waypoints)} clean waypoints.")
            if self.ble_server:
                self.ble_server.send_notification(f"🤖 Autonomous Drive Started! {len(self.waypoints)} WPs queued.")

    def query_full_telemetry(self) -> dict:
        """Queries full sensor telemetry from STM32 with safe fallbacks."""
        raw_l = self.bridge.call("get_encoder_left")
        raw_r = self.bridge.call("get_encoder_right")
        raw_fl = self.bridge.call("get_encoder_fl")
        raw_fr = self.bridge.call("get_encoder_fr")
        raw_rl = self.bridge.call("get_encoder_rl")
        raw_rr = self.bridge.call("get_encoder_rr")
        raw_head = self.bridge.call("get_imu_heading")
        raw_t = self.bridge.call("get_temperature")
        raw_h = self.bridge.call("get_humidity")

        return {
            "temperature_c": round(float(raw_t), 1) if raw_t is not None else None,
            "humidity_pct": round(float(raw_h), 1) if raw_h is not None else None,
            "heading": float(raw_head) if raw_head is not None else 0.0,
            "gps": {
                "lat": float(self.bridge.call("get_gps_lat") or 0.0),
                "lng": float(self.bridge.call("get_gps_lng") or 0.0),
                "has_fix": bool(self.bridge.call("get_gps_has_fix") or False),
                "speed": float(self.bridge.call("get_gps_speed") or 0.0)
            },
            "spectral": {
                "F1_415nm": self.bridge.call("get_spectral_f1"),
                "F2_445nm": self.bridge.call("get_spectral_f2"),
                "F3_480nm": self.bridge.call("get_spectral_f3"),
                "F4_515nm": self.bridge.call("get_spectral_f4"),
                "F5_555nm": self.bridge.call("get_spectral_f5"),
                "F6_590nm": self.bridge.call("get_spectral_f6"),
                "F7_630nm": self.bridge.call("get_spectral_f7"),
                "F8_680nm": self.bridge.call("get_spectral_f8"),
                "Clear": self.bridge.call("get_spectral_clear"),
                "NIR": self.bridge.call("get_spectral_nir")
            },
            "encoders": {
                "fl": int(raw_fl) if raw_fl is not None else 0,
                "fr": int(raw_fr) if raw_fr is not None else 0,
                "rl": int(raw_rl) if raw_rl is not None else 0,
                "rr": int(raw_rr) if raw_rr is not None else 0,
                "left_avg": int(raw_l) if raw_l is not None else 0,
                "right_avg": int(raw_r) if raw_r is not None else 0
            }
        }

    def handle_manual_command(self, cmd: str):
        """Processes manual control inputs from smartphone BLE in TEACH/WAYPOINTS/IDLE modes."""
        if self.mode == "REPEAT":
            logger.warning("Ignoring manual command. Rover is in AUTONOMOUS DRIVE mode.")
            return

        # Directional mapping to motor speeds (Left, Right)
        speed_map = {
            'F': (220, 220),   # Forward
            'B': (-220, -220), # Backward
            'L': (70, 220),    # Smooth Left Arc
            'R': (220, 70),    # Smooth Right Arc
            'S': (0, 0)        # Stop
        }

        # Handle Training Image Captures / Waypoint Photo Observations
        if cmd.startswith("P_"):
            risk_map = {
                "P_LOW": "low_risk",
                "P_MED": "medium_risk",
                "P_HIGH": "high_risk"
            }
            risk_level = risk_map.get(cmd)
            if risk_level:
                # 1. STOP motors immediately so photo is 100% stable with zero motion blur!
                self.bridge.call("set_motor_speeds", 0, 0)
                time.sleep(0.4) # Wait for chassis motion to settle

                # 1. Fetch camera frame once (prevents ESP32 HTTP connection reset/drop)
                frame = self.vision.fetch_single_frame()

                telem = self.query_full_telemetry()
                sensor_data = {
                    "temperature_c": telem["temperature_c"],
                    "humidity_pct": telem["humidity_pct"],
                    "spectral": telem["spectral"],
                    "encoders": telem["encoders"],
                    "servo_angle": self.current_servo_angle,
                    "fused_position": {
                        "x": self.fusion.x,
                        "y": self.fusion.y,
                        "theta": self.fusion.theta
                    }
                }
                # 2. Save training photo using the already fetched frame
                self.vision.save_training_photo(risk_level, sensor_data=sensor_data, frame_bytes=frame)

                # 3. Run ONNX AI prediction
                decision = (
                    self.vision.classify_frame(frame, temp_c=telem["temperature_c"], humidity_pct=telem["humidity_pct"])
                    if frame else "CLEAR"
                )
                assessment = getattr(self.vision, "last_assessment", {})
                detected_risk = assessment.get("final_risk", risk_level)
                confidence = assessment.get("confidence", 1.0)

                # Send real-time risk alert to smartphone app console!
                icon = "🔥" if "high" in detected_risk else ("⚠️" if "med" in detected_risk else "🌿")
                alert_msg = f"{icon} [AI RISK] {detected_risk.upper().replace('_', ' ')} ({int(confidence*100)}%) | Servo: {self.current_servo_angle}°"
                logger.info(alert_msg)
                if self.ble_server:
                    self.ble_server.send_notification(alert_msg)

                # If currently recording waypoints, record an Observation Waypoint with memorized servo angle!
                if self.mode == "WAYPOINTS":
                    wp = {
                        "x": round(self.fusion.x, 3),
                        "y": round(self.fusion.y, 3),
                        "theta": round(self.fusion.theta, 3),
                        "servo_angle": self.current_servo_angle,
                        "has_photo": True,
                        "expected_risk": risk_level
                    }
                    self.waypoints.append(wp)
                    logger.info(f"Recorded Photo Waypoint #{len(self.waypoints)} at ({self.fusion.x:.2f}, {self.fusion.y:.2f}) with Servo Angle {self.current_servo_angle}°")

                # Also log as a landmark event in the mission telemetry database
                est_lat, est_lng = telem["gps"]["lat"], telem["gps"]["lng"]
                if not telem["gps"]["has_fix"] and hasattr(self.fusion, "local_to_gps"):
                    l_lat, l_lng = self.fusion.local_to_gps(self.fusion.x, self.fusion.y)
                    if l_lat is not None:
                        est_lat, est_lng = l_lat, l_lng

                self.mission_logger.log_hazard_event(
                    direction=f"ANGLE_{self.current_servo_angle}",
                    visual_label=assessment.get("visual_label", risk_level),
                    confidence=confidence,
                    final_risk=detected_risk,
                    decision=decision,
                    x=self.fusion.x,
                    y=self.fusion.y,
                    heading_deg=math.degrees(self.fusion.theta) % 360.0,
                    lat=est_lat or 0.0,
                    lng=est_lng or 0.0,
                    has_gps_fix=bool(telem["gps"]["has_fix"] or (est_lat != 0.0 and est_lat is not None)),
                    temp_c=telem["temperature_c"],
                    humidity_pct=telem["humidity_pct"],
                    jpeg_bytes=frame
                )
            return

        # Handle Camera Pan Commands (Memorize current servo angle)
        if cmd.startswith("CAM_"):
            cam_map = {
                "CAM_L": -60, # Max Left (-60°)
                "CAM_C": 0,   # Center (0°)
                "CAM_R": 60   # Max Right (+60°)
            }
            angle = cam_map.get(cmd)
            if angle is not None:
                self.current_servo_angle = angle
                self.bridge.call("pan_servo", angle)
            return

        if cmd.startswith("SERVO:"):
            try:
                angle = int(cmd.split(":")[1])
                self.current_servo_angle = angle
                self.bridge.call("pan_servo", angle)
            except Exception as e:
                logger.error(f"Invalid SERVO command string {cmd}: {e}")
            return

        # Handle Analog Joystick Proportional Steering: "JOY:x,y" (x, y range: -100 to 100)
        if cmd.startswith("JOY:"):
            try:
                parts = cmd[4:].split(",")
                joy_x = float(parts[0]) / 100.0  # Steering: -1.0 (full left) to +1.0 (full right)
                joy_y = float(parts[1]) / 100.0  # Throttle: -1.0 (full back) to +1.0 (full forward)

                # Progressive Curvature Steering: Inside wheel slows down, outside wheel pushes forward
                if abs(joy_y) > 0.05:
                    if joy_x >= 0:
                        # Turning Right: Left (outer) full power, Right (inner) scales down
                        left_factor = 1.0
                        right_factor = 1.0 - (1.6 * joy_x)
                    else:
                        # Turning Left: Right (outer) full power, Left (inner) scales down
                        right_factor = 1.0
                        left_factor = 1.0 - (1.6 * abs(joy_x))

                    raw_left = joy_y * left_factor * 230.0
                    raw_right = joy_y * right_factor * 230.0
                else:
                    # Stationary Turning: Outer wheel drives forward, inner wheel assists gently
                    if joy_x > 0:  # Turn Right
                        raw_left = joy_x * 200.0
                        raw_right = joy_x * -50.0
                    elif joy_x < 0:  # Turn Left
                        raw_right = abs(joy_x) * 200.0
                        raw_left = abs(joy_x) * -50.0
                    else:
                        raw_left, raw_right = 0.0, 0.0

                l_speed = int(max(-255, min(255, raw_left)))
                r_speed = int(max(-255, min(255, raw_right)))

                self.bridge.call("set_motor_speeds", l_speed, r_speed)
                return
            except Exception as e:
                logger.error(f"Invalid JOY command format '{cmd}': {e}")
                return

        # Handle Direction Commands (Discrete fallback)
        if cmd in speed_map:
            l_speed, r_speed = speed_map[cmd]
            self.bridge.call("set_motor_speeds", l_speed, r_speed)
        else:
            logger.warning(f"Unknown manual control string: {cmd}")

    def update_telemetry(self):
        """Queries telemetry from STM32 and updates the sensor fusion coordinate state."""
        try:
            raw_l = self.bridge.call("get_encoder_left")
            raw_r = self.bridge.call("get_encoder_right")
            raw_head = self.bridge.call("get_imu_heading")

            ticks_l = int(raw_l) if raw_l is not None else 0
            ticks_r = int(raw_r) if raw_r is not None else 0
            heading = float(raw_head) if raw_head is not None else 0.0

            raw_lat = self.bridge.call("get_gps_lat")
            raw_lng = self.bridge.call("get_gps_lng")
            raw_fix = self.bridge.call("get_gps_has_fix")
            raw_spd = self.bridge.call("get_gps_speed")

            # Periodically refresh ambient environment (Temperature & Humidity)
            raw_temp = self.bridge.call("get_temperature")
            raw_hum = self.bridge.call("get_humidity")
            if raw_temp is not None:
                self.current_temp = round(float(raw_temp), 1)
            if raw_hum is not None:
                self.current_humidity = round(float(raw_hum), 1)

            gps_data = {
                "lat": float(raw_lat or 0.0),
                "lng": float(raw_lng or 0.0),
                "has_fix": bool(raw_fix or False),
                "speed": float(raw_spd or 0.0)
            }

            # Update Fusion
            x, y, theta = self.fusion.update_state(ticks_l, ticks_r, heading, gps_data)
            
            # Compute current best GPS estimate (direct fix or odometry projection)
            est_lat = gps_data["lat"]
            est_lng = gps_data["lng"]
            has_fix = gps_data["has_fix"]
            if not has_fix and hasattr(self.fusion, "local_to_gps"):
                calc_lat, calc_lng = self.fusion.local_to_gps(x, y)
                if calc_lat is not None:
                    est_lat, est_lng = calc_lat, calc_lng

            # Always record mission telemetry breadcrumbs
            heading_deg = math.degrees(theta) % 360.0
            self.mission_logger.log_breadcrumb(
                mode=self.mode,
                x=x,
                y=y,
                heading_deg=heading_deg,
                lat=est_lat or 0.0,
                lng=est_lng or 0.0,
                has_gps_fix=bool(has_fix or (est_lat != 0.0 and est_lat is not None)),
                speed_mps=gps_data["speed"],
                temp_c=self.current_temp,
                humidity_pct=self.current_humidity
            )

            # Drop breadcrumb only in WAYPOINTS Mode
            if self.mode == "WAYPOINTS":
                if self.fusion.check_breadcrumbing():
                    wp = {"x": round(x, 3), "y": round(y, 3), "theta": round(theta, 3)}
                    self.waypoints.append(wp)
                    logger.info(f"Dropped breadcrumb Waypoint #{len(self.waypoints)}: x={x:.2f}, y={y:.2f}")
                    if self.ble_server and len(self.waypoints) % 5 == 0:
                        self.ble_server.send_notification(f"📍 Recorded WP #{len(self.waypoints)} ({x:.1f}m, {y:.1f}m)")
                    
        except Exception as e:
            logger.error(f"Error updating telemetry: {e}")

    # --- AUTONOMOUS REPEAT MODE NAVIGATION ---
    def execute_repeat_step(self):
        """
        Executes a single step of the autonomous navigation playback.
        This is called periodically in the main loop while mode == 'REPEAT'.
        """
        if not self.waypoints:
            logger.warning("No waypoints recorded! Aborting playback.")
            if self.ble_server:
                self.ble_server.send_notification("⚠️ No waypoints recorded! Record a route first.")
            self.set_mode("IDLE")
            return

        if self.current_wp_index >= len(self.waypoints):
            logger.info("SUCCESS! Final waypoint reached. Path completed.")
            self.bridge.call("set_motor_speeds", 0, 0)
            if self.ble_server:
                self.ble_server.send_notification("🏁 Autonomous Route Completed!")
            self.set_mode("IDLE")
            return

        target_wp = self.waypoints[self.current_wp_index]
        
        # Calculate current distance to target waypoint
        dx = target_wp["x"] - self.fusion.x
        dy = target_wp["y"] - self.fusion.y
        distance_to_wp = math.sqrt(dx**2 + dy**2)

        # 1. Waypoint reached criteria:
        # - Within 0.45m of target, OR
        # - For non-photo waypoints, if already closer to next waypoint (smooth corner cutting)
        is_reached = (distance_to_wp < 0.45)
        if not is_reached and not target_wp.get("has_photo") and (self.current_wp_index + 1 < len(self.waypoints)):
            next_wp = self.waypoints[self.current_wp_index + 1]
            dist_to_next = math.sqrt((next_wp["x"] - self.fusion.x)**2 + (next_wp["y"] - self.fusion.y)**2)
            wp_sep = math.sqrt((next_wp["x"] - target_wp["x"])**2 + (next_wp["y"] - target_wp["y"])**2)
            if dist_to_next < distance_to_wp and dist_to_next < (wp_sep + 0.35):
                is_reached = True

        if is_reached:
            logger.info(f"Reached Waypoint #{self.current_wp_index + 1}/{len(self.waypoints)}: Target was ({target_wp['x']:.2f}, {target_wp['y']:.2f})")
            
            # --- BLUR-FREE PHOTO REPLAY WITH MEMORIZED SERVO ANGLE ---
            if target_wp.get("has_photo"):
                # 1. Stop rover motors immediately for zero motion blur
                self.bridge.call("set_motor_speeds", 0, 0)
                
                # 2. Point camera at the EXACT memorized servo angle (NO sweeping left/right!)
                photo_angle = int(target_wp.get("servo_angle", 0))
                logger.info(f"Aiming camera to memorized angle: {photo_angle}° (zero sweep)")
                self.bridge.call("pan_servo", photo_angle)
                
                # 3. Wait for vibration & servo motion to settle completely
                time.sleep(0.8)
                
                # 4. Capture camera frame & run ONNX AI risk assessment
                frame = self.vision.fetch_single_frame()
                decision = (
                    self.vision.classify_frame(frame, temp_c=self.current_temp, humidity_pct=self.current_humidity)
                    if frame else "CLEAR"
                )
                assessment = getattr(self.vision, "last_assessment", {})
                detected_risk = assessment.get("final_risk", target_wp.get("expected_risk", "low_risk"))
                confidence = float(assessment.get("confidence", 1.0))
                
                # 5. Output live risk assessment directly to the app console!
                icon = "🔥" if "high" in detected_risk else ("⚠️" if "med" in detected_risk else "🌿")
                alert_msg = f"{icon} [AUTO AI] WP #{self.current_wp_index + 1}: {detected_risk.upper().replace('_', ' ')} ({int(confidence * 100)}%) | Angle: {photo_angle}°"
                logger.info(alert_msg)
                if self.ble_server:
                    self.ble_server.send_notification(alert_msg)
                
                # 6. Log hazard snapshot and sensor telemetry to mission database
                est_lat, est_lng = None, None
                if hasattr(self.fusion, "local_to_gps"):
                    est_lat, est_lng = self.fusion.local_to_gps(self.fusion.x, self.fusion.y)
                self.mission_logger.log_hazard_event(
                    direction=f"ANGLE_{photo_angle}",
                    visual_label=assessment.get("visual_label", "clear"),
                    confidence=confidence,
                    final_risk=detected_risk,
                    decision=decision,
                    x=self.fusion.x,
                    y=self.fusion.y,
                    heading_deg=math.degrees(self.fusion.theta) % 360.0,
                    lat=est_lat or 0.0,
                    lng=est_lng or 0.0,
                    has_gps_fix=bool(est_lat is not None and est_lat != 0.0),
                    temp_c=self.current_temp,
                    humidity_pct=self.current_humidity,
                    jpeg_bytes=frame
                )
                
                # 7. Re-center camera servo forward for driving
                self.bridge.call("pan_servo", 0)
                time.sleep(0.3)

            # Advance to next waypoint
            self.current_wp_index += 1
            if self.current_wp_index >= len(self.waypoints):
                logger.info("SUCCESS! Final waypoint reached. Path completed.")
                self.bridge.call("set_motor_speeds", 0, 0)
                if self.ble_server:
                    self.ble_server.send_notification("🏁 Autonomous Route Completed!")
                self.set_mode("IDLE")
                return

            # Retarget next waypoint
            target_wp = self.waypoints[self.current_wp_index]
            dx = target_wp["x"] - self.fusion.x
            dy = target_wp["y"] - self.fusion.y
            distance_to_wp = math.sqrt(dx**2 + dy**2)

        # 2. Drive smoothly towards current waypoint
        target_yaw = math.atan2(dy, dx)
        yaw_error = self.fusion.normalize_angle(target_yaw - self.fusion.theta)
        self._drive_towards_heading(yaw_error, distance_to_wp)

    def _drive_towards_heading(self, yaw_error: float, distance: float = 1.0):
        """
        Continuous smooth trajectory steering without violent oscillating or spinning.
        Only pivots in place if the target is significantly behind (> 75° / 1.3 rad).
        Otherwise, drives continuously forward with progressive proportional differential steering.
        """
        base_speed = 180

        # Only pivot in place if severely misaligned (> 75° / 1.3 rad) AND not right on top of waypoint
        if abs(yaw_error) > 1.3 and distance > 0.35:
            # Controlled pivot speed with no jerk (120-145 PWM)
            pivot_spd = int(120 + min(25, abs(yaw_error) * 15))
            if yaw_error > 0:
                # Pivot Left (Counter-Clockwise)
                self.bridge.call("set_motor_speeds", -pivot_spd, pivot_spd)
            else:
                # Pivot Right (Clockwise)
                self.bridge.call("set_motor_speeds", pivot_spd, -pivot_spd)
            return

        # Continuous forward differential steering:
        # Both wheels roll forward smoothly, steering gently towards target!
        kp = 90.0
        steer = int(kp * yaw_error) # positive yaw_error means target is to left -> left slows, right speeds
        steer = max(-100, min(100, steer))

        l_spd = max(50, min(230, base_speed - steer))
        r_spd = max(50, min(230, base_speed + steer))

        self.bridge.call("set_motor_speeds", l_spd, r_spd)

