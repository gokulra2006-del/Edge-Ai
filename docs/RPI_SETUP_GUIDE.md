# Raspberry Pi 4 Multi-Sensor Hardware Integration Guide
## SENTINEL-AI Autonomous Edge Protection Node

This guide provides the complete, authoritative hardware and software integration manual for deploying SENTINEL-AI to a physical **Raspberry Pi 4 Model B**.

---

## 1. GPIO Pinout & Hardware Architecture

All software references use **BCM GPIO numbering**. Physical pin references correspond to the 40-pin Raspberry Pi J8 header.

| Sensor / Actuator | Signal Function | BCM GPIO | Physical Pin | Voltage Level | Notes |
|---|---|---|---|---|---|
| **Power Rails** | 3.3V Power | - | Pin 1, 17 | 3.3V DC | For 3.3V logic & sensors |
| **Power Rails** | 5.0V Power | - | Pin 2, 4 | 5.0V DC | For MQ-2 heater, Servo, LCD |
| **Ground** | Common Ground | - | Pin 6, 9, 14, 20, 25, 30, 34, 39 | 0V | **All grounds must be tied together** |
| **GY-87 10-DOF** | I2C1 SDA | GPIO 2 | Pin 3 | 3.3V | 0x68 (MPU6050), 0x1E (HMC), 0x77 (BMP) |
| **GY-87 10-DOF** | I2C1 SCL | GPIO 3 | Pin 5 | 3.3V | 100 kHz standard / 400 kHz fast |
| **DHT22** | One-Wire Data | GPIO 4 | Pin 7 | 3.3V | Requires 4.7k-10k pull-up to 3.3V |
| **Status LED: Red** | Active High | GPIO 5 | Pin 29 | 3.3V | 220Ω-330Ω series resistor |
| **Status LED: Yellow** | Active High | GPIO 6 | Pin 31 | 3.3V | 220Ω-330Ω series resistor |
| **Status LED: Green** | Active High | GPIO 13 | Pin 33 | 3.3V | 220Ω-330Ω series resistor |
| **SG90 Micro Servo** | Hardware PWM0 | GPIO 12 | Pin 32 | 3.3V (Signal) | **Power from 5V rail, NOT GPIO** |
| **NEO-6M GPS** | UART0 TXD | GPIO 14 | Pin 8 | 3.3V | Connects to GPS RX |
| **NEO-6M GPS** | UART0 RXD | GPIO 15 | Pin 10 | 3.3V | Connects to GPS TX (9600 baud) |
| **Active Buzzer** | Alert Tone | GPIO 16 | Pin 36 | 3.3V | HIGH = ON, LOW = OFF |
| **INMP441 Mic** | I2S Bit Clock (SCK) | GPIO 18 | Pin 12 | 3.3V | Audio PCM Clock |
| **INMP441 Mic** | I2S Word Select (WS) | GPIO 19 | Pin 35 | 3.3V | Left/Right Frame Clock |
| **INMP441 Mic** | I2S Data (SD) | GPIO 20 | Pin 38 | 3.3V | Serial PCM In |
| **HD44780 16x2 LCD** | Register Select (RS) | GPIO 21 | Pin 40 | 3.3V | Command (0) / Data (1) |
| **HD44780 16x2 LCD** | Enable (E) | GPIO 22 | Pin 15 | 3.3V | Clock latch pulse |
| **HD44780 16x2 LCD** | Data Bit 4 (D4) | GPIO 23 | Pin 16 | 3.3V | 4-bit bus lower nibble |
| **HD44780 16x2 LCD** | Data Bit 5 (D5) | GPIO 24 | Pin 18 | 3.3V | 4-bit bus |
| **HD44780 16x2 LCD** | Data Bit 6 (D6) | GPIO 25 | Pin 22 | 3.3V | 4-bit bus |
| **HD44780 16x2 LCD** | Data Bit 7 (D7) | GPIO 26 | Pin 37 | 3.3V | 4-bit bus upper nibble |
| **ADS1115 ADC** | I2C1 SDA / SCL | GPIO 2, 3 | Pin 3, 5 | 3.3V | Address 0x48 (ADDR -> GND) |
| **MQ-2 Gas / Smoke** | Analog Output | ADS1115 A0 | Via Divider | **< 3.3V** | **10k/20k resistor divider mandatory!** |
| **Camera** | CSI-2 Ribbon Cable | CSI Port | Camera Port | 3.3V / MIPI | Blue backing faces Ethernet/USB |

---

## 2. Electrical Safety & Protection Rules

> [!CAUTION]
> Raspberry Pi GPIO pins operate strictly at **3.3V logic**. Connecting 5V directly to ANY Raspberry Pi GPIO pin will destroy the SoC pin driver permanently.

1. **MQ-2 Gas Sensor Protection:**
   - The MQ-2 internal heater requires **5V** to operate.
   - The analog output ($V_{out}$) can reach 5.0V during high smoke concentration.
   - You **MUST** run the MQ-2 analog output through a voltage divider before connecting to ADS1115 A0:
     ```
     MQ-2 AOUT ───[ 10kΩ ]───┬───> To ADS1115 AIN0
                             │
                          [ 20kΩ ]
                             │
                            GND
     ```
     Ratio: $V_{in\_adc} = V_{sensor} \times \frac{20k}{10k + 20k} = V_{sensor} \times 0.667$.
     Max voltage at ADS1115 is $5.0V \times 0.667 = 3.33V$ (safe).

2. **SG90 Servo Power Isolation:**
   - Servos draw peak surge currents up to 500mA-1A during movement.
   - Connect Servo Red wire to Pin 2/4 (5V rail) or an external 5V 2A regulator.
   - **NEVER** power the servo from 3.3V (Pin 1) or from a GPIO pin directly.

3. **Common Ground:**
   - All modules (Pi, GY-87, ADS1115, MQ-2, GPS, Mic, LCD, Servo) **must share a common ground (GND)**. Without a common ground reference, analog and serial signals will float.

---

## 3. Raspberry Pi OS Configuration

### A. Enable Interfaces via raspi-config
Open the Raspberry Pi configuration utility:
```bash
sudo raspi-config
```
Navigate and enable:
- **Interface Options** -> **I2C** -> **Enable**
- **Interface Options** -> **Serial Port**:
  - *"Would you like a login shell to be accessible over serial?"* -> **NO**
  - *"Would you like the serial port hardware to be enabled?"* -> **YES**
- **Interface Options** -> **Camera** -> **Enable** (if running legacy Bullseye; on Bookworm camera is enabled by default)

### B. Configure `/boot/firmware/config.txt` (or `/boot/config.txt`)
Edit the boot configuration:
```bash
sudo nano /boot/firmware/config.txt
```
Ensure the following lines exist:
```ini
# Enable I2C bus at 400kHz fast mode
dtparam=i2c_arm=on
dtparam=i2c_arm_baudrate=400000

# Enable Primary UART on GPIO 14/15
enable_uart=1

# Enable I2S Audio Microphone Overlay (INMP441)
dtoverlay=googlevoicehat-soundcard

# Camera Support (Modern libcamera / Picam)
camera_auto_detect=1
```
Save with `Ctrl+O`, `Enter`, and exit with `Ctrl+X`.
Reboot the Raspberry Pi:
```bash
sudo reboot
```

---

## 4. Software Installation & Environment Setup

### A. Clone Repository & Install System Dependencies
```bash
# Update APT package indexes
sudo apt-get update && sudo apt-get upgrade -y

# Install required system libraries and build tools
sudo apt-get install -y python3-pip python3-venv python3-dev \
    i2c-tools libgpiod2 portaudio19-dev python3-pyaudio \
    python3-opencv libcap-dev git alsa-utils

# Navigate to project directory
cd ~/Edge-AI
```

### B. Python Virtual Environment (System Packages Accessible)
On Raspberry Pi OS Bookworm (PEP 668), use a virtual environment with `--system-site-packages`:
```bash
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install --upgrade pip
pip install -r src/rpi/requirements_rpi.txt
```

### C. Verify Hardware Buses
Run the built-in bus diagnostic:
```bash
# Verify I2C bus devices (should show 0x48 and 0x68)
sudo i2cdetect -y 1

# Verify serial port exists
ls -l /dev/serial0

# Verify ALSA capture device exists
arecord -l
```

---

## 5. Step-by-Step Diagnostic Test Suite

Run each individual test script in `src/rpi/tests/` to verify hardware step-by-step:

| Script | Purpose | Expected Output |
|---|---|---|
| `python3 src/rpi/tests/test_01_gpio.py` | GPIO Library Check | `RESULT: PASS` (BCM mode OK) |
| `python3 src/rpi/tests/test_02_i2c_scan.py` | I2C Bus Scan | Shows `0x68` (MPU6050), `0x48` (ADS1115), etc. |
| `python3 src/rpi/tests/test_03_gy87.py` | GY-87 10-DOF IMU | Reads live Accelerometer X, Y, Z in $g$ |
| `python3 src/rpi/tests/test_04_ads1115.py` | ADS1115 16-bit ADC | Reads raw ADC counts & voltage on A0 |
| `python3 src/rpi/tests/test_05_dht22.py` | DHT22 Temp / Hum | Temperature °C and Humidity % readings |
| `python3 src/rpi/tests/test_06_mq2.py` | MQ-2 Gas & Smoke | Voltage & Relative Gas Level (0-1000) |
| `python3 src/rpi/tests/test_07_gps.py` | NEO-6M GPS Module | NMEA sentences, satellite count & fix |
| `python3 src/rpi/tests/test_08_leds.py` | Status LEDs | Sequentially cycles Red -> Yellow -> Green |
| `python3 src/rpi/tests/test_09_buzzer.py` | Active Buzzer | 3 short beeps + 1 long alert tone |
| `python3 src/rpi/tests/test_10_servo.py` | SG90 Servo Actuator | Sweeps 90° -> 0° -> 180° -> 90° |
| `python3 src/rpi/tests/test_11_inmp441.py` | INMP441 Microphone | Captures audio RMS & sound level in dB |
| `python3 src/rpi/tests/test_12_lcd.py` | HD44780 16x2 LCD | Displays "SENTINEL-AI SYSTEM ONLINE" |
| `python3 src/rpi/tests/test_13_camera.py` | CSI / V4L2 Camera | Captures test frame to `/tmp/sentinel_cam_test.jpg` |
| **`python3 src/rpi/tests/test_14_full_integration.py`** | **Master Integration Suite** | **Probes all 10 subsystems simultaneously** |

---

## 6. Running the Production Edge Node

### A. Interactive Execution
```bash
source venv/bin/activate
python3 src/rpi/app/main.py
```
Options:
- `--debug-gps`: Log raw incoming NMEA sentences for debugging.

The edge node will:
1. Probe and initialize all 10 hardware subsystems.
2. Initialize HD44780 LCD with boot splash.
3. Start real-time fault-tolerant sensor acquisition loop (1 Hz).
4. Evaluate multi-sensor thresholds via `AlertEngine`.
5. Update LCD display lines in real-time.
6. Trigger traffic-light LEDs and buzzer on critical alerts.
7. Print formatted telemetry snapshots to standard output.

### B. Auto-Start as a systemd Background Service
To run SENTINEL-AI automatically on boot:

1. Create a service file:
```bash
sudo nano /etc/systemd/system/sentinel-ai.service
```
2. Paste configuration (adjust `/home/pi` if using a different username):
```ini
[Unit]
Description=SENTINEL-AI Multi-Sensor Edge Node
After=network.target sound.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Edge-AI
ExecStart=/home/pi/Edge-AI/venv/bin/python3 src/rpi/app/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```
3. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sentinel-ai.service
sudo systemctl start sentinel-ai.service
```
4. Check service status and live logs:
```bash
sudo systemctl status sentinel-ai.service
journalctl -u sentinel-ai.service -f
```

---

## 7. Troubleshooting & Common Pitfalls

| Symptom | Probable Cause | Solution |
|---|---|---|
| `I2C device 0x68 / 0x48 not found` | Loose SDA/SCL wire or missing 3.3V power | Reseat SDA (Pin 3) and SCL (Pin 5). Verify `sudo i2cdetect -y 1`. |
| `DHT22 returns None or checksum error` | Missing pull-up resistor or polling too fast | Add a 4.7kΩ resistor between Pin 1 (3.3V) and Pin 7 (DATA). Max sample rate is 0.5 Hz (2 sec). |
| `MQ-2 sensor reads 0V constantly` | Missing 5V heater power | MQ-2 heater **requires 5V** (Pin 2). Verify heater gets warm to the touch after 2 minutes. |
| `GPS sentences not arriving` | TX/RX swapped | Connect GPS **TX** -> Pi **RX** (Pin 10), GPS **RX** -> Pi **TX** (Pin 8). |
| `GPS fix remains NO_FIX` | Operating indoors | GPS signals cannot penetrate thick concrete. Place antenna near an open window or outdoors for 5-10 mins. |
| `LCD displays black blocks on line 1` | Contrast pin (V0) incorrect or init incomplete | Adjust 10k contrast potentiometer on V0 pin until characters are clearly readable. |
| `Servo jitters or resets Pi` | Power surge on 5V rail | Add a 100uF-470uF electrolytic capacitor across 5V and GND near the servo, or use separate 5V PSU. |
| `Mic capture returns zero/silence` | Missing kernel I2S overlay | Add `dtoverlay=googlevoicehat-soundcard` to `/boot/firmware/config.txt` and reboot. |
