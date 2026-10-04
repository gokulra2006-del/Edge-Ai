# SENTINEL-AI: Raspberry Pi OS Configuration & Setup Guide

This guide walks through configuring Raspberry Pi OS (Bullseye / Bookworm 64-bit) for the SENTINEL-AI physical edge node.

---

## 1. Enable Hardware Interfaces

Open a terminal on your Raspberry Pi:
```bash
# 1. Enable I2C Bus 1 (/dev/i2c-1)
sudo raspi-config nonint do_i2c 0

# 2. Enable Hardware Serial UART (/dev/serial0)
# Disables login shell over serial while keeping serial hardware port active
sudo raspi-config nonint do_serial 2

# 3. Enable Raspberry Pi Camera Interface
sudo raspi-config nonint do_camera 0
```

---

## 2. Enable I2S Audio Support for INMP441

Add the I2S microphone device tree overlay to `/boot/config.txt` (or `/boot/firmware/config.txt` on Bookworm):
```bash
sudo nano /boot/firmware/config.txt
```
Add the following line at the end:
```ini
# INMP441 I2S Audio Overlay
dtoverlay=googlevoicehat-soundcard
```
*Alternatively, you can use the generic I2S mic overlay:*
```ini
dtoverlay=i2s-mmap
```
Reboot the Raspberry Pi to apply kernel overlay changes:
```bash
sudo reboot
```

---

## 3. Install System Packages & Compiler Tools

```bash
sudo apt-get update
sudo apt-get install -y \
    i2c-tools \
    python3-smbus \
    python3-pip \
    python3-dev \
    python3-venv \
    portaudio19-dev \
    libcap-dev \
    ffmpeg
```

Verify that I2C devices are detected on the bus:
```bash
i2cdetect -y 1
```
You should see:
- `68` (MPU-6050)
- `48` (ADS1115)
- `1e` (HMC5883L magnetometer, once MPU-6050 bypass is activated)
- `77` (BMP180 barometer, once MPU-6050 bypass is activated)

---

## 4. Install Python Dependencies

In the project root directory on the Pi:
```bash
cd ~/Edge-AI
pip3 install -r src/requirements.txt
pip3 install smbus2 RPi.GPIO adafruit-circuitpython-dht pyserial pyaudio opencv-python-headless
```

---

## 5. Verify With Hardware Diagnostic Tool

Run the diagnostic suite to confirm every sensor and actuator is operating:
```bash
python3 scripts/hardware_diagnostic.py
```

---

## 6. Launch Production Hardware Edge Node

```bash
python3 scripts/run_rpi_node.py 8080
```
Open your browser on any laptop or phone connected to the same Wi-Fi:
```
http://<raspberry_pi_ip>:8080/
```
