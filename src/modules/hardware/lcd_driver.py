"""
Hardware Driver: 16x2 Parallel LCD Display (HD44780 compatible, 4-bit mode).
=============================================================================
Physical Connections:
    LCD Pin 1  VSS  -> GND
    LCD Pin 2  VDD  -> 5V (Physical Pin 2 or 4)
    LCD Pin 3  V0   -> GND (max contrast — use potentiometer for adjustment)
    LCD Pin 4  RS   -> GPIO 21 / Physical Pin 40
    LCD Pin 5  RW   -> GND (write-only mode)
    LCD Pin 6  E    -> GPIO 22 / Physical Pin 15
    LCD Pin 7-10    -> unused (4-bit mode)
    LCD Pin 11 D4   -> GPIO 23 / Physical Pin 16
    LCD Pin 12 D5   -> GPIO 24 / Physical Pin 18
    LCD Pin 13 D6   -> GPIO 25 / Physical Pin 22
    LCD Pin 14 D7   -> GPIO 26 / Physical Pin 37
    LCD Pin 15 A    -> 5V (backlight anode)
    LCD Pin 16 K    -> GND (backlight cathode)

!! HARDWARE WARNING !!
=======================
The LCD module is powered at 5V (VDD) but the Raspberry Pi GPIO outputs
are 3.3V logic. Most HD44780 LCDs will accept 3.3V as logic HIGH because
the threshold is typically ~2.0V, but this is NOT guaranteed by the datasheet.

For a production-quality connection, insert a level shifter (e.g., 74HC245,
TXS0108E, or BSS138 MOSFET module) between the Pi GPIO pins and the LCD
control/data pins.

This driver is written so pin assignments are configurable, making it
straightforward to adapt if a level-shifting buffer is inserted.

CONTRAST NOTE:
V0 tied to GND gives maximum contrast (all pixels dark). If you see solid
blocks instead of text, you need a potentiometer (10kΩ pot between VDD and
GND, wiper to V0) or a fixed resistor (try 2.2kΩ–4.7kΩ from V0 to GND).
"""
import time
from typing import Any, Dict, Optional
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
from src.config.hardware_config import HARDWARE_CONFIG

try:
    import RPi.GPIO as GPIO
    RPI_GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    RPI_GPIO_AVAILABLE = False

# HD44780 command constants
LCD_CMD = False      # RS = LOW for command
LCD_CHR = True       # RS = HIGH for character data
LCD_LINE_1 = 0x80    # DDRAM address for line 1, position 0
LCD_LINE_2 = 0xC0    # DDRAM address for line 2, position 0
LCD_CLEAR = 0x01     # Clear display
LCD_HOME = 0x02      # Return cursor home
LCD_ENTRY_MODE = 0x06  # Increment cursor, no shift
LCD_DISPLAY_ON = 0x0C  # Display ON, cursor OFF, blink OFF
LCD_DISPLAY_OFF = 0x08  # Display OFF
LCD_FUNCTION_4BIT_2LINE = 0x28  # 4-bit mode, 2 lines, 5x8 font

# Timing constants (microseconds)
E_PULSE_US = 50      # Enable pulse width (minimum 450ns, we use 50µs for safety)
E_DELAY_US = 50      # Delay after enable pulse


class LCDDriver(BaseHardwareDriver):
    """
    Driver for HD44780-compatible 16x2 LCD in 4-bit parallel mode.

    Pin assignments are read from HARDWARE_CONFIG and can be overridden
    for use with a level-shifting buffer circuit.
    """

    def __init__(self, columns: int = 16, rows: int = 2):
        super().__init__("LCD_16x2", "Character_Display")
        self.columns = columns
        self.rows = rows

        # Read pin assignments from config
        self.pin_rs = HARDWARE_CONFIG.PINS["lcd_rs"].bcm
        self.pin_e = HARDWARE_CONFIG.PINS["lcd_e"].bcm
        self.pin_d4 = HARDWARE_CONFIG.PINS["lcd_d4"].bcm
        self.pin_d5 = HARDWARE_CONFIG.PINS["lcd_d5"].bcm
        self.pin_d6 = HARDWARE_CONFIG.PINS["lcd_d6"].bcm
        self.pin_d7 = HARDWARE_CONFIG.PINS["lcd_d7"].bcm
        self.data_pins = [self.pin_d4, self.pin_d5, self.pin_d6, self.pin_d7]

        self.initialize()

    def initialize(self) -> bool:
        """Initializes the LCD in 4-bit mode."""
        if not RPI_GPIO_AVAILABLE:
            self.status = DriverStatus.SIMULATED
            self.is_simulated = True
            self.error_message = "RPi.GPIO not available; LCD running in simulation mode."
            return False

        try:
            # Note: GPIO.setmode should already be called by ActuatorDriver.
            # If not, we set it here. setwarnings(False) prevents duplicate warnings.
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # Setup all LCD pins as outputs
            for pin in [self.pin_rs, self.pin_e] + self.data_pins:
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

            # HD44780 initialization sequence for 4-bit mode
            # (must send commands in specific order with specific delays)
            time.sleep(0.05)  # Wait >40ms after power-on

            # Special init: send 0x03 three times (8-bit mode), then switch to 4-bit
            self._write_4bits(0x03)
            time.sleep(0.005)  # Wait >4.1ms
            self._write_4bits(0x03)
            time.sleep(0.001)  # Wait >100µs
            self._write_4bits(0x03)
            time.sleep(0.001)
            self._write_4bits(0x02)  # Switch to 4-bit mode
            time.sleep(0.001)

            # Now in 4-bit mode — configure display
            self._send_command(LCD_FUNCTION_4BIT_2LINE)  # 4-bit, 2 lines, 5x8 font
            self._send_command(LCD_DISPLAY_ON)            # Display on, cursor off
            self._send_command(LCD_CLEAR)                 # Clear display
            time.sleep(0.002)  # Clear command needs 1.52ms
            self._send_command(LCD_ENTRY_MODE)            # Increment cursor

            self.status = DriverStatus.ONLINE
            self.is_simulated = False
            self.error_message = None
            return True

        except Exception as e:
            self.status = DriverStatus.NOT_DETECTED
            self.is_simulated = True
            self.error_message = f"LCD initialization failed: {e}"
            return False

    def _write_4bits(self, value: int):
        """Writes the lower 4 bits of value to the data pins and pulses Enable."""
        bits = [(value >> i) & 1 for i in range(4)]
        for i, pin in enumerate(self.data_pins):
            GPIO.output(pin, bits[i])
        self._pulse_enable()

    def _pulse_enable(self):
        """Sends a pulse on the Enable pin to latch data into the LCD."""
        GPIO.output(self.pin_e, GPIO.LOW)
        time.sleep(E_PULSE_US / 1_000_000)
        GPIO.output(self.pin_e, GPIO.HIGH)
        time.sleep(E_PULSE_US / 1_000_000)
        GPIO.output(self.pin_e, GPIO.LOW)
        time.sleep(E_DELAY_US / 1_000_000)

    def _send_byte(self, value: int, mode: bool):
        """
        Sends a full byte to the LCD in 4-bit mode (two nibble writes).

        Args:
            value: The byte to send (0x00-0xFF)
            mode: False = command, True = character data
        """
        if self.is_simulated:
            return

        GPIO.output(self.pin_rs, GPIO.HIGH if mode else GPIO.LOW)

        # Send high nibble first
        self._write_4bits((value >> 4) & 0x0F)
        # Send low nibble
        self._write_4bits(value & 0x0F)

    def _send_command(self, cmd: int):
        """Sends a command byte to the LCD."""
        self._send_byte(cmd, LCD_CMD)

    def _send_char(self, char_code: int):
        """Sends a character byte to the LCD."""
        self._send_byte(char_code, LCD_CHR)

    # ── Public API ─────────────────────────────────────────────

    def lcd_init(self):
        """Re-initializes the LCD (alias for initialize())."""
        self.initialize()

    def lcd_clear(self):
        """Clears the LCD display and returns cursor to home."""
        if self.is_simulated:
            return
        self._send_command(LCD_CLEAR)
        time.sleep(0.002)

    def lcd_set_cursor(self, col: int, row: int):
        """
        Sets the cursor position.

        Args:
            col: Column (0 to columns-1)
            row: Row (0 or 1 for 16x2)
        """
        if self.is_simulated:
            return
        col = max(0, min(col, self.columns - 1))
        row = max(0, min(row, self.rows - 1))
        address = LCD_LINE_1 if row == 0 else LCD_LINE_2
        self._send_command(address + col)

    def lcd_write(self, text: str, line: int = 0):
        """
        Writes a string to the specified line, padded/truncated to fit.

        Args:
            text: String to display (will be truncated to column width)
            line: 0 for line 1, 1 for line 2
        """
        if self.is_simulated:
            return

        self.lcd_set_cursor(0, line)
        # Pad or truncate to exactly column width
        padded = text.ljust(self.columns)[:self.columns]
        for char in padded:
            self._send_char(ord(char))

    def lcd_display_status(self, line1: str, line2: str):
        """Convenience: writes both lines at once."""
        self.lcd_write(line1, 0)
        self.lcd_write(line2, 1)

    def lcd_display_startup(self):
        """Shows the startup/boot screen."""
        self.lcd_display_status("  SENTINEL-AI   ", "   Booting...   ")

    def read(self) -> Dict[str, Any]:
        """Returns current LCD status information."""
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {
            "display_size": f"{self.columns}x{self.rows}",
            "mode": "4-bit parallel",
            "pins": {
                "RS": f"GPIO{self.pin_rs} (Pin {HARDWARE_CONFIG.PINS['lcd_rs'].physical})",
                "E": f"GPIO{self.pin_e} (Pin {HARDWARE_CONFIG.PINS['lcd_e'].physical})",
                "D4-D7": f"GPIO{self.pin_d4},{self.pin_d5},{self.pin_d6},{self.pin_d7}",
            },
            "timestamp": now_iso,
            "quality": {
                "status": self.status.value,
                "is_simulated": self.is_simulated,
                "source": "physical_lcd_gpio" if not self.is_simulated else "simulated_lcd",
                "warning": "LCD is 5V powered; Pi GPIO is 3.3V. Level shifter recommended."
            }
        }

    def cleanup(self):
        """Clears the display on shutdown."""
        if not self.is_simulated:
            try:
                self.lcd_clear()
                self._send_command(LCD_DISPLAY_OFF)
            except Exception:
                pass
