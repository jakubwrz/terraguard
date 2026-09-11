import os
import time
import logging
from typing import Dict, Any

from sensor_fusion import SensorFusion
from vision import RoverVision
from ble_server import RoverBLEServer
from state_machine import RoverStateMachine

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("RoverMain")

import socket
import threading

# MessagePack is used by the Arduino Uno Q router daemon
try:
    import msgpack
    HAS_MSGPACK = True
except ImportError:
    HAS_MSGPACK = False

class SocketRouterBridge:
    """
    Direct MessagePack RPC client communicating directly with the Arduino Uno Q
    hardware router daemon at /var/run/arduino-router.sock.
    """
    def __init__(self, socket_path="/var/run/arduino-router.sock"):
        self.socket_path = socket_path
        self.msg_id = 0
        self.lock = threading.Lock()
        self.sock = None
        self._connect()

    def _connect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(1.0)
            self.sock.connect(self.socket_path)
            logger.info(f"Connected to Arduino Router socket at {self.socket_path}. Real hardware active!")
        except Exception as e:
            logger.warning(f"Could not connect to {self.socket_path}: {e}")
            self.sock = None

    def call(self, method_name: str, *args) -> Any:
        if not self.sock:
            self._connect()
            if not self.sock:
                return None

        with self.lock:
            try:
                self.msg_id = (self.msg_id + 1) & 0xFFFFFFFF
                current_id = self.msg_id
                # MessagePack RPC request: [type=0 (Request), msg_id, method_name, [params...]]
                request = [0, current_id, method_name, list(args)]
                packed = msgpack.packb(request)
                self.sock.sendall(packed)

                # Receive response — handle stale/mismatched responses by
                # draining up to 3 messages looking for our msg_id
                unpacker = msgpack.Unpacker(raw=False)
                for _attempt in range(3):
                    response_data = self.sock.recv(4096)
                    if not response_data:
                        self.sock = None
                        return None

                    unpacker.feed(response_data)
                    for response in unpacker:
                        # MessagePack RPC response: [type=1 (Response), msg_id, error, result]
                        if isinstance(response, list) and len(response) >= 4:
                            if response[1] == current_id:
                                err = response[2]
                                result = response[3]
                                if err:
                                    logger.debug(f"RPC error on '{method_name}': {err}")
                                    return None
                                return result
                            # Stale response from previous call — discard and read again

                return None
            except socket.timeout:
                # Timeout means the bridge is stuck — reconnect to clear stale data
                logger.debug(f"RPC timeout on '{method_name}', reconnecting socket")
                self._connect()
                return None
            except Exception as e:
                logger.warning(f"Socket RPC issue on '{method_name}': {e}")
                self._connect()
                return None

# Try to load official App Lab bridge, then fallback to SocketRouterBridge, then MockBridge
HAS_ARDUINO_BRIDGE = False
try:
    from arduino.app_utils import App, Bridge
    HAS_ARDUINO_BRIDGE = True
    logger.info("Arduino App Lab bridge utilities loaded successfully.")
except ImportError:
    pass


class MockBridge:
    """
    Simulates the RPC Bridge for testing code execution on standard computers.
    Tracks state and returns dummy values for IMU, GPS, and Encoder readings.
    """
    def __init__(self):
        self.left_speed = 0
        self.right_speed = 0
        self.servo_angle = 0
        
        # Sim values
        self.sim_encoder_l = 0
        self.sim_encoder_r = 0
        self.sim_yaw = 90.0 # Starts facing North (90° clockwise = East in IMU scale)
        self.sim_lat = 52.2297  # Example coordinates (Warsaw)
        self.sim_lng = 21.0122
        self.sim_gps_fix = True
        self.sim_gps_speed = 0.0

    def call(self, method_name: str, *args) -> Any:
        """Emulates the Arduino Bridge.call(method, *args) RPC framework."""
        if method_name == "set_motor_speeds":
            self.left_speed, self.right_speed = args
            logger.info(f"[SIM MOTOR] PWM Command: Left={self.left_speed}, Right={self.right_speed}")
            return None
            
        elif method_name == "pan_servo":
            self.servo_angle = args[0]
            logger.info(f"[SIM SERVO] Pan Servo to: {self.servo_angle}°")
            return None
            
        elif method_name == "get_encoder_left":
            # Simulate encoder tick accumulation based on speed
            self.sim_encoder_l += int(self.left_speed * 0.05)
            return self.sim_encoder_l
            
        elif method_name == "get_encoder_right":
            self.sim_encoder_r += int(self.right_speed * 0.05)
            return self.sim_encoder_r
            
        elif method_name == "get_encoder_fl":
            return self.sim_encoder_l
            
        elif method_name == "get_encoder_fr":
            return self.sim_encoder_r
            
        elif method_name == "get_encoder_rl":
            return self.sim_encoder_l
            
        elif method_name == "get_encoder_rr":
            return self.sim_encoder_r
            
        elif method_name == "reset_encoders":
            self.sim_encoder_l = 0
            self.sim_encoder_r = 0
            logger.info("[SIM TELEMETRY] Encoders reset.")
            return None

        elif method_name == "reset_imu_heading":
            self.sim_yaw = 0.0
            logger.info("[SIM TELEMETRY] IMU Heading reset to 0.0°.")
            return None
            
        elif method_name == "get_imu_heading":
            # Simulate slight turn drift based on differential motor speed
            diff = self.left_speed - self.right_speed
            self.sim_yaw = (self.sim_yaw + diff * 0.02) % 360.0
            return self.sim_yaw
            
        elif method_name == "get_gps_lat":
            # Simulate moving coordinate based on speeds
            avg_speed = (self.left_speed + self.right_speed) / 2.0
            self.sim_lat += (avg_speed * 0.0000001)
            return self.sim_lat
            
        elif method_name == "get_gps_lng":
            avg_speed = (self.left_speed + self.right_speed) / 2.0
            self.sim_lng += (avg_speed * 0.0000001)
            return self.sim_lng
            
        elif method_name == "get_gps_has_fix":
            return self.sim_gps_fix
            
        elif method_name == "get_gps_speed":
            avg_speed = (self.left_speed + self.right_speed) / 2.0
            self.sim_gps_speed = abs(avg_speed) * 0.005
            return self.sim_gps_speed

        elif method_name == "get_temperature":
            return 24.5 # Simulated 24.5 °C
            
        elif method_name == "get_humidity":
            return 52.0 # Simulated 52.0 % RH
            
        elif method_name.startswith("get_spectral_"):
            if "clear" in method_name:
                return 1200
            elif "nir" in method_name:
                return 80
            else:
                return 250 # Mock value for spectral channels F1-F8

        elif method_name == "get_telemetry_json":
            import json
            mock_data = {
                "fl": self.sim_encoder_l,
                "fr": self.sim_encoder_r,
                "rl": self.sim_encoder_l,
                "rr": self.sim_encoder_r,
                "temp": 24.5,
                "hum": 52.0,
                "heading": self.sim_yaw,
                "lat": self.sim_lat,
                "lng": self.sim_lng,
                "fix": 1 if self.sim_gps_fix else 0,
                "spd": self.sim_gps_speed,
                "f1": 250, "f2": 255, "f3": 260, "f4": 270,
                "f5": 280, "f6": 290, "f7": 300, "f8": 310,
                "clr": 1200, "nir": 80
            }
            return json.dumps(mock_data)
            
        else:
            logger.warning(f"MockBridge: Unknown RPC method requested: {method_name}")
            return None


def main():
    logger.info("==========================================================")
    logger.info("  TerraGuard Rover v2.2 - Audited Safe + LED Matrix Active")
    logger.info("==========================================================")

    # 1. Initialize core hardware connection bridge
    if HAS_ARDUINO_BRIDGE:
        bridge = Bridge
        logger.info("Using official Arduino App Lab Bridge.")
    elif os.path.exists("/var/run/arduino-router.sock") and HAS_MSGPACK:
        bridge = SocketRouterBridge()
        logger.info("Using direct Arduino Router Socket Bridge (/var/run/arduino-router.sock).")
    else:
        bridge = MockBridge()
        logger.warning("No hardware bridge found. Starting in SIMULATION/MOCK mode.")

    # 2. Instantiate helper subsystems
    fusion = SensorFusion()
    vision = RoverVision(camera_ip="192.168.4.1") # Connects to XIAO ESP32S3 Access Point IP
    state_machine = RoverStateMachine(bridge, fusion, vision)

    # 3. Define BLE Command Receiver Callback
    def ble_cmd_handler(cmd: str):
        """Processes all commands incoming from the BLE Smartphone interface."""
        # Check Mode Selection Commands
        if cmd == "MODE_TEACH":
            state_machine.set_mode("TEACH")
        elif cmd == "MODE_WAYPOINTS":
            state_machine.set_mode("WAYPOINTS")
        elif cmd in ["MODE_REPEAT", "MODE_DRIVE"]:
            state_machine.set_mode("REPEAT")
        elif cmd == "MODE_IDLE":
            state_machine.set_mode("IDLE")
        else:
            # Pass direction & photo capture triggers to state machine
            state_machine.handle_manual_command(cmd)

    # 4. Start the BLE Command Server (peripheral)
    ble_server = RoverBLEServer(name="TerraGuardRover", command_callback=ble_cmd_handler)
    state_machine.ble_server = ble_server
    ble_server.start()
    logger.info("BLE controller server listening for connection...")

    # Set default starting mode
    state_machine.set_mode("IDLE")

    # Time tracking for execution loops
    last_telemetry_time = time.time()
    last_repeat_time = time.time()

    # 5. Execute core application loop
    try:
        if HAS_ARDUINO_BRIDGE:
            # If running on the Arduino App Lab environment, run using the App loop scheduler
            def loop_callback():
                nonlocal last_telemetry_time, last_repeat_time
                now = time.time()

                # A. Periodically fetch telemetry and update coordinates (10Hz / every 100ms)
                if now - last_telemetry_time >= 0.100:
                    state_machine.update_telemetry()
                    last_telemetry_time = now

                # B. Execute autonomous repeat path steps (5Hz / every 200ms)
                if state_machine.mode == "REPEAT" and (now - last_repeat_time >= 0.200):
                    state_machine.execute_repeat_step()
                    last_repeat_time = time.time()

            # Launch the App Lab loop scheduler
            App.run(user_loop=loop_callback)
        else:
            # Main execution loop (SocketRouterBridge or Simulator)
            logger.info("Rover main loop active. Press Ctrl+C to exit.")
            while True:
                now = time.time()
                
                # Update telemetry at 10Hz
                if now - last_telemetry_time >= 0.100:
                    state_machine.update_telemetry()
                    last_telemetry_time = now
                    
                # Execute autonomous playback step at 5Hz
                if state_machine.mode == "REPEAT" and (now - last_repeat_time >= 0.200):
                    state_machine.execute_repeat_step()
                    last_repeat_time = time.time()
                    
                time.sleep(0.01) # Small loop sleep

    except KeyboardInterrupt:
        logger.info("Shutting down Rover main software...")
    finally:
        # Safe cleanup: turn off motors, disconnect BLE, finalize mission log.
        bridge.call("set_motor_speeds", 0, 0)
        ble_server.stop()
        if hasattr(state_machine, "mission_logger"):
            state_machine.mission_logger.close()
        logger.info("Shutdown completed.")


if __name__ == "__main__":
    main()
