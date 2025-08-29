#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, time, requests
from datetime import datetime, timedelta
from pytz import timezone
from pymodbus.client import ModbusSerialClient
from zappi_client_local import hourly_today, ws_to_kwh, MyEnergiLite

# ---------------- Config ----------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "pvo_config.json")

REQUIRED_KEYS = [
    "SYSTEMID","APIKEY","OWMKEY","CityID","TimeZone",
    "InverterPort","DeviceId","ZappiUser","ZappiPassword",
    "HarviGridSno","HarviGenSno"
]

def load_config(path):
    try:
        with open(path, "r") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"Config file not found: {path}", file=sys.stderr); sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Config file is not valid JSON: {e}", file=sys.stderr); sys.exit(1)
    missing = [k for k in REQUIRED_KEYS if k not in cfg or str(cfg[k]).strip()==""]
    if missing:
        print("ERROR: Config file is missing required keys:"); [print(f"  - {k}") for k in missing]
        sys.exit(1)
    return cfg

cfg            = load_config(CONFIG_PATH)
SYSTEMID       = cfg["SYSTEMID"]
APIKEY         = cfg["APIKEY"]
OWMKey         = cfg["OWMKEY"]
CityID         = int(cfg["CityID"])
LocalTZ        = timezone(cfg["TimeZone"])
INVERTER_PORT  = cfg["InverterPort"]
DEVICE_ID      = int(cfg["DeviceId"])
ZAPPI_USER     = cfg["ZappiUser"]
ZAPPI_PASS     = cfg["ZappiPassword"]

STATE_PATH = "/tmp/pvo_cons_state.json"

def localnow():
    return datetime.now(tz=LocalTZ)

# ---------------- Weather ----------------
def fetch_owm_temp_current():
    try:
        from pyowm import OWM
        _owm = OWM(OWMKey)
        _mgr = _owm.weather_manager()
        _obs = _mgr.weather_at_id(CityID)
        return float(_obs.weather.temperature(unit='celsius')['temp'])
    except Exception:
        return None

# ---------------- Inverter snapshot ----------------
def _rd_single(regs, idx, unit=10.0):
    return float(regs[idx]) / unit if idx < len(regs) else 0.0

def _rd_double(regs, idx, unit=10.0):
    if idx + 1 >= len(regs): return 0.0
    return float((regs[idx] << 16) + regs[idx+1]) / unit

def read_inverter_snapshot(port: str, device_id: int):
    cli = ModbusSerialClient(port=port, baudrate=9600, stopbits=1,
                             parity="N", bytesize=8, timeout=1)
    snapshot = {
        "ts": localnow(),"status": -1,"ppv_w": 0.0,"vpv_v": 0.0,"epvtoday": 0.0,
        "pac_w": 0.0,"vac1_v": 0.0,"eac_today_kwh": 0.0,"etotal_kwh": 0.0,
        "temp_c": 0.0,"pactogrid_reg": 0.0,
    }
    if not cli.connect(): return snapshot
    try:
        r1 = cli.read_input_registers(0,124,device_id=device_id)
        r9 = cli.read_input_registers(1000,66,device_id=device_id)
        if r1.isError() and r9.isError(): return snapshot
        if r1.isError(): r1 = cli.read_holding_registers(0,124,device_id=device_id)
        if r9.isError(): r9 = cli.read_holding_registers(1000,66,device_id=device_id)
        regs1, regs9 = r1.registers if not r1.isError() else [], r9.registers if not r9.isError() else []
        snapshot.update({
            "status": int(regs1[0]) if regs1 else -1,
            "ppv_w": _rd_double(regs1,1),
            "vpv_v": _rd_single(regs1,3)+_rd_single(regs1,7),
            "epvtoday": _rd_double(regs1,59)+_rd_double(regs1,63),
            "pac_w": _rd_double(regs1,35),
            "vac1_v": _rd_single(regs1,38),
            "eac_today_kwh": _rd_double(regs1,53),
            "etotal_kwh": _rd_double(regs1,55),
            "temp_c": _rd_single(regs1,93),
            "pactogrid_reg": _rd_double(regs9,23) if regs9 else 0.0,
        })
        return snapshot
    finally:
        cli.close()

# ---------------- Zappi totals ----------------
def _derive_zid_from_user(z_user: str) -> int:
    s = str(z_user).strip()
    return int(s[1:]) if s.upper().startswith("Z") else int(s)

def zappi_import_export_today_kwh():
    zid = _derive_zid_from_user(ZAPPI_USER)
    rows = hourly_today(ZAPPI_USER, ZAPPI_PASS, zid)
    imp = exp = gen = 0.0
    for rec in rows:
        imp += ws_to_kwh(int(rec.get("imp",0) or 0))
        exp += ws_to_kwh(int(rec.get("exp",0) or 0))
        gen += ws_to_kwh(int(rec.get("gep",0) or 0))
    return imp, exp, gen

# ---------------- HARVI live ----------------
def harvi_live_values(username, password, grid_sno, solar_sno):
    cli = MyEnergiLite(username, password)
    state = cli.get_status_raw()
    if not isinstance(state, list): return None
    def _find_dev(devclass, sno):
        for grp in state:
            lst = grp.get(devclass.lower()) if devclass!="ZAPPI" else grp.get("zappi")
            if isinstance(lst,list):
                for d in lst:
                    try:
                        if int(d.get("sno"))==int(sno): return d
                    except: pass
        return None
    harvi_grid  = _find_dev("HARVI", int(cfg["HarviGridSno"]))
    harvi_solar = _find_dev("HARVI", int(cfg["HarviGenSno"]))
    if not harvi_grid or not harvi_solar: return None
    def _sum_ectp(d): return sum(int(d.get(k,0)) for k in ("ectp1","ectp2","ectp3") if isinstance(d.get(k),(int,float)))
    grid_w, gen_w = _sum_ectp(harvi_grid), _sum_ectp(harvi_solar)
    house_w = gen_w + grid_w
    return int(grid_w), int(gen_w), int(house_w)

# ---------------- PVOutput upload ----------------
PVO_URL = "https://pvoutput.org/service/r2/addstatus.jsp"
def upload_to_pvo(payload):
    headers = {"X-Pvoutput-Apikey": APIKEY,"X-Pvoutput-SystemId": SYSTEMID}
    r = requests.post(PVO_URL, headers=headers, data=payload, timeout=15)
    r.raise_for_status()
    return r

# ---------------- State persistence ----------------
def load_state(path):
    try:
        with open(path,"r") as f:
            s=json.load(f); s["ts"]=datetime.fromisoformat(s["ts"]); return s
    except: return None

def save_state(path, *, today_str, cum_cons_kwh, inv_eac_today_kwh, imp_kwh, exp_kwh, ts):
    try:
        with open(path,"w") as f:
            json.dump({"date":today_str,"cum_cons_kwh":round(cum_cons_kwh,6),
                       "inv_eac_today_kwh":round(inv_eac_today_kwh,6),
                       "imp_kwh":round(imp_kwh,6),"exp_kwh":round(exp_kwh,6),
                       "ts":ts.isoformat()},f)
    except: pass

# ---------------- Helpers ----------------
def next_five_minute_boundary(tz):
    now=datetime.now(tz); base=now.replace(second=0,microsecond=0)
    add=(5-(now.minute%5))%5; add=5 if add==0 else add
    return base+timedelta(minutes=add)

# ---------------- Main Update ----------------
def update_pvoutput():
    now=localnow(); today_str=now.strftime("%Y-%m-%d"); owm_temp_c=fetch_owm_temp_current()
    inv=read_inverter_snapshot(INVERTER_PORT, DEVICE_ID); inverter_online=(inv["status"]!=-1)
    imp_kwh,exp_kwh,gen_kwh=zappi_import_export_today_kwh()
    gen_ac_kwh=max(inv["eac_today_kwh"],0.0)
    cum_cons_kwh=max(gen_ac_kwh+imp_kwh-exp_kwh,0.0)
    prev=load_state(STATE_PATH)
    if prev and prev.get("date")==today_str:
        dt=max((now-prev["ts"]).total_seconds(),1)
        delta_imp_wh=(imp_kwh-prev["imp_kwh"])*1000.0
        delta_exp_wh=(exp_kwh-prev["exp_kwh"])*1000.0
        derived_pactogrid_w=(delta_exp_wh-delta_imp_wh)*3600.0/dt
    else:
        derived_pactogrid_w=inv.get("pactogrid_reg",0.0)
    pactogrid_w=inv["pactogrid_reg"] if abs(inv.get("pactogrid_reg",0.0))>0 else derived_pactogrid_w
    harvi=harvi_live_values(ZAPPI_USER,ZAPPI_PASS,cfg["HarviGridSno"],cfg["HarviGenSno"])
    if harvi: grid_live_w,gen_live_w,house_live_w=harvi; harvi_ok=True
    else: grid_live_w=gen_live_w=house_live_w=None; harvi_ok=False
    v2_power_gen=gen_live_w if harvi_ok else (int(round(inv["pac_w"])) if inverter_online else 0)
    v9_power_exp=max(-(grid_live_w or 0),0) if harvi_ok else int(round(pactogrid_w))
    payload={"d":now.strftime("%Y%m%d"),"t":now.strftime("%H:%M"),
             "v1":int(round(inv["eac_today_kwh"]*1000)) if inverter_online else 0,
             "v2":v2_power_gen,"v3":int(round(cum_cons_kwh*1000)),
             "v5":(f"{owm_temp_c:.1f}" if owm_temp_c is not None else ""),
             "v6":f"{inv['vpv_v']:.1f}" if inverter_online else 0,
             "v7":f"{inv['eac_today_kwh']:.3f}" if inverter_online else 0,
             "v8":f"{inv['etotal_kwh']:.3f}" if inverter_online else 0,
             "v9":v9_power_exp,"v10":v2_power_gen,
             "v11":f"{inv['vac1_v']:.1f}" if inverter_online else 0,
             "v12":f"{inv['temp_c']:.1f}" if inverter_online else 0}
    try:
        r=upload_to_pvo(payload); print(f"{now.isoformat()} PVOutput OK {payload}")
    except Exception as e:
        print(f"{now.isoformat()} PVOutput FAILED {e}\npayload={payload}",file=sys.stderr)
    save_state(STATE_PATH,today_str=today_str,cum_cons_kwh=cum_cons_kwh,
               inv_eac_today_kwh=inv["eac_today_kwh"],imp_kwh=imp_kwh,
               exp_kwh=exp_kwh,ts=now)

# ---------------- Main loop ----------------
def main():
    while True:
        update_pvoutput()
        nxt=next_five_minute_boundary(LocalTZ)
        sleep_sec=max((nxt-localnow()).total_seconds(),0)
        try: time.sleep(sleep_sec)
        except KeyboardInterrupt: print("\nExiting by user request.\n",file=sys.stderr); sys.exit(0)

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: print("\nExiting by user request.\n",file=sys.stderr); sys.exit(0)
    except Exception as e: print(f"error: {e}",file=sys.stderr); sys.exit(1)
