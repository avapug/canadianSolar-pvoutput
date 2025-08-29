PVOutput Uploader for Growatt MIN 5000TL‑X + MyEnergi (Zappi/Harvi)
==================================================================

Overview
--------
This project uploads your solar generation and household consumption data to
PVOutput.org. It combines:
1) Live inverter data from a Growatt MIN 5000TL‑X (and likely similar models) via
   Modbus/RTU over a serial adapter.
2) MyEnergi (Zappi/Harvi) data for import/export and live PV/house figures.
3) Weather temperature from OpenWeatherMap (OWM).

The uploader posts PVOutput v1–v12 fields. We *only* submit v3 (cumulative energy
consumed) and let PVOutput derive v4 (instantaneous power used). Live power (v2/v10)
and export (v9) prefer Harvi readings when available, falling back to inverter/
derived values.

What this fork does now
-----------------------
- Talks to the Growatt inverter over Modbus/RTU using pymodbus (reads power,
  energy today/total, inverter temp/voltage, etc).
- Queries MyEnergi using a tiny, self‑contained client (`zappi_client_local.py`)
  that implements the same digest‑auth + ASN hand‑off behavior as the MEC tools.
- Uses two HARVI devices (one on the grid, one on the PV) for accurate live
  power readings when available.
- Uploads to PVOutput every 5 minutes, aligned to wall‑clock boundaries.
- Persists a small state JSON under /tmp to compute clean deltas across runs.
- Uses OpenWeatherMap for ambient temperature (required).

Credits
-------
- The MyEnergi client behavior here is informed by the excellent MEC project:
  https://github.com/edent/mec (referenced for request flow and data layout).
- Original Canadian Solar project foundations by Josenivaldo Benito Jr.

Requirements
------------
- Python 3.9+ (3.10 recommended)
- A serial connection to your Growatt inverter (e.g. USB‑RS485/RS232 depending on your setup)
- A MyEnergi account with Zappi/Harvi devices
- An OpenWeatherMap API key
- A PVOutput API key and System ID

Virtualenv Setup (recommended)
------------------------------
# create and activate a venv (example path; choose your own)
python3 -m venv ~/zappi-env
source ~/zappi-env/bin/activate

# upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# run the uploader
python pvoutput.py

Configuration
-------------
Place a JSON file named pvo_config.json next to pvoutput.py with ALL of the
following keys (all are required):

{
  "SYSTEMID":        "your-pvoutput-system-id",
  "APIKEY":          "your-pvoutput-api-key",
  "OWMKEY":          "your-openweather-api-key",
  "CityID":          "5391959",
  "TimeZone":        "Europe/London",
  "InverterPort":    "/dev/ttyUSB0",
  "DeviceId":        "1",
  "ZappiUser":       "12345678",
  "ZappiPassword":   "your-myenergi-password",
  "HarviGridSno":    "2826772",
  "HarviGenSno":     "2835761"
}

Notes:
- Harvi serials are used to identify the “grid” and “PV” devices for live power.
- If a Harvi reading is unavailable, the uploader falls back to inverter/derived values.
- CityID must be the numeric OpenWeatherMap city id.

Running
-------
# from your venv, in the project directory
python pvoutput.py

The script aligns to 5‑minute wall‑clock boundaries and continuously uploads.

Service (optional)
------------------
Many users prefer to run a small wrapper shell script under systemd. Example:

/usr/local/bin/pvoutput.sh
--------------------------
#!/bin/bash
set -euo pipefail
while true; do
  /root/zappi-env/bin/python3 -u /root/pvoutput/pvoutput.py
  echo "Python crashed; sleeping 60s then restarting..."
  sleep 60
done
--------------------------------

Create a systemd unit that ExecStart=/usr/local/bin/pvoutput.sh so it restarts
after errors or reboots. See Raspberry Pi docs for service creation details.

Docker (optional)
-----------------
A minimal Dockerfile is included. Build and run examples:

docker build -t pvoutput-growatt .
docker run --restart always --name pvoutput -d -i   --device=/dev/ttyUSB0 --net=host   -v /path/to/project:/app -w /app pvoutput-growatt   bash -lc "source /app/.venv/bin/activate && python pvoutput.py"

(Adjust device path, volumes, and env to your setup.)

Files in this repo
------------------
- pvoutput.py            Main uploader loop (reads inverter + MyEnergi + OWM, posts to PVOutput)
- zappi_client_local.py  Minimal MyEnergi client (digest auth + ASN switch; hourly + live status)
- requirements.txt       Python dependencies
- Dockerfile             Optional container build
- pvo_config.json        Your local configuration (create this; not committed)

Troubleshooting
---------------
- If PVOutput shows zero or odd values for v2/v9, verify Harvi serials and CT
  orientations. The code treats grid export as negative power from the grid CT.
- If temperature (v5) is blank, verify OWM CityID and API key.
- If Modbus reads fail (inverter offline at night), v1/v2 will be zero; v3 will
  continue to reflect cumulative consumption derived from imports/exports.

License
-------
This fork maintains the original project’s license. See LICENSE file if present.
