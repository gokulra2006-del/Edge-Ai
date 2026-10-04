"""
Module 1 Hardware Foundation: Physical GPIO Actuator Driver.
============================================================
Drives real physical actuators on Raspberry Pi 4 Model B:
- Traffic Signal LEDs: RED (BCM 22), YELLOW (BCM 27), GREEN (BCM 23)
- Emergency Barrier Servo: SG90 on BCM 12 (Hardware PWM0, 50Hz)
- Acoustic Siren Buzzer: BCM 24 (Active High)

Gracefully falls back to mock software logging if running on non-Pi development host.
"""
import time
from typing import Any, Dict, Optional
from src.modules.logging.logger import LOGGER
from src.modules.sensors.gpio_registry import GPIO_REGISTRY

try:
    import RPi.GPIO as GPIO
    RPI_GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    RPI_GPIO_AVAILABLE = False


class PhysicalGPIODriver:
    """
    Direct hardware driver for traffic lights, access barrier servo, and alert buzzer.
    """

    def __init__(self):
        self.is_hardware_active = False
        self._servo_pwm = None
        self._current_traffic_state = "GREEN"
        self._current_barrier_state = "OPEN"
        self._current_buzzer_state = False

        self._init_gpio()

    def _init_gpio(self):
        if not RPI_GPIO_AVAILABLE:
            LOGGER.info("[GPIODriver] Running in software mock mode (RPi.GPIO not detected).")
            return

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # 1. Traffic LEDs (Outputs)
            pin_red = GPIO_REGISTRY.get_pin("traffic_red")
            pin_yellow = GPIO_REGISTRY.get_pin("traffic_yellow")
            pin_green = GPIO_REGISTRY.get_pin("traffic_green")
            for p in (pin_red, pin_yellow, pin_green):
                GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)

            # 2. Siren Buzzer (Output)
            pin_buzzer = GPIO_REGISTRY.get_pin("siren_buzzer")
            GPIO.setup(pin_buzzer, GPIO.OUT, initial=GPIO.LOW)

            # 3. Barrier Servo (PWM 50Hz)
            pin_servo = GPIO_REGISTRY.get_pin("barrier_servo")
            GPIO.setup(pin_servo, GPIO.OUT)
            self._servo_pwm = GPIO.PWM(pin_servo, 50)  # 50 Hz cycle
            self._servo_pwm.start(7.5)  # 7.5% duty cycle = 90 degrees (OPEN)

            self.is_hardware_active = True
            LOGGER.info("[GPIODriver] Successfully bound all Raspberry Pi GPIO actuators.")
            self.set_traffic_light("GREEN")
        except Exception as e:
            LOGGER.warning(f"[GPIODriver] Could not initialize physical GPIO: {e}. Falling back to mock.")
            self.is_hardware_active = False

    def set_traffic_light(self, color: str):
        """
        Sets traffic signal state: 'RED', 'YELLOW', 'GREEN', or 'OFF'.
        """
        color = color.upper().strip()
        self._current_traffic_state = color

        if not self.is_hardware_active:
            LOGGER.debug(f"[GPIODriver-Mock] Traffic Signal -> {color}")
            return

        try:
            pin_red = GPIO_REGISTRY.get_pin("traffic_red")
            pin_yellow = GPIO_REGISTRY.get_pin("traffic_yellow")
            pin_green = GPIO_REGISTRY.get_pin("traffic_green")

            GPIO.output(pin_red, GPIO.HIGH if color in ("RED", "ALL_RED") else GPIO.LOW)
            GPIO.output(pin_yellow, GPIO.HIGH if color in ("YELLOW", "AMBER", "CAUTION") else GPIO.LOW)
            GPIO.output(pin_green, GPIO.HIGH if color in ("GREEN", "CLEAR") else GPIO.LOW)
        except Exception as e:
            LOGGER.error(f"[GPIODriver] Error setting traffic LEDs: {e}")

    def set_barrier(self, position: str):
        """
        Controls SG90 servo:
        - 'OPEN': 90 degrees (Duty cycle ~7.5%)
        - 'CLOSED': 0 degrees (Duty cycle ~2.5%)
        """
        position = position.upper().strip()
        self._current_barrier_state = position

        if not self.is_hardware_active or not self._servo_pwm:
            LOGGER.debug(f"[GPIODriver-Mock] Barrier Servo -> {position}")
            return

        try:
            duty_cycle = 7.5 if position in ("OPEN", "UP") else 2.5
            self._servo_pwm.ChangeDutyCycle(duty_cycle)
            time.sleep(0.25)
            self._servo_pwm.ChangeDutyCycle(0)
        except Exception as e:
            LOGGER.error(f"[GPIODriver] Error setting barrier servo: {e}")

    def set_buzzer(self, active: bool):
        """Turns active buzzer ON or OFF."""
        self._current_buzzer_state = bool(active)

        if not self.is_hardware_active:
            LOGGER.debug(f"[GPIODriver-Mock] Buzzer -> {'ON' if active else 'OFF'}")
            return

        try:
            pin_buzzer = GPIO_REGISTRY.get_pin("siren_buzzer")
            GPIO.output(pin_buzzer, GPIO.HIGH if active else GPIO.LOW)
        except Exception as e:
            LOGGER.error(f"[GPIODriver] Error setting buzzer: {e}")

    def apply_actuators(self, state: Dict[str, Any]):
        """
        Applies a consolidated actuator dictionary:
        {
            'traffic_signal': 'GREEN' | 'YELLOW' | 'RED',
            'barrier': 'OPEN' | 'CLOSED',
            'buzzer': 'ON' | 'OFF' | True | False
        }
        """
        if "traffic_signal" in state:
            self.set_traffic_light(str(state["traffic_signal"]))
        if "barrier" in state:
            self.set_barrier(str(state["barrier"]))
        if "buzzer" in state:
            buz_val = state["buzzer"]
            self.set_buzzer(buz_val is True or buz_val == "ON")

    def get_state(self) -> Dict[str, Any]:
        return {
            "traffic_signal": self._current_traffic_state,
            "barrier": self._current_barrier_state,
            "buzzer": "ON" if self._current_buzzer_state else "OFF",
            "is_physical_hardware": self.is_hardware_active
        }

    def cleanup(self):
        """Safely reset GPIO on system shutdown."""
        if self.is_hardware_active:
            try:
                if self._servo_pwm:
                    self._servo_pwm.stop()
                GPIO.cleanup()
                LOGGER.info("[GPIODriver] GPIO pins cleaned up successfully.")
            except Exception as e:
                LOGGER.warning(f"[GPIODriver] Cleanup warning: {e}")


GPIO_ACTUATOR = PhysicalGPIODriver()
