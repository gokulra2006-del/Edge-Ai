"""
Hardware Driver: NEO-6M GPS Receiver (UART).
============================================
Physical Interface: /dev/serial0 at 9600 baud

Connections:
- GPS TX -> Physical Pin 10 (GPIO 15 / RXD)  — GPS sends NMEA data TO Pi
- GPS RX -> Physical Pin 8  (GPIO 14 / TXD)  — Pi sends commands TO GPS
- GPS GND -> Common GND
- GPS VCC -> Verify your specific breakout board (most accept 3.3V or 5V)

IMPORTANT: Do not assume the GPS VCC voltage. Check your breakout board:
- Most NEO-6M boards have an onboard regulator and accept 3.3V–5V input.
- Connect to 3.3V (Pin 1) or 5V (Pin 2/4) based on YOUR board's specs.

Parses NMEA-0183 sentences ($GPRMC, $GPGGA, $GNRMC, $GNGGA) for:
- latitude, longitude, altitude, speed, satellite count, fix status, UTC time
"""
import logging
import os
import time
from typing import Any, Dict, Optional
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
from src.config.hardware_config import HARDWARE_CONFIG

logger = logging.getLogger("EdgeAI")


class GPSDriver(BaseHardwareDriver):
    def __init__(self, debug_nmea: bool = False):
        super().__init__("NEO6M_GPS", "Geographic_Localization_Receiver")
        self._serial = None
        self._debug_nmea = debug_nmea  # If True, logs raw NMEA lines

        # GPS data — NEVER report as valid without an active fix
        self._latitude = None
        self._longitude = None
        self._altitude = None
        self._speed_kmh = 0.0
        self._satellites = 0
        self._fix_quality = 0  # 0 = no fix, 1 = GPS fix, 2 = DGPS fix
        self._utc_time = None  # UTC time string from NMEA
        self._has_valid_fix = False

        self.initialize()

    def initialize(self) -> bool:
        port = HARDWARE_CONFIG.uart_device
        if not os.path.exists(port):
            self.error_message = (
                f"UART device {port} not found. "
                "Enable with: sudo raspi-config -> Interface Options -> Serial Port"
            )
            self.status = DriverStatus.NOT_DETECTED
            self.is_simulated = True
            return False

        try:
            import serial
            self._serial = serial.Serial(
                port=port,
                baudrate=HARDWARE_CONFIG.uart_baud_rate,
                timeout=0.2
            )
            # GPS is connected but may not have a satellite fix yet
            self.status = DriverStatus.NO_FIX
            self.is_simulated = False
            self.error_message = None
            return True
        except ImportError:
            self.error_message = "pyserial library not installed. Install with: pip install pyserial"
            self.status = DriverStatus.NOT_DETECTED
            self.is_simulated = True
            return False
        except Exception as e:
            self.error_message = f"GPS serial connection error ({port}): {e}"
            self.status = DriverStatus.OFFLINE
            self.is_simulated = True
            return False

    def _parse_nmea(self, line: str):
        """
        Parses standard NMEA sentences.
        Supports GPS-only ($GP) and multi-GNSS ($GN) prefixes.
        """
        try:
            if self._debug_nmea:
                logger.debug(f"[GPS NMEA] {line}")

            parts = line.split(",")

            # ── $GPRMC / $GNRMC — Recommended Minimum ──
            if parts[0] in ("$GPRMC", "$GNRMC") and len(parts) > 9:
                # Extract UTC time (field 1): HHMMSS.sss
                if parts[1] and len(parts[1]) >= 6:
                    hh = parts[1][0:2]
                    mm = parts[1][2:4]
                    ss = parts[1][4:6]
                    self._utc_time = f"{hh}:{mm}:{ss} UTC"

                if parts[2] == "A":  # A = Active (valid fix)
                    self._has_valid_fix = True
                    self.status = DriverStatus.ONLINE

                    # Parse Latitude (field 3-4): DDMM.MMMM,N/S
                    if parts[3]:
                        raw_lat = float(parts[3])
                        lat_deg = int(raw_lat / 100)
                        lat_min = raw_lat - (lat_deg * 100)
                        self._latitude = round(lat_deg + (lat_min / 60.0), 6)
                        if parts[4] == "S":
                            self._latitude = -self._latitude

                    # Parse Longitude (field 5-6): DDDMM.MMMM,E/W
                    if parts[5]:
                        raw_lon = float(parts[5])
                        lon_deg = int(raw_lon / 100)
                        lon_min = raw_lon - (lon_deg * 100)
                        self._longitude = round(lon_deg + (lon_min / 60.0), 6)
                        if parts[6] == "W":
                            self._longitude = -self._longitude

                    # Parse Speed (field 7): knots -> km/h
                    if parts[7]:
                        self._speed_kmh = round(float(parts[7]) * 1.852, 1)

                elif parts[2] == "V":  # V = Void (no fix)
                    self._has_valid_fix = False
                    self.status = DriverStatus.NO_FIX

            # ── $GPGGA / $GNGGA — Fix Information ──
            elif parts[0] in ("$GPGGA", "$GNGGA") and len(parts) > 9:
                # Fix quality (field 6): 0=invalid, 1=GPS, 2=DGPS
                if parts[6]:
                    self._fix_quality = int(parts[6])
                    if self._fix_quality >= 1:
                        self._has_valid_fix = True
                        self.status = DriverStatus.ONLINE
                    else:
                        self._has_valid_fix = False
                        self.status = DriverStatus.NO_FIX

                # Satellite count (field 7)
                if parts[7]:
                    self._satellites = int(parts[7])

                # Altitude (field 9): meters above mean sea level
                if parts[9] and self._has_valid_fix:
                    self._altitude = round(float(parts[9]), 1)

        except (ValueError, IndexError) as e:
            if self._debug_nmea:
                logger.debug(f"[GPS] NMEA parse error: {e} in line: {line}")

    def read(self) -> Dict[str, Any]:
        self.read_count += 1
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        if not self.is_simulated and self._serial:
            try:
                # Non-blocking read: process all available NMEA sentences
                lines_read = 0
                while self._serial.in_waiting > 0 and lines_read < 20:
                    raw_line = self._serial.readline().decode("ascii", errors="ignore").strip()
                    if raw_line.startswith("$"):
                        self._parse_nmea(raw_line)
                        lines_read += 1

                self.last_read_time = now

                # CRITICAL: Only report position as valid if we have a fix
                if self._has_valid_fix and self._latitude is not None and self._longitude is not None:
                    fix_status = "3D_FIX" if self._altitude is not None else "2D_FIX"
                    return {
                        "latitude": self._latitude,
                        "longitude": self._longitude,
                        "altitude_m": self._altitude,
                        "speed_kmh": self._speed_kmh,
                        "satellites": self._satellites,
                        "fix_status": fix_status,
                        "fix_valid": True,
                        "utc_time": self._utc_time,
                        "timestamp": now_iso,
                        "quality": {
                            "status": DriverStatus.ONLINE.value,
                            "is_simulated": False,
                            "source": "physical_uart_neo6m"
                        }
                    }
                else:
                    # GPS is connected but has NO VALID FIX
                    return {
                        "latitude": None,
                        "longitude": None,
                        "altitude_m": None,
                        "speed_kmh": 0.0,
                        "satellites": self._satellites,
                        "fix_status": "NO_FIX",
                        "fix_valid": False,
                        "utc_time": self._utc_time,
                        "timestamp": now_iso,
                        "quality": {
                            "status": DriverStatus.NO_FIX.value,
                            "is_simulated": False,
                            "source": "physical_uart_neo6m",
                            "note": "GPS receiver online but no satellite fix acquired"
                        }
                    }

            except Exception as e:
                self.failure_count += 1
                self.status = DriverStatus.DEGRADED
                self.error_message = str(e)

        # Simulation Mode
        import random
        return {
            "latitude": round(12.9716 + random.uniform(-0.00002, 0.00002), 6),
            "longitude": round(77.5946 + random.uniform(-0.00002, 0.00002), 6),
            "altitude_m": round(920.0 + random.uniform(-0.5, 0.5), 1),
            "speed_kmh": round(random.uniform(0.0, 15.0), 1),
            "satellites": 9,
            "fix_status": "3D_FIX_SIMULATED",
            "fix_valid": False,
            "utc_time": "12:00:00 UTC",
            "timestamp": now_iso,
            "quality": {
                "status": DriverStatus.SIMULATED.value,
                "is_simulated": True,
                "source": "simulated_neo6m"
            }
        }

    def cleanup(self):
        """Closes the serial port."""
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
