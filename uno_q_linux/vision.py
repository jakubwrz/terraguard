import os
import time
import urllib.request
import logging
from typing import Optional

logger = logging.getLogger("RoverVision")
logging.basicConfig(level=logging.INFO)

# Dataset Directories for Training
DATASET_BASE = "dataset"
RISK_CATEGORIES = ["low_risk", "medium_risk", "high_risk"]

# ONNX Model Path (deployed alongside the Python stack)
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wildfire_model.onnx")

# Class index to label mapping (must match training order)
CLASS_LABELS = ["low_risk", "medium_risk", "high_risk"]

# ImageNet normalization constants (standard for MobileNet/ResNet transfer learning)
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class RoverVision:
    """
    Manages connection to the Seeed Studio XIAO ESP32S3 Sense MJPEG camera stream,
    ONNX-based terrain risk classification, and training photo capture database.
    """

    def __init__(self, camera_ip: str = "192.168.4.1"):
        self.camera_ip = camera_ip
        self.stream_url = f"http://{camera_ip}/stream"
        self.onnx_session = None

        # Initialize training folders
        self._init_dataset_folders()

        # Load ONNX model
        self._load_model()

    def _init_dataset_folders(self):
        """Creates risk dataset directories on the Linux eMMC if they don't exist."""
        for category in RISK_CATEGORIES:
            path = os.path.join(DATASET_BASE, category)
            os.makedirs(path, exist_ok=True)
        logger.info("Initialized local training image datasets at: dataset/{low_risk, medium_risk, high_risk}")

    def _load_model(self):
        """Loads the ONNX terrain risk classification model."""
        try:
            import onnxruntime as ort
            
            # Check candidate model paths
            candidate_paths = [
                MODEL_PATH,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "wildfire_model.onnx"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "wildfire_model.onnx"),
                "wildfire_model.onnx"
            ]

            resolved_path = None
            for p in candidate_paths:
                if os.path.exists(p):
                    resolved_path = os.path.abspath(p)
                    break

            if not resolved_path:
                logger.warning(f"ONNX model not found in candidates: {candidate_paths}. Classification will use fallback.")
                return

            self.onnx_session = ort.InferenceSession(resolved_path)
            inp = self.onnx_session.get_inputs()[0]
            out = self.onnx_session.get_outputs()[0]
            logger.info(f"ONNX model loaded: {resolved_path} (input={inp.shape}, output={out.shape})")
        except ImportError:
            logger.warning("onnxruntime not installed. Classification will use fallback.")
        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e}. Classification will use fallback.")

    def fetch_single_frame(self) -> Optional[bytes]:
        """
        Connects to the MJPEG stream, reads the buffer, and parses out 
        exactly one complete JPEG frame using binary delimiters (FFD8 and FFD9).
        """
        try:
            # Short timeout to prevent locking if camera goes offline
            stream = urllib.request.urlopen(self.stream_url, timeout=3.0)
            bytes_buffer = b""
            
            # Read chunks of stream to find the first complete JPEG image
            for _ in range(200): # Hard limit read loops to prevent hanging
                chunk = stream.read(1024)
                if not chunk:
                    break
                bytes_buffer += chunk
                
                # A JPEG image starts with 0xFFD8 and ends with 0xFFD9
                a = bytes_buffer.find(b'\xff\xd8')
                b = bytes_buffer.find(b'\xff\xd9')
                
                if a != -1 and b != -1 and b > a:
                    jpg_bytes = bytes_buffer[a:b+2]
                    stream.close()
                    return jpg_bytes
            
            stream.close()
        except Exception as e:
            logger.error(f"Error fetching frame from camera {self.stream_url}: {e}")
        
        return None

    def _preprocess_frame(self, jpeg_bytes: bytes):
        """
        Preprocesses a JPEG frame for ONNX inference:
        1. Decode JPEG -> RGB
        2. Resize to 224x224
        3. Normalize with ImageNet mean/std
        4. Transpose to NCHW format [1, 3, 224, 224]
        """
        import numpy as np
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
        img = img.resize((224, 224), Image.BILINEAR)

        # Convert to float32 numpy array [0, 1]
        arr = np.array(img, dtype=np.float32) / 255.0

        # Normalize with ImageNet stats: (pixel - mean) / std
        for c in range(3):
            arr[:, :, c] = (arr[:, :, c] - IMAGENET_MEAN[c]) / IMAGENET_STD[c]

        # Transpose from HWC [224, 224, 3] to NCHW [1, 3, 224, 224]
        arr = np.transpose(arr, (2, 0, 1))
        arr = np.expand_dims(arr, axis=0)

        return arr

    def classify_frame(self, jpeg_bytes: bytes, temp_c: Optional[float] = None, humidity_pct: Optional[float] = None) -> str:
        """
        Runs ONNX terrain risk classification fused with ambient weather data (Temperature & Humidity).
        
        Wildfire Risk Fusion Logic:
        - HIGH_RISK (visual): Dense vegetation -> Always BLOCKED.
        - MEDIUM_RISK (visual): Moderate grass/brush.
            * Under severe fire weather (Temp >= 30°C and Humidity <= 35%, or Temp >= 35°C, or Humidity <= 20%):
              Vegetation is tinder-dry and highly combustible -> ESCALATED TO HIGH_RISK (BLOCKED).
            * Under normal weather: CAUTION (passable at reduced speed).
        - LOW_RISK (visual): Clear path -> CLEAR.
        
        Returns:
        - "CLEAR": Safe to drive at full speed.
        - "CAUTION": Medium vegetation, proceed with care at reduced speed.
        - "BLOCKED": Dense vegetation or extreme wildfire hazard zone -> detour required.
        """
        if self.onnx_session is None or jpeg_bytes is None:
            return "CLEAR"

        try:
            import numpy as np

            # Preprocess
            input_tensor = self._preprocess_frame(jpeg_bytes)

            # Run inference
            input_name = self.onnx_session.get_inputs()[0].name
            logits = self.onnx_session.run(None, {input_name: input_tensor})[0][0]

            # Softmax
            exp_logits = np.exp(logits - np.max(logits))
            probs = exp_logits / np.sum(exp_logits)

            predicted_idx = int(np.argmax(probs))
            visual_label = CLASS_LABELS[predicted_idx]
            confidence = float(probs[predicted_idx])

            # Base decision from visual classification
            if visual_label == "low_risk":
                decision = "CLEAR"
            elif visual_label == "medium_risk":
                decision = "CAUTION"
            else:
                decision = "BLOCKED"

            final_risk = visual_label
            env_note = ""

            # --- ENVIRONMENTAL WILDFIRE RISK FUSION ---
            if temp_c is not None and temp_c > 0.0 and humidity_pct is not None and humidity_pct > 0.0:
                is_severe_fire_weather = (temp_c >= 30.0 and humidity_pct <= 35.0) or (temp_c >= 35.0) or (humidity_pct <= 20.0)
                is_elevated_fire_weather = (temp_c >= 26.0 and humidity_pct <= 45.0)

                if is_severe_fire_weather:
                    if visual_label == "medium_risk":
                        # Dry grass/brush under high heat + low humidity becomes extreme wildfire danger!
                        final_risk = "high_risk"
                        decision = "BLOCKED"
                        env_note = f" [🔥 SEVERE WILDFIRE RISK: Temp={temp_c:.1f}°C, Hum={humidity_pct:.1f}% -> ESCALATED TO BLOCKED]"
                    elif visual_label == "low_risk":
                        env_note = f" [⚠️ Extreme Ambient Weather: Temp={temp_c:.1f}°C, Hum={humidity_pct:.1f}%]"
                elif is_elevated_fire_weather:
                    env_note = f" [Elevated Weather: Temp={temp_c:.1f}°C, Hum={humidity_pct:.1f}%]"
                else:
                    env_note = f" [Mild Weather: Temp={temp_c:.1f}°C, Hum={humidity_pct:.1f}%]"
            else:
                env_note = " [Env sensors offline/unplugged - using vision only]"

            logger.info(
                f"Terrain Assessment: Visual={visual_label} ({confidence*100:.1f}%) | "
                f"Final Risk={final_risk} -> Decision={decision}{env_note}"
            )

            self.last_assessment = {
                "visual_label": visual_label,
                "confidence": confidence,
                "final_risk": final_risk,
                "decision": decision,
                "probabilities": {
                    "low": float(probs[0]),
                    "medium": float(probs[1]),
                    "high": float(probs[2])
                },
                "env_note": env_note
            }

            return decision

        except Exception as e:
            logger.error(f"Classification inference failed: {e}")
            self.last_assessment = {
                "visual_label": "unknown",
                "confidence": 0.0,
                "final_risk": "low_risk",
                "decision": "CLEAR",
                "probabilities": {},
                "env_note": str(e)
            }
            return "CLEAR"

    def _create_placeholder_frame(self, text: str) -> bytes:
        """Generates a minimal valid JPEG image as a fallback when camera is offline."""
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.new('RGB', (320, 240), color=(20, 25, 45))
            d = ImageDraw.Draw(img)
            d.text((20, 100), f"CAMERA OFFLINE\n{text}\nCheck IP: {self.camera_ip}", fill=(255, 100, 100))
            buf = io.BytesIO()
            img.save(buf, format='JPEG')
            return buf.getvalue()
        except Exception:
            # Minimal 1x1 white JPEG binary fallback
            return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'

    def save_training_photo(self, risk_level: str, sensor_data: Optional[dict] = None, frame_bytes: Optional[bytes] = None) -> bool:
        """
        Saves a camera frame to the labeled dataset folder,
        and saves corresponding multispectral and environmental data to a JSON sidecar.
        """
        if risk_level not in RISK_CATEGORIES:
            logger.error(f"Invalid risk category: {risk_level}")
            return False

        logger.info(f"Triggering training photo capture for category: [{risk_level}]...")
        if frame_bytes is not None:
            jpg_bytes = frame_bytes
        else:
            jpg_bytes = self.fetch_single_frame()
        
        if jpg_bytes is None:
            logger.warning(f"Camera stream ({self.stream_url}) unreachable. Saving sensor metadata with placeholder image.")
            jpg_bytes = self._create_placeholder_frame(f"Risk: {risk_level}")

        timestamp = int(time.time() * 1000)
        filename = f"photo_{timestamp}.jpg"
        filepath = os.path.join(DATASET_BASE, risk_level, filename)
        
        try:
            with open(filepath, "wb") as f:
                f.write(jpg_bytes)
            logger.info(f"Saved training image: {filepath} ({len(jpg_bytes)} bytes)")
            
            # Save corresponding sensor metadata if provided
            if sensor_data is not None:
                import json
                meta_filename = f"photo_{timestamp}.json"
                meta_filepath = os.path.join(DATASET_BASE, risk_level, meta_filename)
                
                metadata = {
                    "timestamp": timestamp,
                    "risk_level": risk_level,
                    "sensor_data": sensor_data
                }
                
                with open(meta_filepath, "w") as f_meta:
                    json.dump(metadata, f_meta, indent=4)
                logger.info(f"Saved sensor metadata: {meta_filepath}")

            return True
        except Exception as e:
            logger.error(f"Failed to write image or metadata file to disk: {e}")
            return False


# Local diagnostic script
if __name__ == "__main__":
    vision = RoverVision("127.0.0.1") # Run local test
    # Test file saving mock
    vision.save_training_photo("low_risk")
