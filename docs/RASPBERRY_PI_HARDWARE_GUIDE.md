# SENTINEL-AI: Raspberry Pi 4 Physical Hardware Connection & Wiring Guide

This guide provides the complete pinout, wiring schematics, and software setup instructions to connect your **physical Raspberry Pi 4 Model B** and multiple sensors to SENTINEL-AI.

---

## 1. Conflict-Free Hardware Pinout & Wiring Matrix

The SENTINEL-AI pinout is designed with **zero GPIO conflicts**, ensuring that I2C buses, digital sensors, PWM servos, and audio subsystems run concurrently without collision.

### Raspberry Pi 40-Pin Header Allocation Table

| Physical Pin # | BCM / GPIO | Signal / Role | Connected Hardware Component | Wiring Color / Notes |
| :---: | :---: | :---: | :---: | :---: |
| **Pin 1** | **3V3** | 3.3V DC Power | **MPU-6050 VCC**, **ADS1115 VDD**, **DHT-22 VCC** | Red (Do NOT connect 5V to 3.3V pins!) |
| **Pin 2** | **5V** | 5.0V DC Power | **MQ-2 Gas Sensor VCC**, **SG90 Servo 5V** | Red / Orange |
| **Pin 3** | **GPIO 2** | I2C1 SDA | **MPU-6050 SDA** & **ADS1115 SDA** | Green (Shared I2C Data bus) |
| **Pin 5** | **GPIO 3** | I2C1 SCL | **MPU-6050 SCL** & **ADS1115 SCL** | Yellow (Shared I2C Clock bus) |
| **Pin 6** | **GND** | Ground | **Common Ground (Sensors & Actuators)** | Black (All grounds tied together) |
| **Pin 7** | **GPIO 4** | Digital Input | **DHT-22 / DHT-11 Data Pin** | White (Requires 4.7kΩ pull-up to 3.3V) |
| **Pin 11** | **GPIO 17** | Digital Input | **MQ-2 Digital Out (DO)** *(Optional alternative to ADC)* | Blue |
| **Pin 13** | **GPIO 27** | Digital Output | **Traffic Light: YELLOW LED** | Yellow wire (via 220Ω resistor to GND) |
| **Pin 15** | **GPIO 22** | Digital Output | **Traffic Light: RED LED** | Red wire (via 220Ω resistor to GND) |
| **Pin 16** | **GPIO 23** | Digital Output | **Traffic Light: GREEN LED** | Green wire (via 220Ω resistor to GND) |
| **Pin 18** | **GPIO 24** | Digital Output | **Active Strobe Buzzer / Siren** | Purple (Driven via 2N2222 NPN or direct) |
| **Pin 32** | **GPIO 12** | Hardware PWM0 | **SG90 Access Barrier Servo (Signal)** | Orange / Yellow wire |
| **USB Port 1** | **USB** | UVC Video | **USB Webcam / Raspberry Pi CSI Camera** | Standard USB connection |
| **USB Port 2** | **USB** | ALSA Audio | **USB Mini Microphone** | Standard USB connection |

---

## 2. Sensor-by-Sensor Detailed Wiring

### Sensor 1: MPU-6050 6-DoF IMU (Collision & Crash Detection)
- **VCC** &rarr; Physical Pin 1 (3.3V)
- **GND** &rarr; Physical Pin 6 (GND)
- **SCL** &rarr; Physical Pin 5 (GPIO 3 / I2C SCL)
- **SDA** &rarr; Physical Pin 3 (GPIO 2 / I2C SDA)
- **AD0** &rarr; GND (Selects default I2C address `0x68`)

### Sensor 2: MQ-2 / MQ-135 Gas & Smoke Sensor (Fire & Smoke Plume)
> [!IMPORTANT]
> The MQ-2 heater requires **5V**, but Raspberry Pi GPIOs are only **3.3V tolerant**.
> - **Method A (Analog with ADS1115 ADC - Recommended)**:
>   - MQ-2 VCC &rarr; Physical Pin 2 (5V)
>   - MQ-2 GND &rarr; Common GND
>   - MQ-2 A0 (Analog Out) &rarr; ADS1115 Pin `AIN0`
>   - ADS1115 VDD &rarr; Physical Pin 1 (3.3V)
>   - ADS1115 GND &rarr; Common GND
>   - ADS1115 SDA &rarr; Physical Pin 3 (I2C SDA)
>   - ADS1115 SCL &rarr; Physical Pin 5 (I2C SCL)
> - **Method B (Digital Direct - Without ADC)**:
>   - MQ-2 VCC &rarr; Physical Pin 2 (5V)
>   - MQ-2 GND &rarr; Common GND
>   - MQ-2 D0 (Digital Out) &rarr; Physical Pin 11 (GPIO 17)

### Sensor 3: DHT-22 / DHT-11 Temperature & Humidity Sensor (Heat Spike Detection)
- **VCC** &rarr; Physical Pin 1 (3.3V)
- **GND** &rarr; Common GND
- **DATA** &rarr; Physical Pin 7 (GPIO 4)
  *(If using a bare 4-pin DHT sensor, connect a 4.7kΩ or 10kΩ resistor between VCC and DATA)*

### Sensor 4 & 5: Vision & Audio Peripherals
- **Camera**: Plug USB webcam into any USB 3.0 port, or connect Raspberry Pi Camera Module into the CSI ribbon connector.
- **Microphone**: Plug USB Mini Microphone into any available USB port.

### Actuators: Traffic Signals, Barrier Servo & Siren Buzzer
- **RED LED**: Anode (+) to Pin 15 (GPIO 22) through 220Ω resistor; Cathode (-) to GND.
- **YELLOW LED**: Anode (+) to Pin 13 (GPIO 27) through 220Ω resistor; Cathode (-) to GND.
- **GREEN LED**: Anode (+) to Pin 16 (GPIO 23) through 220Ω resistor; Cathode (-) to GND.
- **Active Buzzer**: VCC (+) to Pin 18 (GPIO 24); GND (-) to GND.
- **SG90 Servo**: Red to 5V (Pin 2); Brown to GND (Pin 6); Orange/Yellow (Signal) to Pin 32 (GPIO 12).

---

## 3. Raspberry Pi Software Setup Instructions

### Step 1: Enable Hardware Interfaces on Raspberry Pi OS
Open a terminal on your Raspberry Pi and enable I2C and Camera interfaces:
```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_camera 0
```

### Step 2: Install System Packages
```bash
sudo apt-get update
sudo apt-get install -y i2c-tools python3-smbus python3-pip python3-dev libcap-dev portaudio19-dev ffmpeg
```

Verify I2C devices are detected on the bus:
```bash
i2cdetect -y 1
```
You should see:
- `68` for MPU-6050
- `48` for ADS1115 (if connected)

### Step 3: Clone / Copy Codebase to Raspberry Pi
Transfer the `Edge-AI` project folder to your Raspberry Pi home directory:
```bash
cd ~/Edge-AI
```

### Step 4: Install Python Edge Dependencies
```bash
pip3 install -r src/requirements.txt
pip3 install smbus2 RPi.GPIO adafruit-circuitpython-dht pyaudio opencv-python-headless
```

---

## 4. Running Hardware Tests & Production Node

### Step 1: Run the Interactive Sensor Diagnostic Suite
Before launching the complete system, test every connected sensor and actuator individually:
```bash
python3 scripts/test_hardware_sensors.py
```
This diagnostic tool will:
1. Scan I2C addresses `0x68` and `0x48`.
2. Read real live acceleration G-force from MPU-6050.
3. Read voltage and smoke PPM from MQ-2.
4. Read temperature and humidity from DHT-22.
5. Capture a snapshot frame from the camera.
6. Record 1.5 seconds of audio from the microphone.
7. Test the Traffic LEDs, sound the buzzer, and sweep the access barrier servo.

### Step 2: Launch the Production Edge Node
Run the production edge node:
```bash
python3 scripts/run_rpi_node.py 8080
```

### Step 3: Access the Web Dashboard
From any browser on the same Wi-Fi network (laptop, smartphone, or tablet), open:
```
http://<raspberry_pi_ip>:8080/
```
*(Find your Pi\'s IP by running `hostname -I` on the terminal).*

You will see:
- Live multi-sensor matrix updating directly from physical sensors.
- Deep Learning Rule Engine decisions evaluated in real-time.
- Physical traffic LEDs, barrier servo, and alert sirens actuating autonomously upon incident detection!
