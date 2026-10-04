# SENTINEL-AI: Hardware Troubleshooting & Diagnostics Guide

Common failure modes, diagnostic commands, and recovery procedures for the physical edge node.

---

## 1. GY-87: Magnetometer (0x1E) and Barometer (0x77) Not Showing Up

### Symptom:
`i2cdetect -y 1` shows `0x68` (MPU-6050), but `0x1E` and `0x77` are absent.

### Cause:
On the GY-87 board, the HMC5883L and BMP180 are connected to the auxiliary I2C pins of the MPU-6050. By default, the MPU-6050 isolates its auxiliary bus from the Raspberry Pi.

### Solution:
Enable I2C bypass mode in the MPU-6050:
```python
import smbus2
bus = smbus2.SMBus(1)
bus.write_byte_data(0x68, 0x6B, 0x00)  # Wake up MPU-6050
bus.write_byte_data(0x68, 0x37, 0x02)  # Set BYPASS_EN bit in INT_PIN_CFG
```
After running this command, run `i2cdetect -y 1` again. Addresses `0x1E` and `0x77` will appear!

---

## 2. GPS: No Data Received on /dev/serial0

### Symptom:
`/dev/serial0` is open, but no NMEA sentences are received.

### Cause:
1. TX and RX wires are swapped:
   - **GPS TX** must go to **Raspberry Pi RX (GPIO 15 / Pin 10)**.
   - **GPS RX** must go to **Raspberry Pi TX (GPIO 14 / Pin 8)**.
2. Bluetooth conflict: On Raspberry Pi 3/4, the primary UART is sometimes assigned to the onboard Bluetooth controller.

### Solution:
Disable Bluetooth on primary UART to ensure `/dev/serial0` routes to GPIO 14/15:
```bash
sudo nano /boot/firmware/config.txt
```
Add:
```ini
dtoverlay=disable-bt
enable_uart=1
```
Then stop and disable the modem service:
```bash
sudo systemctl disable hciuart
sudo reboot
```
Test GPS data with:
```bash
cat /dev/serial0
```

---

## 3. DHT-22: Checksum / Timeout Errors

### Symptom:
`RuntimeError: Checksum did not validate!` or intermittent `None` values.

### Cause:
1. Missing 4.7 kΩ pull-up resistor between VCC (3.3V) and DATA (GPIO 4).
2. Polling too quickly. Physical DHT-22 sensors require a minimum of **1.5 to 2.0 seconds** between read requests.

### Solution:
- Ensure 4.7 kΩ pull-up is in place.
- The `DHT22Driver` automatically enforces a 2.0-second cooldown cache.

---

## 4. INMP441: No Audio Stream / ALSA Errors

### Symptom:
`PyAudio` raises `IOError: Device not found`.

### Cause:
I2S requires a sound card overlay in the Linux device tree.

### Solution:
Verify the sound card is listed in ALSA:
```bash
arecord -l
```
If no recording device is listed, ensure `/boot/firmware/config.txt` contains:
```ini
dtoverlay=googlevoicehat-soundcard
```
And verify pins:
- SCK &rarr; GPIO 18 (Pin 12)
- WS &rarr; GPIO 19 (Pin 35)
- SD &rarr; GPIO 20 (Pin 38)
- L/R &rarr; GND

---

## 5. Non-Root GPIO Permission Denied

### Symptom:
`RuntimeError: No access to /dev/mem or /dev/gpiomem`.

### Solution:
Add your user to the `gpio` and `i2c` groups:
```bash
sudo usermod -aG gpio,i2c,video,audio $USER
```
Log out and log back in for permissions to take effect.
