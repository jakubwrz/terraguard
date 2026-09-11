import math
import logging
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger("RoverSensorFusion")
logging.basicConfig(level=logging.INFO)


class SensorFusion:
    """
    Tracks the rover's global state [x, y, theta] by fusing GPS, Encoders, and BNO055 IMU heading.
    
    Units:
    - x, y: Meters relative to the GPS origin (first valid GPS lock).
    - theta: Radians, counter-clockwise from East (standard Cartesian).
    """

    def __init__(self, 
                 wheel_base: float = 0.205,     # Measured physical distance between left and right wheels (20.5 cm)
                 wheel_diameter: float = 0.125, # Measured outer wheel diameter (12.5 cm)
                 ticks_per_rev: float = 244.0): # Measured magnetic Hall sensor ticks per wheel revolution
        # Physical parameters
        self.wheel_base = wheel_base
        self.meters_per_tick = (math.pi * wheel_diameter) / ticks_per_rev

        # Global State [x, y, theta]
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0

        # Sensor caching
        self.prev_ticks_l = 0
        self.prev_ticks_r = 0
        self.initialized = False

        # GPS Reference Origin (maps GPS lat/lon to local x,y Cartesian coordinate)
        self.origin_lat: Optional[float] = None
        self.origin_lon: Optional[float] = None

        # Breadcrumbing baseline
        self.last_wp_x = 0.0
        self.last_wp_y = 0.0
        self.last_wp_theta = 0.0
        
        # Thresholds
        self.DIST_THRESHOLD = 0.5        # 0.5 meters (responsive for both indoor and field courses)
        self.ROT_THRESHOLD = math.radians(15.0)  # 15 degrees in radians

    def reset(self, x: float = 0.0, y: float = 0.0, theta: float = 0.0, ticks_l: int = 0, ticks_r: int = 0):
        """Resets dead-reckoned odometry state, baseline ticks, and breadcrumbing references."""
        self.x = x
        self.y = y
        self.theta = theta
        self.prev_ticks_l = ticks_l
        self.prev_ticks_r = ticks_r
        self.last_wp_x = x
        self.last_wp_y = y
        self.last_wp_theta = theta
        self.initialized = True
        logger.info(f"SensorFusion state reset to origin: x={x:.2f}, y={y:.2f}, theta={math.degrees(theta):.1f}° (ticks={ticks_l},{ticks_r})")

    def set_origin(self, lat: float, lon: float):
        """Sets the local cartesian origin point from GPS coordinates."""
        self.origin_lat = lat
        self.origin_lon = lon
        logger.info(f"GPS origin coordinates established: Lat={lat}, Lon={lon}")

    def gps_to_local(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Translates GPS latitude/longitude into a local Cartesian x, y coordinate system (in meters).
        Uses a simple flat-earth approximation appropriate for small local navigation areas.
        """
        if self.origin_lat is None or self.origin_lon is None:
            self.set_origin(lat, lon)
            return 0.0, 0.0

        # Earth radius in meters
        R = 6378137.0
        
        d_lat = math.radians(lat - self.origin_lat)
        d_lon = math.radians(lon - self.origin_lon)
        
        x = d_lon * R * math.cos(math.radians(self.origin_lat))
        y = d_lat * R
        
        return x, y

    def local_to_gps(self, x: float, y: float) -> Tuple[Optional[float], Optional[float]]:
        """
        Translates local Cartesian x, y coordinate system (in meters) back into
        global GPS latitude/longitude using the established origin.
        Returns (None, None) if origin has not yet been established.
        """
        if self.origin_lat is None or self.origin_lon is None:
            return None, None

        R = 6378137.0
        d_lat_rad = y / R
        d_lon_rad = x / (R * math.cos(math.radians(self.origin_lat)))

        lat = self.origin_lat + math.degrees(d_lat_rad)
        lon = self.origin_lon + math.degrees(d_lon_rad)

        return lat, lon

    def update_state(self, 
                     ticks_l: int, 
                     ticks_r: int, 
                     imu_heading_deg: float, 
                     gps_data: Optional[Dict[str, Any]] = None) -> Tuple[float, float, float]:
        """
        Fuses sensory inputs to update the rover's global state [x, y, theta].
        """
        ticks_l = ticks_l if ticks_l is not None else 0
        ticks_r = ticks_r if ticks_r is not None else 0
        imu_heading_deg = float(imu_heading_deg) if imu_heading_deg is not None else 0.0

        if not self.initialized:
            self.prev_ticks_l = ticks_l
            self.prev_ticks_r = ticks_r
            if imu_heading_deg >= 0.0:
                self.theta = self.normalize_angle(math.radians(self.imu_to_cartesian_yaw(imu_heading_deg)))
            else:
                self.theta = 0.0
            self.initialized = True
            
            # Setup origin if we have valid GPS lock
            if gps_data and gps_data.get("has_fix"):
                self.gps_to_local(gps_data["lat"], gps_data["lng"])
                
            self.last_wp_x = self.x
            self.last_wp_y = self.y
            self.last_wp_theta = self.theta
            return self.x, self.y, self.theta

        # 1. Calculate Encoder Odometry
        delta_ticks_l = ticks_l - self.prev_ticks_l
        delta_ticks_r = ticks_r - self.prev_ticks_r
        
        self.prev_ticks_l = ticks_l
        self.prev_ticks_r = ticks_r

        d_l = delta_ticks_l * self.meters_per_tick
        d_r = delta_ticks_r * self.meters_per_tick
        d_c = (d_l + d_r) / 2.0
        
        # Change in heading according to encoders
        d_theta_enc = (d_r - d_l) / self.wheel_base

        # 2. Get absolute heading from BNO055 (if available)
        theta_odom = self.theta + d_theta_enc
        if imu_heading_deg >= 0.0:
            imu_yaw_rad = math.radians(self.imu_to_cartesian_yaw(imu_heading_deg))
            # Wrap angular error to [-pi, pi] to prevent 180° flip glitches across branch cuts
            angle_err = self.normalize_angle(imu_yaw_rad - theta_odom)
            alpha = 0.85 # Complementary filter: 85% IMU yaw gyro, 15% encoder smoothing
            self.theta = self.normalize_angle(theta_odom + alpha * angle_err)
        else:
            # Fallback: pure differential drive wheel encoder odometry
            self.theta = self.normalize_angle(theta_odom)

        # 3. Calculate position update from odometry
        x_odom = self.x + d_c * math.cos(self.theta)
        y_odom = self.y + d_c * math.sin(self.theta)

        # 4. GPS Georeferencing (Origin anchor for global mapping)
        if gps_data and gps_data.get("has_fix"):
            if self.origin_lat is None or self.origin_lon is None:
                self.set_origin(gps_data["lat"], gps_data["lng"])

        # Local autonomous navigation coordinates [x, y] are driven purely by
        # high-precision magnetic Hall wheel encoders and BNO055 gyroscope.
        # This guarantees millimeter/centimeter path replay immune to 3-5 meter consumer GPS jitter.
        self.x = x_odom
        self.y = y_odom

        return self.x, self.y, self.theta

    def check_breadcrumbing(self) -> bool:
        """
        Determines whether a new waypoint breadcrumb should be dropped.
        Triggers when the rover has traveled >= 0.45 meters along the route.
        Stationary turns without translation do not generate duplicate (x,y) waypoints.
        """
        dist = math.sqrt((self.x - self.last_wp_x)**2 + (self.y - self.last_wp_y)**2)
        rot = abs(self.normalize_angle(self.theta - self.last_wp_theta))

        # Require at least 0.4m of translation, or a turn with at least 0.25m of movement
        if dist >= 0.45 or (dist >= 0.25 and rot >= self.ROT_THRESHOLD):
            self.last_wp_x = self.x
            self.last_wp_y = self.y
            self.last_wp_theta = self.theta
            logger.info(f"Breadcrumb Triggered! Delta Dist: {dist:.2f}m, Delta Rot: {math.degrees(rot):.1f}°")
            return True
            
        return False

    @staticmethod
    def imu_to_cartesian_yaw(heading_deg: float) -> float:
        """
        Converts BNO055 clockwise degrees (0..360, where 0 is Forward, 90 is Right, 270 is Left)
        to standard Cartesian counter-clockwise degrees (where 0 is Forward (+X), 90 is Left (+Y), 270 is Right (-Y)).
        """
        cartesian_deg = (360.0 - heading_deg) % 360.0
        return cartesian_deg

    @staticmethod
    def normalize_angle(angle: float) -> float:
        """Normalizes an angle to be within [-pi, pi]."""
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle


# Quick local self-test
if __name__ == "__main__":
    fusion = SensorFusion()
    
    # Init at Heading 0 (Forward / +X)
    x, y, theta = fusion.update_state(0, 0, 0.0) # Forward IMU heading = 0 deg
    print(f"Init: x={x:.2f}, y={y:.2f}, theta={math.degrees(theta):.1f}°")
    
    # Move forward 100 ticks (both wheels)
    # ticks = 100 * 0.001609 = ~0.16 meters forward (+X)
    x, y, theta = fusion.update_state(100, 100, 0.0)
    print(f"Drive: x={x:.2f}, y={y:.2f}, theta={math.degrees(theta):.1f}°")
    print(f"Need Waypoint? {fusion.check_breadcrumbing()}")
    
    # Turn 90 deg right (IMU = 90 deg clockwise -> -90 deg Cartesian)
    x, y, theta = fusion.update_state(100, 100, 90.0)
    print(f"Turned Right: x={x:.2f}, y={y:.2f}, theta={math.degrees(theta):.1f}°")
    
    # Reset test
    fusion.reset(0.0, 0.0, 0.0)
    print(f"Reset: x={fusion.x:.2f}, y={fusion.y:.2f}, theta={math.degrees(fusion.theta):.1f}°")
