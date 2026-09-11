import sys
import logging
import asyncio
import socket
import threading
from typing import Callable, Optional

# Attempt to import bless for BLE peripheral support.
# If bless is unavailable, we fall back to a TCP socket mock server.
HAS_BLESS = False
try:
    from bless import (
        BlessServer,
        BlessGATTCharacteristic,
        GATTCharacteristicProperties,
        GATTAttributePermissions,
    )
    HAS_BLESS = True
except ImportError:
    pass

logger = logging.getLogger("RoverBLEServer")
logging.basicConfig(level=logging.INFO)

# BLE UUID Constants
SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
CHAR_UUID = "51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B"


class RoverBLEServer:
    """
    BLE Server for smartphone joystick control and training captures.
    
    Supports:
    - Directional controls: 'F' (Forward), 'B' (Backward), 'L' (Left), 'R' (Right), 'S' (Stop)
    - Photo training tagging: 'P_LOW' (Low Risk), 'P_MED' (Medium Risk), 'P_HIGH' (High Risk)
    """

    def __init__(self, name: str = "TerraGuardRover", command_callback: Optional[Callable[[str], None]] = None):
        self.name = name
        self.command_callback = command_callback
        self.server: Optional[BlessServer] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.tcp_server_thread: Optional[threading.Thread] = None
        self._active_tcp_conn: Optional[socket.socket] = None
        self.running = False

    def send_notification(self, message: str):
        """Broadcasts a live status message/alert back to the smartphone app."""
        if not message:
            return
        logger.info(f"[BLE Notify] -> App: {message}")

        # 1. BLE Server Notification (Bless)
        if self.server and self.loop and self.server.is_running:
            try:
                char = self.server.get_characteristic(CHAR_UUID)
                if char:
                    char.value = message.encode("utf-8")
                    asyncio.run_coroutine_threadsafe(
                        self.server.update_value(SERVICE_UUID, CHAR_UUID),
                        self.loop
                    )
            except Exception as e:
                logger.debug(f"Bless notification skipped: {e}")

        # 2. TCP Mock Server Notification (if socket connected)
        if self._active_tcp_conn:
            try:
                self._active_tcp_conn.sendall((message + "\n").encode("utf-8"))
            except Exception:
                self._active_tcp_conn = None

    def handle_command(self, cmd: str):
        """Processes and forwards incoming commands to the callback."""
        cleaned_cmd = cmd.strip().upper()
        if not cleaned_cmd:
            return
            
        logger.info(f"Received Command: {cleaned_cmd}")
        if self.command_callback:
            try:
                self.command_callback(cleaned_cmd)
            except Exception as e:
                logger.error(f"Error in command callback: {e}")

    # --- BLE SERVER IMPLEMENTATION ---
    def _ble_write_request(self, characteristic: 'BlessGATTCharacteristic', value: bytearray, **kwargs):
        """Callback triggered when a BLE client writes to the characteristic."""
        try:
            cmd = value.decode("utf-8")
            self.handle_command(cmd)
        except Exception as e:
            logger.error(f"Failed to decode BLE write value: {e}")

    async def _start_ble(self):
        """Initializes and starts the BLE Server."""
        logger.info("Initializing BLE Server...")
        self.server = BlessServer(name=self.name, loop=self.loop)
        
        # Override the write request handler
        self.server.write_request_func = self._ble_write_request

        # Create Service and Characteristic
        await self.server.add_new_service(SERVICE_UUID)
        
        char_flags = (
            GATTCharacteristicProperties.write |
            GATTCharacteristicProperties.read |
            GATTCharacteristicProperties.notify
        )
        permissions = GATTAttributePermissions.writeable | GATTAttributePermissions.readable
        
        await self.server.add_new_characteristic(
            SERVICE_UUID, CHAR_UUID, char_flags, None, permissions
        )

        await self.server.start()
        logger.info("BLE Server started successfully and is advertising.")

    # --- TCP FALLBACK MOCK SERVER ---
    def _start_tcp_mock(self):
        """Launches a mock TCP socket server to receive commands in environments without BLE."""
        host = "0.0.0.0"
        port = 8888
        logger.warning(f"Starting TCP Mock command server on {host}:{port} due to missing BLE hardware/library...")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(1)
        sock.settimeout(1.0)
        
        while self.running:
            try:
                conn, addr = sock.accept()
                self._active_tcp_conn = conn
                logger.info(f"Mock Client Connected: {addr}")
                conn.settimeout(1.0)
                while self.running:
                    try:
                        data = conn.recv(1024)
                        if not data:
                            break
                        cmd = data.decode("utf-8").strip()
                        self.handle_command(cmd)
                    except socket.timeout:
                        continue
                    except Exception as e:
                        logger.error(f"Mock client error: {e}")
                        break
                conn.close()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Mock TCP Server error: {e}")
                break
        sock.close()
        logger.info("TCP Mock command server stopped.")

    # --- BLE ASYNC THREAD RUNNER ---
    def _run_ble_thread(self):
        """Runs the asyncio event loop for BlessServer in a dedicated thread."""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._start_ble())
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"BLE Server Thread Error: {e}. Falling back to TCP Mock.")
            if self.running:
                self._start_tcp_mock()

    # --- PUBLIC CONTROL API ---
    def start(self):
        """Starts the BLE server. Falls back to TCP socket if BLE fails/is missing."""
        self.running = True
        
        if HAS_BLESS:
            logger.info("Starting BLE background worker thread...")
            self.ble_thread = threading.Thread(target=self._run_ble_thread, daemon=True)
            self.ble_thread.start()
        else:
            logger.warning("BLE library (bless) not installed. Starting TCP Mock server...")
            self.tcp_server_thread = threading.Thread(target=self._start_tcp_mock, daemon=True)
            self.tcp_server_thread.start()

    def stop(self):
        """Stops both the BLE and mock TCP servers."""
        self.running = False
        if self.server and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop)
            self.loop.call_soon_threadsafe(self.loop.stop)
            logger.info("BLE Server stopped.")
        
        if self.tcp_server_thread and self.tcp_server_thread.is_alive():
            self.tcp_server_thread.join(timeout=2.0)


# Quick verification entry point
if __name__ == "__main__":
    def print_cmd(c):
        print(f"[TEST CALLBACK] Command: {c}")

    srv = RoverBLEServer("TestRover", command_callback=print_cmd)
    srv.start()
    
    print("Press Ctrl+C to stop.")
    try:
        if srv.loop and srv.loop.is_running():
            srv.loop.run_forever()
        else:
            import time
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
