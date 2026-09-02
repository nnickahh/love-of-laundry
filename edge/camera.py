import os
import cv2
import time
import numpy as np
from pathlib import Path

class PanTiltController:
    """Controls the Pan-Tilt HAT servo motors via Mock (Windows/Dev) or I2C (Raspberry Pi)."""
    def __init__(self, use_hardware=False):
        self.use_hardware = use_hardware
        self.pan_angle = 0.0
        self.tilt_angle = 0.0
        
        if self.use_hardware:
            try:
                # Import RPi specific libraries inside the condition
                import smbus
                self.bus = smbus.SMBus(1)
                # PCA9685 address & register configurations for servo controller
                self.pca_address = 0x40
                # Initialize PCA9685
                self.bus.write_byte_data(self.pca_address, 0x00, 0x20) # Enable Auto-Increment
                self.bus.write_byte_data(self.pca_address, 0xFE, 121)  # Set Prescale to 50Hz (20ms period)
                self.bus.write_byte_data(self.pca_address, 0x00, 0xa1) # Restart
                print("Pan-Tilt Controller initialized using Raspberry Pi I2C (PCA9685)")
            except Exception as e:
                print(f"Failed to initialize physical Pan-Tilt I2C hardware: {e}")
                print("Falling back to Mock Mode.")
                self.use_hardware = False
        
        if not self.use_hardware:
            print("Pan-Tilt Controller initialized in Mock Mode (Development)")

    def set_angle(self, pan: float, tilt: float):
        """Sets the pan and tilt angles in degrees (typically -90 to 90)."""
        # Clamp inputs
        self.pan_angle = max(min(pan, 90.0), -90.0)
        self.tilt_angle = max(min(tilt, 90.0), -90.0)
        
        print(f"[Pan-Tilt Motor] Moving to Pan: {self.pan_angle}°, Tilt: {self.tilt_angle}°")
        
        if self.use_hardware:
            # Physical Waveshare / Pimoroni servo pulse calculations
            # Convert degrees (-90 to 90) to servo pulse length (1ms to 2ms, or PCA9685 count 204 to 409)
            # Channel 0: Pan, Channel 1: Tilt
            self._write_servo_pulse(0, self.pan_angle)
            self._write_servo_pulse(1, self.tilt_angle)
            
        time.sleep(0.3) # Wait for motors to move

    def _write_servo_pulse(self, channel: int, angle: float):
        """Helper to write PCA9685 PWM registers."""
        # Mapping -90 -> 90 to 150 -> 600 PCA9685 counts
        val = int(375 + (angle / 90.0) * 225)
        # Register for channel: LEDx_ON_L, LEDx_ON_H, LEDx_OFF_L, LEDx_OFF_H
        reg_base = 0x06 + (channel * 4)
        try:
            self.bus.write_byte_data(self.pca_address, reg_base, 0)
            self.bus.write_byte_data(self.pca_address, reg_base + 1, 0)
            self.bus.write_byte_data(self.pca_address, reg_base + 2, val & 0xFF)
            self.bus.write_byte_data(self.pca_address, reg_base + 3, (val >> 8) & 0xFF)

        except Exception as e:
            print(f"Error writing to servo channel {channel}: {e}")

    def get_angles(self) -> dict:
        return {"pan": self.pan_angle, "tilt": self.tilt_angle}

    def get_presets(self) -> dict:
        return {
            "center": (0.0, 0.0),
            "top_left": (-30.0, 30.0),
            "top_right": (30.0, 30.0),
            "bottom_left": (-30.0, -30.0),
            "bottom_right": (30.0, -30.0),
        }

import sys
import threading

class EdgeCamera:
    """Handles image capture from physical webcams, external USB cameras, RTSP/HTTP streams, Picamera2, or sample clothing mock feeds."""
    def __init__(self, source="0"):
        self.lock = threading.Lock()
        self.source = str(source)
        self.is_mock = False
        self.is_file = False
        self._mock_frame_count = 0
        self.cap = None
        self.picam2 = None
        self.source_name = "Camera"
        self._consecutive_failures = 0
        self._latest_frame = None
        
        # Background dedicated camera grab thread (eliminates V4L2 driver latency & buffer buildup)
        self._stop_grabber = threading.Event()
        self._grabber_thread = None
        
        # Load sample clothing images for rich mock mode fallback
        self.mock_images = []
        for search_dir in ["assets", "edge/static/captures", "dataset/labelled/jacket", "dataset/labelled/shirt", "dataset/deepfashion/images/train"]:
            p = Path(search_dir)
            if p.exists() and p.is_dir():
                for ext in ["*.jpg", "*.png", "*.jpeg"]:
                    self.mock_images.extend(list(p.glob(ext)))
        self.mock_images = [str(f) for f in self.mock_images if not Path(f).name.startswith(".")]

        self._init_source(self.source)

    def _start_grabber_thread(self):
        """Starts dedicated frame reader thread if physical camera or stream is active."""
        self._stop_grabber.clear()
        if self._grabber_thread is None or not self._grabber_thread.is_alive():
            self._grabber_thread = threading.Thread(target=self._grab_loop, daemon=True, name="cam_grabber")
            self._grabber_thread.start()

    def _grab_loop(self):
        """Continuously pulls frames at full sensor speed to keep driver buffer empty (0ms latency)."""
        while not self._stop_grabber.is_set():
            if self.cap and not self.is_mock and not self.is_file:
                try:
                    ret, frame = self.cap.read()
                    if ret and frame is not None and frame.size > 0:
                        with self.lock:
                            self._latest_frame = frame
                            self._consecutive_failures = 0
                    else:
                        time.sleep(0.005)
                except Exception:
                    time.sleep(0.01)
            elif self.picam2 and not self.is_mock:
                try:
                    frame = self.picam2.capture_array()
                    if frame is not None:
                        with self.lock:
                            self._latest_frame = frame
                except Exception:
                    time.sleep(0.01)
            else:
                time.sleep(0.03)

    def _get_backends(self):
        """Returns platform-specific backends in prioritized order."""
        if sys.platform == "win32":
            return [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        return [cv2.CAP_V4L2, cv2.CAP_ANY]

    def _init_source(self, source: str):
        """Initializes the camera device or stream for the given source identifier."""
        self._release_current()
        self.source = str(source).strip()
        self._consecutive_failures = 0
        self.is_file = False
        self._latest_frame = None

        # 1. Explicit Mock Mode
        if self.source.lower() in ["mock", "test", "none"]:
            print("[EdgeCamera] Explicit Mock Mode activated.")
            self.is_mock = True
            self.source_name = "Mock Test Feed"
            return

        # 2. Static image or directory source
        if not self.source.isdigit() and not self.source.startswith(("http://", "https://", "rtsp://", "rtmp://")) and os.path.exists(self.source):
            print(f"[EdgeCamera] Using static file/directory source: {self.source}")
            self.is_mock = False
            self.is_file = True
            self.source_name = f"File: {Path(self.source).name}"
            return

        # 3. RTSP / HTTP / RTMP Network Stream (e.g. VLC streaming, IP Webcam, DroidCam)
        if self.source.startswith(("http://", "https://", "rtsp://", "rtmp://")):
            print(f"[EdgeCamera] Connecting to Network / VLC Stream: {self.source}")
            try:
                cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ret, test_frame = cap.read()
                if ret and test_frame is not None and test_frame.size > 0:
                    self.cap = cap
                    self.is_mock = False
                    self._latest_frame = test_frame
                    self.source_name = f"Stream ({self.source[:24]}...)" if len(self.source) > 28 else f"Stream ({self.source})"
                    print(f"[EdgeCamera] Connected to Network Stream: {test_frame.shape[1]}x{test_frame.shape[0]}")
                    self._start_grabber_thread()
                    return
                cap.release()
            except Exception as e:
                print(f"[EdgeCamera] Failed to connect to stream {self.source}: {e}")

        # 4. Raspberry Pi CSI Ribbon Camera via Picamera2
        if self.source.lower() in ["0", "csi", "rpi", "picam"]:
            try:
                from picamera2 import Picamera2
                self.picam2 = Picamera2()
                config = self.picam2.create_preview_configuration(main={"size": (640, 480), "format": "BGR888"})
                self.picam2.configure(config)
                self.picam2.start()
                self.is_mock = False
                self.source_name = "RPi CSI Camera (Picamera2)"
                print("[EdgeCamera] Initialized Raspberry Pi CSI Camera via Picamera2")
                self._start_grabber_thread()
                return
            except Exception:
                self.picam2 = None

        # 5. Physical USB / Laptop Webcams via OpenCV VideoCapture
        backends = self._get_backends()
        
        # Determine candidate device indices
        indices_to_try = []
        if self.source.isdigit():
            indices_to_try.append(int(self.source))
        else:
            indices_to_try.extend([0, 1, 2, 3])

        # Also add common indices as fallbacks if specific index was requested
        for idx in [0, 1, 2, 3]:
            if idx not in indices_to_try:
                indices_to_try.append(idx)

        for idx in indices_to_try:
            for backend in backends:
                try:
                    cap = cv2.VideoCapture(idx, backend)
                    if not cap.isOpened():
                        continue

                    # Request hardware MJPEG mode on webcam to dramatically lower USB bandwidth & latency
                    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    
                    for _ in range(4):
                        ret, test_frame = cap.read()
                        if ret and test_frame is not None and test_frame.size > 0:
                            self.cap = cap
                            self.is_mock = False
                            self._latest_frame = test_frame
                            self.source = str(idx)
                            self.source_name = f"Camera {idx} ({'Laptop/Built-in' if idx == 0 else 'External USB'})"
                            print(f"==================================================")
                            print(f" SUCCESS: Connected to Camera #{idx} ({self.source_name})")
                            print(f" Resolution: {test_frame.shape[1]}x{test_frame.shape[0]} @ 30fps")
                            print(f"==================================================")
                            self._start_grabber_thread()
                            return
                        time.sleep(0.03)
                    cap.release()
                except Exception:
                    continue

        # 6. Fallback to Mock Garment Mode
        print(f"[EdgeCamera] No physical or stream cameras available. Initializing Mock Garment Mode ({len(self.mock_images)} sample images ready).")
        self.is_mock = True
        self.source_name = "Mock Mode (No Camera)"

    def set_source(self, new_source: str) -> dict:
        """Dynamically switch camera source at runtime."""
        with self.lock:
            self._init_source(new_source)
            return {
                "status": "success",
                "source": self.source,
                "is_mock": self.is_mock,
                "source_name": self.source_name
            }

    def detect_available_sources(self) -> list:
        """Scans and detects available camera devices on the system."""
        sources = []
        backends = self._get_backends()

        # Check USB / Webcam indices 0..3
        for idx in range(4):
            # If current camera is using this index and opened, mark available
            if self.cap and not self.is_mock and self.source == str(idx):
                name = "Laptop / Primary Camera (0)" if idx == 0 else f"External Camera ({idx})"
                sources.append({
                    "id": str(idx),
                    "name": name,
                    "type": "usb",
                    "available": True,
                    "active": True
                })
                continue

            # Otherwise test-open briefly
            found = False
            for backend in backends:
                try:
                    test_cap = cv2.VideoCapture(idx, backend)
                    if test_cap.isOpened():
                        ret, test_frame = test_cap.read()
                        if ret and test_frame is not None:
                            found = True
                    test_cap.release()
                    if found:
                        break
                except Exception:
                    pass

            if found:
                name = "Laptop / Primary Camera (0)" if idx == 0 else f"External Camera ({idx})"
                sources.append({
                    "id": str(idx),
                    "name": name,
                    "type": "usb",
                    "available": True,
                    "active": (self.source == str(idx) and not self.is_mock)
                })

        # Add Network Stream option
        is_stream_active = self.source.startswith(("http://", "https://", "rtsp://", "rtmp://")) and not self.is_mock
        sources.append({
            "id": self.source if is_stream_active else "network_stream",
            "name": f"Network / VLC Stream ({self.source[:20]}...)" if is_stream_active else "Network / VLC Stream (RTSP/HTTP)",
            "type": "stream",
            "available": True,
            "active": is_stream_active
        })

        # Add Mock Mode option
        sources.append({
            "id": "mock",
            "name": "Mock Test Mode (Sample Garments)",
            "type": "mock",
            "available": True,
            "active": self.is_mock
        })

        return sources

    def capture_frame(self) -> np.ndarray:
        """Captures a pristine frame for YOLO inference and defect logging."""
        with self.lock:
            # 1. Active physical/stream frame from dedicated background grabber
            if self._latest_frame is not None and not self.is_mock:
                return self._latest_frame.copy()

            # 2. Static file source
            if self.is_file and os.path.exists(self.source):
                try:
                    if os.path.isdir(self.source):
                        files = [os.path.join(self.source, f) for f in os.listdir(self.source) 
                                 if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
                        if files:
                            import random
                            return cv2.imread(random.choice(files))
                    else:
                        return cv2.imread(self.source)
                except Exception:
                    pass

            # 3. Mock Mode: Return a real sample clothing image for AI inspection
            if self.mock_images:
                import random
                try:
                    img_path = random.choice(self.mock_images)
                    img = cv2.imread(img_path)
                    if img is not None:
                        return cv2.resize(img, (640, 480))
                except Exception:
                    pass

            return self._build_mock_live_frame()

    def read_live_frame(self) -> np.ndarray:
        """Instantly returns the freshest frame captured by the dedicated grab thread with zero lag."""
        with self.lock:
            if self._latest_frame is not None and not self.is_mock:
                return self._latest_frame

            if self.is_file and os.path.exists(self.source):
                try:
                    return cv2.imread(self.source)
                except Exception:
                    pass

            return self._build_mock_live_frame()

    def _build_mock_live_frame(self) -> np.ndarray:
        """Generates a realistic live mock frame."""
        self._mock_frame_count += 1
        
        # Load sample clothing base if available
        base_frame = None
        if self.mock_images:
            img_idx = (self._mock_frame_count // 30) % len(self.mock_images)
            base_frame = cv2.imread(self.mock_images[img_idx])
            if base_frame is not None:
                base_frame = cv2.resize(base_frame, (640, 480))

        if base_frame is None:
            base_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            for y in range(480):
                val = int(15 + (y / 480) * 25)
                base_frame[y, :] = [val, val, val + 10]
            cv2.rectangle(base_frame, (160, 90), (480, 390), (40, 35, 60), -1)
            cv2.rectangle(base_frame, (160, 90), (480, 390), (70, 55, 120), 2)

        frame = base_frame.copy()

        # HUD Brackets
        bracket_color = (100, 220, 255)
        blen = 25
        cv2.line(frame, (155, 85), (155 + blen, 85), bracket_color, 2)
        cv2.line(frame, (155, 85), (155, 85 + blen), bracket_color, 2)
        cv2.line(frame, (485, 85), (485 - blen, 85), bracket_color, 2)
        cv2.line(frame, (485, 85), (485, 85 + blen), bracket_color, 2)
        cv2.line(frame, (155, 395), (155 + blen, 395), bracket_color, 2)
        cv2.line(frame, (155, 395), (155, 395 - blen), bracket_color, 2)
        cv2.line(frame, (485, 395), (485 - blen, 395), bracket_color, 2)
        cv2.line(frame, (485, 395), (485, 395 - blen), bracket_color, 2)

        # Timestamp
        ts = time.strftime("%H:%M:%S")
        cv2.putText(frame, ts, (540, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 180), 1)

        # Watermark
        cv2.putText(frame, "MOCK / DEMO FEED", (200, 460),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 220), 2)

        return frame

    def _release_current(self):
        if self.picam2:
            try:
                self.picam2.stop()
            except Exception:
                pass
            self.picam2 = None
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def release(self):
        with self.lock:
            self._release_current()

