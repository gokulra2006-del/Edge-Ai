"""
Hardware Driver: Actuators (Traffic Light LEDs, Buzzer, SG90 Servo).
====================================================================
Pin Mapping (from HARDWARE_CONFIG — verified conflict-free):
    RED LED:    GPIO 5  / Physical Pin 29  (via 330Ω resistor)
    YELLOW LED: GPIO 6  / Physical Pin 31  (via 330Ω resistor)
    GREEN LED:  GPIO 13 / Physical Pin 33  (via 330Ω resistor)
    BUZZER:     GPIO 16 / Physical Pin 36  (active-high or PWM)
    SERVO:      GPIO 12 / Physical Pin 32  (Hardware PWM0, 50Hz)

SAFETY RULES:
1. Startup: All LEDs OFF, buzzer OFF, servo at neutral (90°)
2. Shutdown: All LEDs OFF, buzzer OFF, PWM stopped
3. Servo MUST use external 5V power (NOT GPIO12)
4. Servo GND must be connected to Pi GND (common ground)
5. Buzzer auto-cutoff after max continuous duration
6. No rapid servo oscillation — smooth movement with delays
"""
import time
from typing import Any, Dict
from src.modules.logging.logger import LOGGER
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
from src.config.hardware_config import HARDWARE_CONFIG

try:
    import RPi.GPIO as GPIO
    RPI_GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    RPI_GPIO_AVAILABLE = False


class ActuatorDriver(BaseHardwareDriver):
    """Controls LEDs, buzzer, and servo with individual methods and safety limits."""

    def __init__(self):
        super().__init__("GPIO_Actuators", "Multi_Actuator_Output_Controller")
        self._servo_pwm = None
        self._current_servo_angle = HARDWARE_CONFIG.SERVO_DEFAULT_ANGLE
        self._buzzer_active = False
        self._buzzer_start_time = 0.0
        self._traffic_state = "OFF"
        self._barrier_state = "NEUTRAL"
        self._led_states = {"red": False, "yellow": False, "green": False}

        # Read pin assignments from config
        self.pin_red = HARDWARE_CONFIG.PINS["led_red"].bcm
        self.pin_yellow = HARDWARE_CONFIG.PINS["led_yellow"].bcm
        self.pin_green = HARDWARE_CONFIG.PINS["led_green"].bcm
        self.pin_buzzer = HARDWARE_CONFIG.PINS["buzzer"].bcm
        self.pin_servo = HARDWARE_CONFIG.PINS["servo_barrier"].bcm

        self.initialize()

    def initialize(self) -> bool:
        if not RPI_GPIO_AVAILABLE:
            self.status = DriverStatus.SIMULATED
            self.is_simulated = True
            self.error_message = "RPi.GPIO library not detected; running actuators in simulation mode."
            return False

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # Setup LED + Buzzer outputs — ALL start LOW (off)
            for pin in (self.pin_red, self.pin_yellow, self.pin_green, self.pin_buzzer):
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

            # Setup SG90 Servo Hardware PWM0 (50Hz)
            # NOTE: Servo power MUST come from external 5V, NOT from this GPIO pin.
            # This pin provides only the PWM SIGNAL (3.3V logic).
            GPIO.setup(self.pin_servo, GPIO.OUT)
            self._servo_pwm = GPIO.PWM(self.pin_servo, 50)
            # Start at neutral position (90°)
            self._servo_pwm.start(HARDWARE_CONFIG.SERVO_MID_DUTY)
            time.sleep(0.3)
            self._servo_pwm.ChangeDutyCycle(0)  # Stop signal to prevent jitter

            self.status = DriverStatus.ONLINE
            self.is_simulated = False
            self.error_message = None
            LOGGER.info(f"[ActuatorDriver] GPIO pins initialized: "
                        f"RED={self.pin_red}, YELLOW={self.pin_yellow}, GREEN={self.pin_green}, "
                        f"BUZZER={self.pin_buzzer}, SERVO={self.pin_servo}")
            return True
        except Exception as e:
            self.status = DriverStatus.SIMULATED
            self.is_simulated = True
            self.error_message = f"GPIO initialization error: {e}"
            return False

    # ── Individual LED Controls ──────────────────────────────

    def red_on(self):
        """Turns RED LED on."""
        self._set_led("red", self.pin_red, True)

    def red_off(self):
        """Turns RED LED off."""
        self._set_led("red", self.pin_red, False)

    def yellow_on(self):
        """Turns YELLOW LED on."""
        self._set_led("yellow", self.pin_yellow, True)

    def yellow_off(self):
        """Turns YELLOW LED off."""
        self._set_led("yellow", self.pin_yellow, False)

    def green_on(self):
        """Turns GREEN LED on."""
        self._set_led("green", self.pin_green, True)

    def green_off(self):
        """Turns GREEN LED off."""
        self._set_led("green", self.pin_green, False)

    def all_off(self):
        """Turns ALL LEDs and buzzer off."""
        self.red_off()
        self.yellow_off()
        self.green_off()
        self.buzzer_off()

    def all_leds_off(self):
        """Turns all status LEDs off without affecting buzzer."""
        self.red_off()
        self.yellow_off()
        self.green_off()

    def _set_led(self, name: str, pin: int, state: bool):
        """Sets an individual LED state."""
        self._led_states[name] = state
        if not self.is_simulated:
            try:
                GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
            except Exception as e:
                LOGGER.error(f"[ActuatorDriver] LED {name} write error: {e}")
        else:
            LOGGER.debug(f"[ActuatorDriver-Sim] {name.upper()} LED -> {'ON' if state else 'OFF'}")

    def set_traffic_light(self, state: str):
        """Sets traffic light mode: RED, YELLOW, GREEN, or OFF."""
        state = state.upper().strip()
        self._traffic_state = state
        self.all_off()

        if state == "RED":
            self.red_on()
        elif state in ("YELLOW", "AMBER", "CAUTION"):
            self.yellow_on()
        elif state in ("GREEN", "CLEAR"):
            self.green_on()
        # "OFF" leaves everything off (handled by all_off above)

    # ── Buzzer Controls ──────────────────────────────────────

    def buzzer_on(self):
        """Turns buzzer on with safety timeout tracking."""
        self._buzzer_active = True
        if self._buzzer_start_time == 0.0:
            self._buzzer_start_time = time.time()

        if not self.is_simulated:
            try:
                GPIO.output(self.pin_buzzer, GPIO.HIGH)
            except Exception as e:
                LOGGER.error(f"[ActuatorDriver] Buzzer write error: {e}")

    def buzzer_off(self):
        """Turns buzzer off."""
        self._buzzer_active = False
        self._buzzer_start_time = 0.0
        if not self.is_simulated:
            try:
                GPIO.output(self.pin_buzzer, GPIO.LOW)
            except Exception as e:
                LOGGER.error(f"[ActuatorDriver] Buzzer write error: {e}")

    def set_buzzer(self, state: bool):
        """Sets buzzer state boolean (True = ON, False = OFF)."""
        if state:
            self.buzzer_on()
        else:
            self.buzzer_off()

    def beep(self, duration_ms: int = 200, count: int = 1, pause_ms: int = 150):
        """
        Produces short beeps.

        Args:
            duration_ms: Duration of each beep in milliseconds
            count: Number of beeps
            pause_ms: Pause between beeps in milliseconds
        """
        for i in range(count):
            self.buzzer_on()
            time.sleep(duration_ms / 1000.0)
            self.buzzer_off()
            if i < count - 1:
                time.sleep(pause_ms / 1000.0)

    def emergency_alert(self):
        """Plays an emergency alert pattern: 3 rapid beeps."""
        self.beep(duration_ms=150, count=3, pause_ms=100)

    def _check_buzzer_safety(self):
        """Auto-cutoff if buzzer exceeds max continuous duration."""
        if self._buzzer_active and self._buzzer_start_time > 0:
            elapsed = time.time() - self._buzzer_start_time
            if elapsed > HARDWARE_CONFIG.BUZZER_MAX_CONTINUOUS_SEC:
                LOGGER.warning("[ActuatorDriver] Buzzer exceeded max continuous duration; auto-silencing.")
                self.buzzer_off()

    # ── Servo Controls ───────────────────────────────────────

    def set_servo_angle(self, angle: float):
        """
        Sets the servo to a specific angle with smooth movement.

        Args:
            angle: Target angle (clamped to configured min/max limits)
        """
        # Clamp to safe limits
        angle = max(HARDWARE_CONFIG.SERVO_MIN_ANGLE, min(HARDWARE_CONFIG.SERVO_MAX_ANGLE, angle))

        if not self.is_simulated and self._servo_pwm:
            try:
                # Convert angle to duty cycle
                # 0° = 2.5% duty, 180° = 12.5% duty (linear interpolation)
                duty = HARDWARE_CONFIG.SERVO_MIN_DUTY + (
                    (angle / 180.0) * (HARDWARE_CONFIG.SERVO_MAX_DUTY - HARDWARE_CONFIG.SERVO_MIN_DUTY)
                )
                self._servo_pwm.ChangeDutyCycle(duty)
                time.sleep(0.3)  # Allow servo to reach position
                self._servo_pwm.ChangeDutyCycle(0)  # Stop signal to prevent jitter
            except Exception as e:
                LOGGER.error(f"[ActuatorDriver] Servo error: {e}")
        else:
            LOGGER.debug(f"[ActuatorDriver-Sim] Servo -> {angle}°")

        self._current_servo_angle = angle

    def servo_neutral(self):
        """Moves servo to neutral/safe position (default 90°)."""
        self._barrier_state = "NEUTRAL"
        self.set_servo_angle(HARDWARE_CONFIG.SERVO_DEFAULT_ANGLE)

    def set_barrier(self, state: str):
        """Sets barrier state: OPEN, CLOSED, or NEUTRAL."""
        state = state.upper().strip()
        self._barrier_state = state
        if state == "CLOSED":
            self.set_servo_angle(HARDWARE_CONFIG.SERVO_MIN_ANGLE)
        elif state == "OPEN":
            self.set_servo_angle(HARDWARE_CONFIG.SERVO_MAX_ANGLE)
        else:
            self.servo_neutral()

    # ── Status & Cleanup ─────────────────────────────────────

    def read(self) -> Dict[str, Any]:
        """Returns the current state of all physical actuators."""
        self._check_buzzer_safety()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {
            "leds": {
                "red": self._led_states["red"],
                "yellow": self._led_states["yellow"],
                "green": self._led_states["green"],
            },
            "buzzer": {
                "active": self._buzzer_active,
                "gpio": self.pin_buzzer,
            },
            "servo": {
                "angle": self._current_servo_angle,
                "gpio": self.pin_servo,
                "note": "Signal pin only. External 5V power required.",
            },
            "timestamp": now_iso,
            "quality": {
                "status": self.status.value,
                "is_simulated": self.is_simulated,
                "source": "physical_gpio_actuators" if not self.is_simulated else "simulated_actuators"
            }
        }

    def cleanup(self):
        """Safe GPIO shutdown — all LEDs off, buzzer off, PWM stopped."""
        if not self.is_simulated:
            try:
                # Turn everything off
                for pin in (self.pin_red, self.pin_yellow, self.pin_green, self.pin_buzzer):
                    try:
                        GPIO.output(pin, GPIO.LOW)
                    except Exception:
                        pass

                if self._servo_pwm:
                    self._servo_pwm.stop()

                GPIO.cleanup()
                LOGGER.info("[ActuatorDriver] GPIO pins cleaned up safely.")
            except Exception as e:
                LOGGER.warning(f"[ActuatorDriver] Cleanup warning: {e}")

        self._led_states = {"red": False, "yellow": False, "green": False}
        self._buzzer_active = False
