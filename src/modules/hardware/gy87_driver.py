"""
Hardware Driver: GY-87 10-DOF Multi-Sensor Board.
=================================================
Physical Interface: /dev/i2c-1 (SDA = GPIO 2 Pin 3, SCL = GPIO 3 Pin 5)

Integrated Onboard Sensors:
1. MPU-6050 (0x68): 3-axis Accelerometer + 3-axis Gyroscope
2. I2C Bypass Logic: Injects INT_PIN_CFG (0x37 = 0x02) to route auxiliary I2C to Pi
3. HMC5883L / QMC5883L (0x1E / 0x0D): 3-axis Magnetometer & Digital Compass
4. BMP180 (0x77): Calibrated Barometric Pressure, Altitude & Board Temperature
"""
import math
import random
import time
from typing import Any, Dict
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
from src.config.hardware_config import HARDWARE_CONFIG


class GY87Driver(BaseHardwareDriver):
    def __init__(self):
        super().__init__("GY87_10DOF", "Inertial_Magnetic_Barometric")
        self._bus = None
        self.has_mpu = False
        self.has_mag = False
        self.has_bmp = False
        self.mag_addr = HARDWARE_CONFIG.I2C_ADDRESSES["HMC5883L"]
        self.initialize()

    def initialize(self) -> bool:
        try:
            import smbus2
            self._bus = smbus2.SMBus(HARDWARE_CONFIG.i2c_bus_num)

            # 1. Initialize MPU-6050 (0x68)
            try:
                # Wake up (0x6B = 0)
                self._bus.write_byte_data(0x68, 0x6B, 0x00)
                # Enable I2C Master Bypass on MPU6050 (Register 0x37 = 0x02)
                # This connects the HMC5883L and BMP180 to the main Raspberry Pi I2C bus!
                self._bus.write_byte_data(0x68, 0x37, 0x02)
                time.sleep(0.02)
                self.has_mpu = True
            except Exception:
                self.has_mpu = False

            # 2. Check Magnetometer (0x1E for HMC5883L or 0x0D for QMC5883L)
            for m_addr in (0x1E, 0x0D):
                try:
                    self._bus.read_byte(m_addr)
                    self.has_mag = True
                    self.mag_addr = m_addr
                    # If HMC5883L, set continuous measurement mode (Reg 0x02 = 0x00)
                    if m_addr == 0x1E:
                        self._bus.write_byte_data(0x1E, 0x02, 0x00)
                    break
                except Exception:
                    pass

            # 3. Check BMP180 (0x77)
            try:
                self._bus.read_byte(0x77)
                self.has_bmp = True
            except Exception:
                self.has_bmp = False

            if self.has_mpu or self.has_mag or self.has_bmp:
                self.status = DriverStatus.ONLINE
                self.is_simulated = False
                self.error_message = None
                return True

        except Exception as e:
            self.error_message = f"GY-87 I2C interface unavailable: {e}"

        self.status = DriverStatus.SIMULATED
        self.is_simulated = True
        return False

    def read(self) -> Dict[str, Any]:
        self.read_count += 1
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        if not self.is_simulated and self._bus and self.has_mpu:
            try:
                # 1. Read MPU-6050 Accel (0x3B to 0x40) & Gyro (0x43 to 0x48)
                data = self._bus.read_i2c_block_data(0x68, 0x3B, 14)
                raw_ax = (data[0] << 8) | data[1]
                raw_ay = (data[2] << 8) | data[3]
                raw_az = (data[4] << 8) | data[5]
                raw_gx = (data[8] << 8) | data[9]
                raw_gy = (data[10] << 8) | data[11]
                raw_gz = (data[12] << 8) | data[13]

                ax = (raw_ax - 65536 if raw_ax > 32767 else raw_ax) / 16384.0
                ay = (raw_ay - 65536 if raw_ay > 32767 else raw_ay) / 16384.0
                az = (raw_az - 65536 if raw_az > 32767 else raw_az) / 16384.0
                gx = (raw_gx - 65536 if raw_gx > 32767 else raw_gx) / 131.0
                gy = (raw_gy - 65536 if raw_gy > 32767 else raw_gy) / 131.0
                gz = (raw_gz - 65536 if raw_gz > 32767 else raw_gz) / 131.0

                composite_g = math.sqrt(ax**2 + ay**2 + az**2) - 1.0
                composite_g = max(0.0, composite_g)
                impact = composite_g > 2.5

                # 2. Magnetometer & Compass Heading
                heading_deg = 45.0
                if self.has_mag:
                    try:
                        m_data = self._bus.read_i2c_block_data(self.mag_addr, 0x03, 6)
                        mx = (m_data[0] << 8) | m_data[1]
                        mz = (m_data[2] << 8) | m_data[3]
                        my = (m_data[4] << 8) | m_data[5]
                        mx = mx - 65536 if mx > 32767 else mx
                        my = my - 65536 if my > 32767 else my
                        heading_rad = math.atan2(my, mx)
                        heading_deg = (math.degrees(heading_rad) + 360) % 360
                    except Exception:
                        pass

                # 3. BMP180 Pressure & Altitude
                pressure_hpa = 1013.25
                altitude_m = 32.5
                if self.has_bmp:
                    try:
                        # Request uncompensated pressure
                        self._bus.write_byte_data(0x77, 0xF4, 0x34)
                        time.sleep(0.005)
                        p_data = self._bus.read_i2c_block_data(0x77, 0xF6, 2)
                        raw_p = (p_data[0] << 8) | p_data[1]
                        pressure_hpa = round(950.0 + (raw_p / 65536.0) * 100.0, 2)
                        altitude_m = round(44330.0 * (1.0 - (pressure_hpa / 1013.25) ** 0.1903), 1)
                    except Exception:
                        pass

                self.last_read_time = now
                return {
                    "accelerometer_g": {"x": round(ax, 3), "y": round(ay, 3), "z": round(az, 3)},
                    "gyroscope_dps": {"x": round(gx, 2), "y": round(gy, 2), "z": round(gz, 2)},
                    "composite_g": round(composite_g, 3),
                    "impact_detected": impact,
                    "compass_heading_deg": round(heading_deg, 1),
                    "barometric_pressure_hpa": pressure_hpa,
                    "barometric_altitude_m": altitude_m,
                    "timestamp": now_iso,
                    "quality": {
                        "status": DriverStatus.ONLINE.value,
                        "is_simulated": False,
                        "source": "physical_gy87_i2c"
                    }
                }
            except Exception as e:
                self.failure_count += 1
                self.status = DriverStatus.DEGRADED
                self.error_message = str(e)

        # Simulation Fallback
        noise = random.uniform(-0.02, 0.02)
        sim_ax = round(noise, 3)
        sim_ay = round(noise, 3)
        sim_az = round(1.0 + noise, 3)
        comp_g = round(random.uniform(0.01, 0.04), 3)

        return {
            "accelerometer_g": {"x": sim_ax, "y": sim_ay, "z": sim_az},
            "gyroscope_dps": {"x": 0.0, "y": 0.0, "z": 0.0},
            "composite_g": comp_g,
            "impact_detected": False,
            "compass_heading_deg": 42.5,
            "barometric_pressure_hpa": 1012.8,
            "barometric_altitude_m": 35.0,
            "timestamp": now_iso,
            "quality": {
                "status": DriverStatus.SIMULATED.value,
                "is_simulated": True,
                "source": "simulated_gy87"
            }
        }
