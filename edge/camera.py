import os
import cv2
import time
import numpy as np

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


class EdgeCamera:
    """Handles image capture from physical webcam or falls back to mock test images."""
    def __init__(self, source="0"):
        self.source = source
        self.is_mock = False
        self._mock_frame_count = 0  # for animating mock frames
        
        if source.isdigit():
            # OpenCV Webcam source
            self.cap = cv2.VideoCapture(int(source))
            if not self.cap.isOpened():
                print(f"Could not open webcam index {source}. Initializing camera in Mock Mode.")
                self.is_mock = True
            else:
                # Set lower resolution for fast RPi processing
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        else:
            # Source is a path or folder
            if not os.path.exists(source):
                print(f"Source path {source} does not exist. Initializing camera in Mock Mode.")
                self.is_mock = True
            else:
                self.cap = None # Will read file directly

    def capture_frame(self) -> np.ndarray:
        """Captures a still frame and returns a BGR numpy array (used by scan endpoint)."""
        if self.is_mock:
            # Generate dummy gray frame with garment-like shape
            frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
            # Draw a light clothing box shape in middle
            cv2.rectangle(frame, (180, 100), (460, 380), (200, 200, 200), -1)
            # Draw a defect-like dark circle
            cv2.circle(frame, (320, 240), 15, (50, 50, 255), -1)
            cv2.putText(frame, "MOCK FRAME (No Camera)", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            return frame
            
        if self.cap:
            # Read from webcam
            ret, frame = self.cap.read()
            if not ret or frame is None:
                # Fallback if webcam fails
                print("Failed to read frame from webcam.")
                return self.capture_frame_mock_fallback()
            return frame
        else:
            # Read static file
            if os.path.isdir(self.source):
                # Pick a random image from folder
                files = [os.path.join(self.source, f) for f in os.listdir(self.source) 
                         if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
                if files:
                    import random
                    return cv2.imread(random.choice(files))
            else:
                return cv2.imread(self.source)

    def read_live_frame(self) -> np.ndarray:
        """
        Reads a frame suitable for continuous MJPEG streaming.
        Non-blocking: does NOT sleep. Returns an animated frame in mock mode.
        """
        if self.is_mock:
            return self._build_mock_live_frame()
            
        if self.cap:
            ret, frame = self.cap.read()
            if not ret or frame is None:
                return self._build_mock_live_frame()
            return frame
        else:
            # Static source: just read the file (for testing)
            if os.path.isdir(self.source):
                files = [os.path.join(self.source, f) for f in os.listdir(self.source)
                         if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
                if files:
                    import random
                    return cv2.imread(random.choice(files))
            return cv2.imread(self.source)

    def _build_mock_live_frame(self) -> np.ndarray:
        """Generates an animated mock frame with timestamp and scan-line overlay."""
        self._mock_frame_count += 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Dark gradient background
        for y in range(480):
            val = int(15 + (y / 480) * 25)
            frame[y, :] = [val, val, val + 10]

        # Simulated garment silhouette
        cv2.rectangle(frame, (160, 90), (480, 390), (40, 35, 60), -1)
        cv2.rectangle(frame, (160, 90), (480, 390), (70, 55, 120), 2)

        # Animated scan line (moves top to bottom based on frame count)
        scan_y = int((self._mock_frame_count * 3) % 480)
        alpha_line = frame.copy()
        cv2.line(alpha_line, (0, scan_y), (640, scan_y), (80, 200, 255), 2)
        frame = cv2.addWeighted(frame, 0.85, alpha_line, 0.15, 0)

        # Corner brackets
        bracket_color = (100, 220, 255)
        blen = 25
        # Top-left
        cv2.line(frame, (155, 85), (155 + blen, 85), bracket_color, 2)
        cv2.line(frame, (155, 85), (155, 85 + blen), bracket_color, 2)
        # Top-right
        cv2.line(frame, (485, 85), (485 - blen, 85), bracket_color, 2)
        cv2.line(frame, (485, 85), (485, 85 + blen), bracket_color, 2)
        # Bottom-left
        cv2.line(frame, (155, 395), (155 + blen, 395), bracket_color, 2)
        cv2.line(frame, (155, 395), (155, 395 - blen), bracket_color, 2)
        # Bottom-right
        cv2.line(frame, (485, 395), (485 - blen, 395), bracket_color, 2)
        cv2.line(frame, (485, 395), (485, 395 - blen), bracket_color, 2)

        # LIVE badge
        cv2.rectangle(frame, (10, 10), (80, 36), (0, 0, 200), -1)
        cv2.putText(frame, "  LIVE", (12, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        # Timestamp
        ts = time.strftime("%H:%M:%S")
        cv2.putText(frame, ts, (540, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 180), 1)

        # "NO CAMERA" watermark
        cv2.putText(frame, "MOCK FEED - NO CAMERA", (120, 450),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 120), 1)

        return frame

    def capture_frame_mock_fallback(self) -> np.ndarray:
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 50
        cv2.putText(frame, "Camera Read Failed", (150, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        return frame

    def release(self):
        if not self.is_mock and self.cap:
            self.cap.release()
