"""
SENTINEL-AI Central Hardware Configuration & Pin Allocation Registry.
=====================================================================
Target Board: Raspberry Pi 4 Model B

BCM numbering is used strictly across all software drivers.
Physical pin numbers are documented for wiring integrity.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass(frozen=True)
class PinDefinition:
    bcm: int
    physical: int
    role: str
    desc: str
    voltage: str = "3.3V"


@dataclass
class HardwareConfiguration:
    # Target Board Information
    board_model: str = "Raspberry Pi 4 Model B"
    architecture: str = "ARMv8 (Cortex-A72)"
    operating_system: str = "Raspberry Pi OS (64-bit)"

    # Interfaces
    i2c_bus_path: str = "/dev/i2c-1"
    i2c_bus_num: int = 1
    uart_device: str = "/dev/serial0"
    uart_baud_rate: int = 9600
    camera_device: str = "/dev/video0"

    # Master Conflict-Free Pin Registry
    # All BCM pins are unique; zero pin conflicts exist.
    PINS: Dict[str, PinDefinition] = field(default_factory=lambda: {
        # Single-Wire Digital Sensor
        "dht22_data": PinDefinition(bcm=4, physical=7, role="DIGITAL_IN", desc="DHT-22 Temp & Humidity (4.7k pull-up to 3.3V)"),

        # I2C Bus 1 (Physical Pins 3 & 5)
        "i2c_sda": PinDefinition(bcm=2, physical=3, role="I2C_SDA", desc="I2C Data Bus (GY-87 + ADS1115)"),
        "i2c_scl": PinDefinition(bcm=3, physical=5, role="I2C_SCL", desc="I2C Clock Bus (GY-87 + ADS1115)"),

        # GPS NEO-6M UART (Physical Pins 8 & 10)
        "gps_tx_pi_rx": PinDefinition(bcm=15, physical=10, role="UART_RX", desc="GPS Module TX -> RPi RX (GPIO 15)"),
        "gps_rx_pi_tx": PinDefinition(bcm=14, physical=8, role="UART_TX", desc="GPS Module RX <- RPi TX (GPIO 14)"),

        # I2S MEMS Microphone INMP441 (Physical Pins 12, 35, 38)
        "inmp441_sck": PinDefinition(bcm=18, physical=12, role="I2S_BCLK", desc="I2S Serial Clock / Bit Clock"),
        "inmp441_ws": PinDefinition(bcm=19, physical=35, role="I2S_LRCLK", desc="I2S Word Select / Frame Sync"),
        "inmp441_sd": PinDefinition(bcm=20, physical=38, role="I2S_DIN", desc="I2S Serial Data Input"),

        # Actuators: Traffic Light LEDs
        "led_red": PinDefinition(bcm=5, physical=29, role="OUTPUT", desc="Traffic Light RED LED (330 ohm resistor)"),
        "led_yellow": PinDefinition(bcm=6, physical=31, role="OUTPUT", desc="Traffic Light YELLOW LED (330 ohm resistor)"),
        "led_green": PinDefinition(bcm=13, physical=33, role="OUTPUT", desc="Traffic Light GREEN LED (330 ohm resistor)"),

        # Actuator: Emergency Siren Buzzer
        "buzzer": PinDefinition(bcm=16, physical=36, role="OUTPUT", desc="Buzzer module I/O (active-high or PWM)"),

        # Actuator: Emergency Barrier Servo
        "servo_barrier": PinDefinition(bcm=12, physical=32, role="PWM0", desc="SG90 Access Barrier Servo (Hardware PWM0, 50Hz)"),

        # LCD 16x2 in 4-bit mode (Physical Pins 40, 15, 16, 18, 22, 37)
        # WARNING: LCD is 5V powered. Raspberry Pi GPIO is 3.3V logic.
        # Direct wiring works on MOST LCDs because they accept 3.3V as logic HIGH,
        # but this is NOT electrically ideal. For production, use a level-shifter
        # (e.g., 74HC245 or TXS0108E) between Pi GPIOs and LCD data/control pins.
        "lcd_rs": PinDefinition(bcm=21, physical=40, role="OUTPUT", desc="LCD Register Select", voltage="3.3V->5V"),
        "lcd_e": PinDefinition(bcm=22, physical=15, role="OUTPUT", desc="LCD Enable strobe", voltage="3.3V->5V"),
        "lcd_d4": PinDefinition(bcm=23, physical=16, role="OUTPUT", desc="LCD Data bit 4", voltage="3.3V->5V"),
        "lcd_d5": PinDefinition(bcm=24, physical=18, role="OUTPUT", desc="LCD Data bit 5", voltage="3.3V->5V"),
        "lcd_d6": PinDefinition(bcm=25, physical=22, role="OUTPUT", desc="LCD Data bit 6", voltage="3.3V->5V"),
        "lcd_d7": PinDefinition(bcm=26, physical=37, role="OUTPUT", desc="LCD Data bit 7", voltage="3.3V->5V"),
    })

    # I2C Addresses
    I2C_ADDRESSES: Dict[str, int] = field(default_factory=lambda: {
        "MPU6050": 0x68,      # GY-87 6-DOF Accel/Gyro
        "HMC5883L": 0x1E,     # GY-87 3-axis Magnetometer / Compass (via MPU-6050 bypass)
        "QMC5883L_ALT": 0x0D, # Alternative Magnetometer chip found on some GY-87 revisions
        "BMP180": 0x77,       # GY-87 Barometric Pressure & Altitude
        "ADS1115": 0x48       # 16-bit ADC for MQ-2 Smoke/Gas Sensor
    })

    # Sensor Polling Intervals (seconds)
    POLL_INTERVALS: Dict[str, float] = field(default_factory=lambda: {
        "dht22": 2.0,         # Minimum 1.5s required between physical DHT reads
        "gy87_imu": 0.1,      # 10 Hz IMU telemetry loop
        "gps": 1.0,           # 1 Hz GPS fix cycle
        "ads1115_gas": 0.2,   # 5 Hz Gas/Smoke monitoring
        "audio": 0.5,         # 2 Hz acoustic SPL & classifier window
        "camera": 0.066,      # ~15 FPS video pipeline
        "lcd": 1.0,           # 1 Hz LCD display update
    })

    # MQ-2 Gas/Smoke Sensor Configuration
    # The MQ-2 AOUT is connected through a voltage divider (10k top / 20k bottom)
    # to the ADS1115 A0 input. This reduces 5V-range MQ-2 output to ~1.67V max
    # which is safe for the ADS1115 operating at 3.3V VDD.
    MQ2_WARMUP_SECONDS: float = 60.0          # Minimum heater warm-up before readings are stable
    MQ2_VOLTAGE_DIVIDER_RATIO: float = 1 / 3  # 20k / (10k + 20k) = voltage at ADC / original voltage
    MQ2_ADS1115_CHANNEL: int = 0              # AIN0

    # Hardware Safety Bounds
    SERVO_MIN_DUTY: float = 2.5     # 0 degrees (CLOSED) ~ 500us
    SERVO_MAX_DUTY: float = 12.5    # 180 degrees ~ 2500us
    SERVO_MID_DUTY: float = 7.5     # 90 degrees (OPEN) ~ 1500us
    SERVO_MIN_ANGLE: float = 0.0    # Minimum allowed angle
    SERVO_MAX_ANGLE: float = 180.0  # Maximum allowed angle
    SERVO_DEFAULT_ANGLE: float = 90.0  # Neutral / safe position
    BUZZER_MAX_CONTINUOUS_SEC: float = 15.0  # Automatic safety cutoff for acoustic siren

    # Alert Thresholds (all configurable, NOT hardcoded)
    ALERT_THRESHOLDS: Dict[str, float] = field(default_factory=lambda: {
        "high_temperature_c": 50.0,       # Celsius
        "high_humidity_pct": 90.0,        # Percent
        "gas_level_warning": 1.5,         # Voltage at ADC (relative, not PPM)
        "gas_level_critical": 2.5,        # Voltage at ADC (relative, not PPM)
        "imu_impact_g": 2.5,              # G-force threshold for impact detection
        "imu_tilt_deg": 45.0,             # Degree tilt threshold
    })

    # Global Simulation Fallback Enable
    allow_simulation_fallback: bool = True

    def validate_pin_assignments(self) -> List[str]:
        """Checks for duplicate physical or BCM pin assignments."""
        errors = []
        seen_bcm = {}
        seen_phys = {}

        for name, pin in self.PINS.items():
            if pin.bcm in seen_bcm:
                errors.append(f"BCM GPIO conflict: {pin.bcm} assigned to both '{seen_bcm[pin.bcm]}' and '{name}'")
            seen_bcm[pin.bcm] = name

            if pin.physical in seen_phys:
                errors.append(f"Physical Pin conflict: Pin {pin.physical} assigned to both '{seen_phys[pin.physical]}' and '{name}'")
            seen_phys[pin.physical] = name

        return errors


HARDWARE_CONFIG = HardwareConfiguration()
