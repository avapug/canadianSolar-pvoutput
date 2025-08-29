# zappi_client_local.py
# Minimal, self-contained MyEnergi client for:
#   - Live status fetch (cgi-jstatus-*)
#   - Hourly Zappi history (cgi-jdayhour-Z{zid}-Y-M-D)
#
# No external dependencies beyond the standard library.
# Used by pvoutput.py to get Zappi totals and live HARVI/Zappi values.

import http
import urllib.request
import urllib.error
import json
import time
import socket
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import List, Dict, Optional, Any, Tuple

ASN_HEADER = "X_MYENERGI-asn"


class _HostChanged(Exception):
    """Internal signal that the backend asked us to switch to another host."""
    pass


class MyEnergiLite:
    """
    Tiny MyEnergi API client:
      - Handles digest auth
      - Follows 'X_MYENERGI-asn' to switch to the correct backend host
    """

    def __init__(self, username: str, password: str):
        # Username is typically your Zappi serial (e.g. "Z12345678" or "12345678").
        self._username = str(username)
        self._password = password
        # Starting point; server may redirect us with X_MYENERGI-asn.
        self._host = "s18.myenergi.net"

    # ---------- low-level helpers ----------

    def _maybe_set_host(self, headers):
        """Switch self._host if X_MYENERGI-asn is present and different."""
        if not headers:
            return
        if ASN_HEADER not in headers:
            return
        new_host = headers[ASN_HEADER]
        if not new_host or new_host == "undefined" or new_host == self._host:
            return
        self._host = new_host
        raise _HostChanged()

    def _load(self, suffix: str) -> Any:
        """
        Perform a GET with digest auth. We retry once if ASN header asks us
        to switch host, and then do one final attempt.
        """
        for _ in range(2):
            try:
                return self._do_load(suffix)
            except _HostChanged:
                # Will re-run against the new host
                pass
        return self._do_load(suffix)

    def _do_load(self, suffix: str) -> Any:
        url = f"https://{self._host}/{suffix}"
        req = urllib.request.Request(url)
        # Old client UA mimicked by upstream tools (doesn’t really matter).
        req.add_header("User-Agent", "Wget/1.14 (linux-gnu)")
        req.add_header("Accept", "application/json")

        realm = "MyEnergi Telemetry"
        pwd_mgr = urllib.request.HTTPPasswordMgr()
        # Note: urllib’s add_password signature is:
        #   add_password(realm, uri, user, passwd)
        pwd_mgr.add_password(realm, url, self._username, self._password)
        handler = urllib.request.HTTPDigestAuthHandler(pwd_mgr)
        opener = urllib.request.build_opener(handler)
        urllib.request.install_opener(opener)

        try:
            resp = urllib.request.urlopen(req, timeout=20)
            self._maybe_set_host(resp.headers)
            raw = resp.read()
        except urllib.error.HTTPError as e:
            # 401 challenge includes headers; check for host switch.
            self._maybe_set_host(e.headers)
            raise
        except (urllib.error.URLError, socket.timeout, http.client.RemoteDisconnected, ConnectionResetError):
            raise

        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---------- public API ----------

    def get_status_raw(self) -> Any:
        """
        Live snapshot across devices (Zappi/Harvi/Eddi), same shape
        the upstream tools use. Typically a list of groups,
        e.g. [{'zappi': [...]}, {'harvi': [...]}, ...].
        """
        return self._load("cgi-jstatus-*")

    def get_hour_data(self, zid: int, y: int, m: int, d: int) -> List[Dict]:
        """
        Hourly Zappi history for a specific day (local to the Zappi site).
        Endpoint shape matches upstream: cgi-jdayhour-Z{zid}-{y}-{m}-{d}
        Returns a list of hour buckets.
        """
        res = self._load(f"cgi-jdayhour-Z{zid}-{y}-{m}-{d}")
        key = f"U{zid}"
        if isinstance(res, dict) and key in res and isinstance(res[key], list):
            return res[key]
        if isinstance(res, list):
            return res
        return []


# ---------- helpers used by pvoutput.py ----------

def _today_local_tuple() -> Tuple[int, int, int]:
    """
    Use the local (device) clock to decide 'today' — this matches the
    original get_zappi_history.py behaviour and your current pvoutput.py.
    """
    t = time.localtime()
    return t.tm_year, t.tm_mon, t.tm_mday


def ws_to_kwh(ws: int) -> float:
    """Convert Watt-seconds (Ws) to kWh."""
    return float(ws) / 3_600_000.0  # 1 kWh = 3,600,000 Ws


def choose_first_zappi(username: str, password: str) -> int:
    """
    Convenience: find the first Zappi serial visible on the account.
    Not used by pvoutput.py, but handy for manual testing.
    """
    cli = MyEnergiLite(username, password)
    res = cli.get_status_raw()
    if isinstance(res, list):
        for group in res:
            if "zappi" in group and isinstance(group["zappi"], list) and group["zappi"]:
                first = group["zappi"][0]
                try:
                    return int(first.get("sno"))
                except Exception:
                    continue
    raise RuntimeError("No Zappi serial found on this account.")


def hourly_today(username: str, password: str, zid: int) -> List[Dict]:
    """
    Fetch the Zappi HOURLY buckets for 'today' using the local clock.
    This is what pvoutput.py relies on for import/export/gen totals.
    """
    y, m, d = _today_local_tuple()
    cli = MyEnergiLite(username, password)
    return cli.get_hour_data(zid, y, m, d)


# Pretty table helpers for manual testing (not used by pvoutput.py).
def sum_import_export_kwh(username: str, password: str, zid: int) -> Tuple[float, float]:
    rows = hourly_today(username, password, zid)
    imp = exp = 0.0
    for rec in rows:
        imp += ws_to_kwh(int(rec.get("imp", 0) or 0))
        exp += ws_to_kwh(int(rec.get("exp", 0) or 0))
    return imp, exp


def pretty_table_today(username: str, password: str, zid: int) -> str:
    rows = hourly_today(username, password, zid)
    header = f"{'Time':>5}  {'Dur':>6}  {'Imported':>10}  {'Exported':>10}  {'Generation':>11}"
    lines = [header, "-" * len(header)]
    for rec in rows:
        hr   = int(rec.get("hr", 0) or 0)
        mins = int(rec.get("min", 0) or 0)
        dur  = 3600  # hourly buckets
        imp  = ws_to_kwh(int(rec.get("imp", 0) or 0))
        exp  = ws_to_kwh(int(rec.get("exp", 0) or 0))
        gen  = ws_to_kwh(int(rec.get("gep", 0) or 0))  # generation positive
        lines.append(f"{hr:02d}:{mins:02d}  {dur:6d}  {imp:10.3f}  {exp:10.3f}  {gen:11.3f}")
    # totals
    imp_t, exp_t = 0.0, 0.0
    for rec in rows:
        imp_t += ws_to_kwh(int(rec.get("imp", 0) or 0))
        exp_t += ws_to_kwh(int(rec.get("exp", 0) or 0))
    lines += ["-" * len(header), f"{'Totals':>5}  {'':6}  {imp_t:10.3f}  {exp_t:10.3f}  {'':11}"]
    return "\n".join(lines)
