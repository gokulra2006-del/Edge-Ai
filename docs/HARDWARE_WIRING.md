# SENTINEL-AI: Comprehensive Hardware Wiring & Pinout Guide

This document is the authoritative hardware reference for wiring all sensors and actuators to your **Raspberry Pi 4 Model B**.

---

## 1. Master 40-Pin Header Wiring Allocation

Every pin assignment has been verified to ensure **zero GPIO collisions**:

| Physical Pin # | BCM GPIO | Signal / Function | Connected Sensor / Actuator | Required Resistor / Circuit | Power Rail |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Pin 1** | **3V3** | 3.3V DC Supply | **DHT-22 VCC, ADS1115 VDD, GY-87 VCC_IN** | Direct connection | 3.3V (Max 50mA per pin) |
| **Pin 2** | **5V** | 5.0V DC Supply | **MQ-2 Gas Heater VCC, SG90 Servo Power** | Direct connection | 5.0V Rail |
| **Pin 3** | **GPIO 2** | I2C1 SDA | **GY-87 SDA** and **ADS1115 SDA** | Shared I2C Data bus | 3.3V logic level |
| **Pin 5** | **GPIO 3** | I2C1 SCL | **GY-87 SCL** and **ADS1115 SCL** | Shared I2C Clock bus | 3.3V logic level |
| **Pin 6** | **GND** | Ground Rail | **Common System Ground** | Common ground for all devices | 0V |
| **Pin 7** | **GPIO 4** | 1-Wire Digital | **DHT-22 / DHT-11 Data** | **4.7 kΩ pull-up to 3.3V** | 3.3V logic level |
| **Pin 8** | **GPIO 14** | UART0 TXD | **GPS NEO-6M RX Pin** | Direct connection | 3.3V logic level |
| **Pin 10** | **GPIO 15** | UART0 RXD | **GPS NEO-6M TX Pin** | Direct connection | 3.3V logic level |
| **Pin 12** | **GPIO 18** | I2S BCLK | **INMP441 SCK (Serial Clock)** | Direct connection | 3.3V logic level |
| **Pin 29** | **GPIO 5** | Digital Out | **RED LED** (Incident Halt) | **220 Ω – 330 Ω resistor to GND** | 3.3V GPIO |
| **Pin 31** | **GPIO 6** | Digital Out | **YELLOW LED** (Near-Miss Caution) | **220 Ω – 330 Ω resistor to GND** | 3.3V GPIO |
| **Pin 32** | **GPIO 12** | Hardware PWM0 | **SG90 Barrier Servo Signal** | PWM Signal pin (50 Hz) | 3.3V PWM logic |
| **Pin 33** | **GPIO 13** | Digital Out | **GREEN LED** (Nominal Flow) | **220 Ω – 330 Ω resistor to GND** | 3.3V GPIO |
| **Pin 35** | **GPIO 19** | I2S LRCLK | **INMP441 WS (Word Select)** | Direct connection | 3.3V logic level |
| **Pin 36** | **GPIO 16** | Digital Out | **Emergency Siren Buzzer** | Active buzzer (or NPN driver) | 3.3V GPIO |
| **Pin 38** | **GPIO 20** | I2S DIN | **INMP441 SD (Serial Data)** | Direct connection | 3.3V logic level |
| **CSI Port** | **CSI** | MIPI CSI-2 | **Raspberry Pi Camera Module** | 15-pin ribbon cable | 3.3V Camera Interface |

---

## 2. Sensor-by-Sensor Circuit Details

### 1. DHT-22 Temperature & Humidity Sensor
- **VCC (Pin 1)** &rarr; Raspberry Pi Pin 1 (3.3V)
- **DATA (Pin 2)** &rarr; Raspberry Pi Pin 7 (GPIO 4)
  - Place a **4.7 kΩ to 10 kΩ resistor** between Pin 1 (3.3V) and Pin 2 (DATA) as a pull-up.
- **GND (Pin 4)** &rarr; Raspberry Pi Pin 6 (GND)

### 2. GY-87 10-DOF Multi-Sensor Board
Contains MPU-6050 (0x68), HMC5883L (0x1E), and BMP180 (0x77):
- **VCC_IN** &rarr; Raspberry Pi Pin 1 (3.3V) *(Safest for I2C bus)*
- **GND** &rarr; Common GND
- **SDA** &rarr; Raspberry Pi Pin 3 (GPIO 2)
- **SCL** &rarr; Raspberry Pi Pin 5 (GPIO 3)
> [!NOTE]
> The software automatically injects `0x02` into register `0x37` (`INT_PIN_CFG`) on the MPU-6050 to activate I2C bypass, making the magnetometer and barometer visible on `/dev/i2c-1`.

### 3. ADS1115 16-Bit ADC + MQ-2 Smoke Sensor
> [!CAUTION]
> MQ-2 internal heater requires 5V. **Never connect the analog output of a 5V MQ-2 directly to Raspberry Pi GPIOs!**
- **ADS1115 VDD** &rarr; Raspberry Pi Pin 1 (3.3V)
- **ADS1115 GND** &rarr; Common GND
- **ADS1115 SDA** &rarr; Raspberry Pi Pin 3 (GPIO 2)
- **ADS1115 SCL** &rarr; Raspberry Pi Pin 5 (GPIO 3)
- **ADS1115 ADDR** &rarr; Common GND (Sets address to `0x48`)
- **ADS1115 AIN0** &rarr; MQ-2 Analog Pin `A0`
- **MQ-2 VCC** &rarr; Raspberry Pi Pin 2 (5V Rail)
- **MQ-2 GND** &rarr; Common GND

### 4. NEO-6M GPS Receiver (UART)
- **VCC** &rarr; Raspberry Pi Pin 1 (3.3V) or Pin 2 (5V)
- **GND** &rarr; Common GND
- **TX** &rarr; Raspberry Pi Pin 10 (GPIO 15 / RXD0)
- **RX** &rarr; Raspberry Pi Pin 8 (GPIO 14 / TXD0)

### 5. INMP441 I2S MEMS Microphone
- **VDD** &rarr; Raspberry Pi Pin 1 (3.3V)
- **GND** &rarr; Common GND
- **SCK** &rarr; Raspberry Pi Pin 12 (GPIO 18 / BCLK)
- **WS** &rarr; Raspberry Pi Pin 35 (GPIO 19 / LRCLK)
- **SD** &rarr; Raspberry Pi Pin 38 (GPIO 20 / DIN)
- **L/R** &rarr; GND (Selects Left Channel)

### 6. Actuators (LEDs, Buzzer, Servo)
- **RED LED**: Anode (+) &rarr; 330 Ω Resistor &rarr; Pin 29 (GPIO 5); Cathode (-) &rarr; GND.
- **YELLOW LED**: Anode (+) &rarr; 330 Ω Resistor &rarr; Pin 31 (GPIO 6); Cathode (-) &rarr; GND.
- **GREEN LED**: Anode (+) &rarr; 330 Ω Resistor &rarr; Pin 33 (GPIO 13); Cathode (-) &rarr; GND.
- **Buzzer**: Positive (+) &rarr; Pin 36 (GPIO 16); Negative (-) &rarr; GND.
- **SG90 Servo**: Red Wire &rarr; 5V (Pin 2); Brown Wire &rarr; GND (Pin 6); Orange Wire &rarr; Pin 32 (GPIO 12).
