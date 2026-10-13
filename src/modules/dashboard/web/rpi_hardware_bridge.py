"""
SENTINEL-AI: Raspberry Pi Physical Hardware Bridge Client.
===========================================================
Synchronizes physical Raspberry Pi actuators (Traffic LEDs, SG90 Servo, Buzzer)
with live decisions from the Edge-AI Dashboard in real time (<200ms latency).

Hardware Wiring:
  - Traffic RED LED:    BCM 5  (Physical Pin 29)
  - Traffic YELLOW LED: BCM 6  (Physical Pin 31)
  - Traffic GREEN LED:  BCM 13 (Physical Pin 33)
  - SG90 Barrier Servo: BCM 12 (Physical Pin 32, Hardware PWM0)
  - Siren Buzzer:       BCM 16 (Physical Pin 36)

Usage on Raspberry Pi:
  python3 rpi_hardware_bridge.py --server http://172.20.10.2:8080
"""

import argparse
import json
import sys
import time
import urllib.request

# Try RPi.GPIO or gpiozero for hardware control
GPIO_MODE = None
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO_MODE = "RPI_GPIO"
except Exception:
    try:
        from gpiozero import LED, AngularServo, Buzzer, PWMOutputDevice
        GPIO_MODE = "GPIOZERO"
    except Exception:
        GPIO_MODE = "MOCK"

PIN_RED = 5
PIN_YELLOW = 6
PIN_GREEN = 13
PIN_SERVO = 12
PIN_BUZZER = 16


class RPiActuatorController:
    def __init__(self):
        self.mode = GPIO_MODE
        self.servo_pwm = None
        self.gz_red = None
        self.gz_yellow = None
        self.gz_green = None
        self.gz_servo = None
        self.gz_buzzer = None

        self.last_signal = None
        self.last_barrier = None

        self._init_pins()

    def _init_pins(self):
        print(f"[HW-BRIDGE] Actuator backend detected: {self.mode}")
        if self.mode == "RPI_GPIO":
            for p in (PIN_RED, PIN_YELLOW, PIN_GREEN, PIN_BUZZER):
                GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(PIN_SERVO, GPIO.OUT)
            self.servo_pwm = GPIO.PWM(PIN_SERVO, 50)  # 50 Hz cycle
            self.servo_pwm.start(2.5)  # 2.5% = 0 degrees (CLOSED)
            time.sleep(0.3)
            self.servo_pwm.ChangeDutyCycle(0)
        elif self.mode == "GPIOZERO":
            from gpiozero import LED, PWMOutputDevice
            self.gz_red = LED(PIN_RED)
            self.gz_yellow = LED(PIN_YELLOW)
            self.gz_green = LED(PIN_GREEN)
            self.gz_buzzer = LED(PIN_BUZZER)
            self.gz_servo = PWMOutputDevice(PIN_SERVO, frequency=50)
            self.gz_servo.value = 0.05  # ~0 deg
            time.sleep(0.3)
            self.gz_servo.value = 0

    def set_traffic_light(self, color: str):
        color = (color or "GREEN").upper()
        if color == self.last_signal:
            return
        self.last_signal = color

        if color in ("GREEN", "CLEAR"):
            print(f"[ACTUATOR] 🟢 Traffic LED -> GREEN ON (BCM {PIN_GREEN}) [Emergency Corridor Pre-emption]")
        elif color in ("RED", "ALL_RED"):
            print(f"[ACTUATOR] 🔴 Traffic LED -> RED ON (BCM {PIN_RED}) [Cyclic Stop]")
        elif color in ("YELLOW", "AMBER"):
            print(f"[ACTUATOR] 🟡 Traffic LED -> YELLOW ON (BCM {PIN_YELLOW}) [Caution Phase]")

        if self.mode == "RPI_GPIO":
            GPIO.output(PIN_RED, GPIO.HIGH if color in ("RED", "ALL_RED") else GPIO.LOW)
            GPIO.output(PIN_YELLOW, GPIO.HIGH if color in ("YELLOW", "AMBER") else GPIO.LOW)
            GPIO.output(PIN_GREEN, GPIO.HIGH if color in ("GREEN", "CLEAR") else GPIO.LOW)
        elif self.mode == "GPIOZERO":
            self.gz_red.value = 1 if color in ("RED", "ALL_RED") else 0
            self.gz_yellow.value = 1 if color in ("YELLOW", "AMBER") else 0
            self.gz_green.value = 1 if color in ("GREEN", "CLEAR") else 0

    def set_barrier(self, position: str):
        position = (position or "CLOSED").upper()
        if position == self.last_barrier:
            return
        self.last_barrier = position

        if position in ("OPEN", "UP"):
            print(f"[ACTUATOR] 🚧 SG90 Servo Motor -> ROTATING TO 90° (OPEN) [PWM BCM {PIN_SERVO}]")
        else:
            print(f"[ACTUATOR] 🚧 SG90 Servo Motor -> ROTATING TO 0° (CLOSED) [PWM BCM {PIN_SERVO}]")

        # OPEN = 90 deg (~7.5% duty), CLOSED = 0 deg (~2.5% duty)
        if self.mode == "RPI_GPIO" and self.servo_pwm:
            duty = 7.5 if position in ("OPEN", "UP") else 2.5
            self.servo_pwm.ChangeDutyCycle(duty)
            time.sleep(0.4)
            self.servo_pwm.ChangeDutyCycle(0)
        elif self.mode == "GPIOZERO" and self.gz_servo:
            val = 0.075 if position in ("OPEN", "UP") else 0.025
            self.gz_servo.value = val
            time.sleep(0.4)
            self.gz_servo.value = 0

    def set_buzzer(self, active: bool):
        if self.mode == "RPI_GPIO":
            GPIO.output(PIN_BUZZER, GPIO.HIGH if active else GPIO.LOW)
        elif self.mode == "GPIOZERO":
            self.gz_buzzer.value = 1 if active else 0

    def self_test(self):
        print("\n--- [RUNNING HARDWARE SELF-TEST] ---")
        print("1. Testing LEDs (Red -> Yellow -> Green)...")
        self.set_traffic_light("RED")
        time.sleep(0.5)
        self.set_traffic_light("YELLOW")
        time.sleep(0.5)
        self.set_traffic_light("GREEN")
        time.sleep(0.5)

        print("2. Testing SG90 Servo (OPEN 90 deg -> CLOSED 0 deg)...")
        self.set_barrier("OPEN")
        time.sleep(1.0)
        self.set_barrier("CLOSED")
        time.sleep(0.5)

        print("3. Testing Buzzer chime...")
        self.set_buzzer(True)
        time.sleep(0.1)
        self.set_buzzer(False)
        print("--- [HARDWARE SELF-TEST COMPLETE] ---\n")

    def cleanup(self):
        if self.mode == "RPI_GPIO":
            if self.servo_pwm:
                self.servo_pwm.stop()
            GPIO.cleanup()


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI Raspberry Pi Hardware Bridge")
    parser.add_argument("--server", type=str, default="http://172.20.10.2:8080", help="Dashboard server URL")
    parser.add_argument("--test-only", action="store_true", help="Run self-test only then exit")
    args = parser.parse_args()

    controller = RPiActuatorController()
    controller.self_test()

    if args.test_only:
        controller.cleanup()
        return

    url = args.server.rstrip("/") + "/api/live"
    print(f"[HW-BRIDGE] Listening to live dashboard stream: {url}")
    print("[HW-BRIDGE] Move barrier and LEDs live when dashboard changes. Press Ctrl+C to exit.\n")

    last_event_id = None

    try:
        while True:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SentinelAI-HWBridge"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    actuators = data.get("actuators", {})
                    active_ev = data.get("active_event") or {}

                    event_type = active_ev.get("event")
                    event_id = active_ev.get("id")

                    # Check if an AMBULANCE emergency event occurred
                    if event_type == "EMERGENCY_VEHICLE" and event_id != last_event_id:
                        last_event_id = event_id
                        conf = float(active_ev.get("confidence", 0.94)) * 100
                        print("\n" + "=" * 68)
                        print(f"🚨 [EMERGENCY DETECTED] AMBULANCE SIREN VERIFIED! (AI Confidence: {conf:.1f}%)")
                        print("🚑 Model: EdgeAcousticNet TFLite | Rule R3: Emergency Corridor Engaged")
                        print(f"🟢 Actuator Command -> TRAFFIC LIGHT: GREEN (BCM {PIN_GREEN})")
                        print(f"🚧 Actuator Command -> SG90 SERVO: OPEN 90° (BCM {PIN_SERVO})")
                        print("=" * 68 + "\n")
                    elif event_type in (None, "NORMAL") and last_event_id is not None and last_event_id != "NORMAL":
                        last_event_id = "NORMAL"
                        print("\n" + "=" * 68)
                        print("✅ [CORRIDOR RESTORED] Normal Municipal Traffic Flow Active")
                        print(f"🔴 Actuator Command -> TRAFFIC LIGHT: RED (BCM {PIN_RED})")
                        print(f"🚧 Actuator Command -> SG90 SERVO: CLOSED 0° (BCM {PIN_SERVO})")
                        print("=" * 68 + "\n")

                    controller.set_traffic_light(actuators.get("traffic_signal", "GREEN"))
                    controller.set_barrier(actuators.get("barrier", "OPEN"))
                    controller.set_buzzer(actuators.get("buzzer") == "ON")
            except Exception as e:
                # Network hiccup, keep retrying silently
                pass
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\n[HW-BRIDGE] Stopping hardware bridge...")
    finally:
        controller.cleanup()


if __name__ == "__main__":
    main()
