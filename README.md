# Growatt + MyEnergi PVOutput Uploader

This project collects and uploads live solar generation, grid import/export, house consumption, and weather data to [PVOutput.org](https://pvoutput.org), by combining:

- **Growatt MIN 5000TL‑X** inverter (via Modbus RTU / RS-232)  
- **MyEnergi Zappi + HARVI** devices for CT-based power monitoring  
- **OpenWeatherMap** for local temperature  
- Logic adapted from the **mec GitHub repository** for reliable Zappi integrations

---

## Features

- Reads **Growatt inverter data** (Pac, VPV, EacToday, temperature, etc.)  
- Reads **live PV generation and grid readings** via HARVI CT clamps  
- Reads **import/export/generation totals** via Zappi API  
- Fetches **temperature from OpenWeatherMap**  
- Uploads complete dataset (v1–v12) to PVOutput.org every 5 minutes  
- Maintains a small state file to compute power/consumption deltas properly  
- Designed to run continuously via a service or wrapper script

---

## Configuration

Put the following in `pvo_config.json` (all fields required):

```json
{
  "SYSTEMID": "your-pvoutput-system-id",
  "APIKEY": "your-pvoutput-api-key",
  "OWMKEY": "your-openweather-api-key",
  "CityID": "your-openweather-city-id",
  "TimeZone": "Australia/Sydney",
  "InverterPort": "/dev/ttyUSB0",
  "DeviceId": 1,
  "ZappiUser": "your-zappi-serial",
  "ZappiPassword": "your-zappi-password",
  "HarviGridSno": "12345678",
  "HarviGenSno": "12345678"
}
```

---

## Usage

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Manually**
   ```bash
   ./pvoutput.py
   ```

3. **Run as a Service**

   Use a wrapper like:

   ```bash
   #!/bin/bash
   while true; do
     /root/zappi-env/bin/python3 -u /root/pvoutput/pvoutput.py
     echo "Script exited—restarting in 60s"
     sleep 60
   done
   ```

   And invoke it via systemd with:
   ```ini
   [Service]
   ExecStart=/path/to/pvoutput.sh
   Restart=always
   ```

---

## Notes

- Requires PVOutput donation-enabled account for extended data (v7–v12).  
- Harvi data is the authoritative live value source (better than inverter alone).  
- OpenWeatherMap configuration is mandatory.  

---

## Acknowledgements

This integration adapts **Zappi and Harvi data handling** from the [mec GitHub repository](https://github.com/your-org/mec) — many thanks for their pioneering work in the MyEnergi ecosystem.
