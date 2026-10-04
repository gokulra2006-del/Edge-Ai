"""
Hardware Utility: UART Manager for GPS Communication.
=====================================================
Physical Interface: /dev/serial0

Connections:
- GPS TX -> Physical Pin 10 (GPIO 15 / RXD) — GPS sends data TO the Pi
- GPS RX -> Physical Pin 8 (GPIO 14 / TXD)  — Pi sends data TO GPS

IMPORTANT Raspberry Pi UART Configuration:
==========================================
The Pi 4 has two UARTs:
  - /dev/ttyAMA0 (PL011 full UART — high quality)
  - /dev/ttyS0 (mini UART — lower quality, affected by CPU clock)

/dev/serial0 is a symlink that points to whichever UART is assigned to
the GPIO header pins 8 & 10.

To configure UART for GPS on Raspberry Pi OS:
1. Run: sudo raspi-config
   -> Interface Options -> Serial Port
   -> "Login shell over serial?" -> NO
   -> "Serial port hardware enabled?" -> YES

2. Or manually edit /boot/config.txt and add:
   enable_uart=1
   dtoverlay=disable-bt    # (optional: gives PL011 UART to GPIO header)

3. Check /boot/cmdline.txt — remove 'console=serial0,115200' if present
   (this prevents the kernel console from consuming GPS data)

4. Reboot after changes.

5. Verify: ls -la /dev/serial0
   Should show: /dev/serial0 -> ttyAMA0 (or ttyS0)
"""
import os
from typing import Any, Dict, Optional
from src.config.hardware_config import HARDWARE_CONFIG


class UARTManager:
    """Manages UART serial port availability and configuration status."""

    def __init__(self):
        self.device = HARDWARE_CONFIG.uart_device
        self.baud_rate = HARDWARE_CONFIG.uart_baud_rate
        self._serial = None

    def check_availability(self) -> Dict[str, Any]:
        """
        Checks if the UART serial device exists and is accessible.
        Does NOT open a persistent connection — that is left to the GPS driver.
        """
        device_exists = os.path.exists(self.device)

        # Check if the symlink resolves correctly
        real_device = None
        if device_exists:
            try:
                real_device = os.path.realpath(self.device)
            except Exception:
                pass

        # Check if Bluetooth is still consuming the PL011 UART
        bt_active = os.path.exists("/dev/ttyAMA0") and real_device and "ttyS0" in real_device

        return {
            "device": self.device,
            "device_exists": device_exists,
            "real_device": real_device,
            "baud_rate": self.baud_rate,
            "bluetooth_may_conflict": bt_active,
            "status": "AVAILABLE" if device_exists else "NOT_FOUND",
            "setup_instructions": self._get_setup_instructions() if not device_exists else None,
        }

    @staticmethod
    def _get_setup_instructions() -> str:
        return (
            "UART not found. On Raspberry Pi, enable with:\n"
            "  1. sudo raspi-config -> Interface Options -> Serial Port\n"
            "     -> Login shell: NO, Serial hardware: YES\n"
            "  2. Add to /boot/config.txt: enable_uart=1\n"
            "  3. Remove 'console=serial0,115200' from /boot/cmdline.txt\n"
            "  4. Reboot"
        )

    def open_serial(self, timeout: float = 0.2):
        """Opens the serial port and returns the connection."""
        if not os.path.exists(self.device):
            return None

        try:
            import serial
            self._serial = serial.Serial(
                port=self.device,
                baudrate=self.baud_rate,
                timeout=timeout
            )
            return self._serial
        except ImportError:
            return None
        except Exception:
            return None

    def close(self):
        """Closes the serial port."""
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None


UART_MANAGER = UARTManager()
