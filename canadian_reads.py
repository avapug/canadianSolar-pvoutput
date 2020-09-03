#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, requests
from configobj import ConfigObj
from datetime import datetime
from time import sleep, time
from pytz import timezone
from pyowm import OWM
from pymodbus.client.sync import ModbusSerialClient as ModbusClient
os.chdir(os.path.dirname(__file__))

# read settings from config file
config = ConfigObj("pvoutput.txt")
SYSTEMID = config['SYSTEMID']
APIKEY = config['APIKEY']
OWMKey = config['OWMKEY']
CityID = int(config['CityID'])
LocalTZ = timezone(config['TimeZone'])


# Local time with timezone
def localnow():
    return datetime.now(tz=LocalTZ)

def read_single(rr, index, unit=10):
    return float(rr.registers[index]) / unit

def read_double(rr, index, unit=10):
    return float((rr.registers[index] << 16) + rr.registers[index + 1]) / unit

class Inverter(object):

    def __init__(self, address, port):
        """Return a Inverter object with port set to *port* and
        values set to their initial state."""
        self._inv = ModbusClient(method='rtu', port=port, baudrate=9600, stopbits=1, parity='N', bytesize=8, timeout=1)
        self._unit = address

        # Inverter properties
        self.date = timezone('UTC').localize(datetime(1970, 1, 1, 0, 0, 0))
        self.status = -1
        self.ppv = 0.0      # Ppv // Input PV power (w)
        self.vpv = 0.0      # Vpv1 + Vpv2 // Input voltage 1 channel (V) // Input Voltage 2-way (V)
        self.pac = 0.0      # Pac // Output power (W)
        #self.vac1 = 0.0    # Vac1 // Output voltage 1 channel (V)
        self.eactoday = 0   # EacToday // Electricity of the day (kWh)
        self.eactotal = 0   # EacTotal // Cumulative power generation (kWh)
        self.temp1 = 0      # Inverter temperature
        self.cmo_str = ''

    def read_inputs(self):
        """Try read input properties from inverter, return true if succeed"""
        ret = False

        if self._inv.connect():
            # by default read first 100 registers
            # they contain all basic information needed to report
            rr = self._inv.read_input_registers(0, 100, unit=self._unit)

            if not rr.isError():
                ret = True
                self.date = localnow()

                self.status = rr.registers[0]
                if self.status != -1:
                    self.cmo_str = 'Status: '+str(self.status)
                self.ppv = read_single(rr, 2)
                self.vpv = read_single(rr, 3) + read_single(rr, 7)
                self.pac = read_single(rr, 36)
                #self.vac1 = read_single(rr, 38)
                self.eactoday = read_single(rr, 54)
                self.eactotal = read_single(rr, 56)
                self.temp1 = read_single(rr, 93)

                #print('{:10}'.format('Date:'), self.date)
                #if self.status == 0: print('{:10}'.format('Status:'), 'Waiting')
                #if self.status == 1: print('{:10}'.format('Status:'), 'Normal')
                #if self.status == 2: print('{:10}'.format('Status:'), 'Fault')
                #print('{:10}'.format('PPv:'), self.ppv, 'W')
                #print('{:10}'.format('Vpv:'), self.vpv, 'V')
                #print('{:10}'.format('Pac:'), self.pac, 'W')
                #print('{:10}'.format('Vac1:'), self.vac1, 'V')
                #print('{:10}'.format('EacToday:'), self.eactoday, 'kWh')
                #print('{:10}'.format('EacTotal:'), self.eactotal, 'kWh')
                #print('{:10}'.format('Temp:'), self.temp1, 'c')
            else:
                self.status = -1
                ret = False

            self._inv.close()
        else:
            print('Error connecting to port')
            ret = False

        return ret


class Weather(object):

    def __init__(self, API, city_id=None):
        self._API = API
        self._cityID = city_id
        self._owm = OWM(self._API)
        self._mgr = self._owm.weather_manager()
        self.temperature = 0.0

    def get(self):
        obs = self._mgr.weather_at_id(self._cityID)
        w = obs.weather
        self.temperature = w.temperature(unit='celsius')['temp']

        #print(self.temperature)


class PVOutputAPI(object):

    def __init__(self, API, system_id=None):
        self._API = API
        self._systemID = system_id

    def add_status(self, payload, system_id=None):
        """Add live output data. Data should contain the parameters as described
        here: https://pvoutput.org/help.html#api-addstatus ."""
        sys_id = system_id if system_id is not None else self._systemID
        self.__call("https://pvoutput.org/service/r2/addstatus.jsp", payload, sys_id)

    def add_output(self, payload, system_id=None):
        """Add end of day output information. Data should be a dictionary with
        parameters as described here: https://pvoutput.org/help.html#api-addoutput ."""
        sys_id = system_id if system_id is not None else self._systemID
        self.__call("https://pvoutput.org/service/r2/addoutput.jsp", payload, sys_id)

    def __call(self, url, payload, system_id=None):
        headers = {
            'X-Pvoutput-Apikey': self._API,
            'X-Pvoutput-SystemId': system_id,
            'X-Rate-Limit': '1'
        }

        # Make three attempts
        for i in range(3):
            try:
                r = requests.post(url, headers=headers, data=payload, timeout=10)
                reset = round(float(r.headers['X-Rate-Limit-Reset']) - time())
                if int(r.headers['X-Rate-Limit-Remaining']) < 10:
                    print("Only {} requests left, reset after {} seconds".format(
                        r.headers['X-Rate-Limit-Remaining'],
                        reset))
                if r.status_code == 403:
                    print("Forbidden: " + r.reason)
                    sleep(reset + 1)
                else:
                    r.raise_for_status()
                    break
            except requests.exceptions.HTTPError as errh:
                print(localnow().strftime('%Y-%m-%d %H:%M'), "Http Error:", errh)
            except requests.exceptions.ConnectionError as errc:
                print(localnow().strftime('%Y-%m-%d %H:%M'), "Error Connecting:", errc)
            except requests.exceptions.Timeout as errt:
                print(localnow().strftime('%Y-%m-%d %H:%M'), "Timeout Error:", errt)
            except requests.exceptions.RequestException as err:
                print(localnow().strftime('%Y-%m-%d %H:%M'), "Oops: Something Else", err)

            sleep(5)
        else:
            print(localnow().strftime('%Y-%m-%d %H:%M'),
                  "Failed to call PVOutput API after {} attempts.".format(i))

    def send_status(self, date, eactoday=None, pac=None, owm_temp=None, vpv=None, system_id=None):
        # format status payload
        payload = {
            'd': date.strftime('%Y%m%d'),
            't': date.strftime('%H:%M'),
        }

        if eactoday is not None:
            payload['v1'] = eactoday * 1000
        if pac is not None:
            payload['v2'] = pac
        if owm_temp is not None:
            payload['v5'] = owm_temp
        if vpv is not None:
            payload['v6'] = vpv

        # Send status
        print(payload)
        self.add_status(payload, system_id)

    def send_extend(self, date, eactoday=None, eactotal=None, ppv=None, pac=None, vpv=None, temp1=None, system_id=None):
        # format status payload
        payload = {
            'd': date.strftime('%Y%m%d'),
            't': date.strftime('%H:%M'),
        }
        payload['v7'] = eactoday
        payload['v8'] = eactotal
        payload['v9'] = ppv
        payload['v10'] = pac
        payload['v11'] = vpv
        payload['v12'] = temp1

        # Send status
        print(payload)
        self.add_status(payload, system_id)

def main_loop():
    # init
    inv = Inverter(0x1, '/dev/ttyUSB0')
    if OWMKey:
        owm = Weather(OWMKey, CityID)
        owm.fresh = False
    else:
        owm = False

    pvo = PVOutputAPI(APIKEY, SYSTEMID)

    # start and stop monitoring (hour of the day)
    shStart = 5
    shStop = 21
    # Loop until end of universe
    while True:
        if shStart <= localnow().hour < shStop:
            # get fresh temperature from OWM
            if owm:
                try:
                    owm.get()
                    owm.fresh = True
                except Exception as e:
                    print('Error getting weather: {}'.format(e))
                    owm.fresh = False

            # get readings from inverter, if success send  to pvoutput
            inv.read_inputs()
            if inv.status != -1:
                # pvoutput(inv, owm)
                # temperature report only if available
                owm_temp = owm.temperature if owm and owm.fresh else None

                for x in range(3):
                  pvo.send_status(date=inv.date, eactoday=inv.eactoday, pac=inv.pac, owm_temp=owm_temp, vpv=inv.vpv)
                  pvo.send_extend(date=inv.date, eactoday=inv.eactoday, eactotal=inv.eactotal, ppv=inv.ppv, pac=inv.pac, vpv=inv.vpv, temp1=inv.temp1)
                  sleep(5)

                # sleep until next multiple of 5 minutes
                min = 5 - localnow().minute % 5
                sleep(min*60 - localnow().second)
            else:
                # some error
                sleep(60)  # 1 minute before try again
        else:
            # it is too late or too early, let's sleep until next shift
            hour = localnow().hour
            minute = localnow().minute
            if 24 > hour >= shStop:
                # before midnight
                snooze = (((shStart - hour) + 24) * 60) - minute
            elif shStart > hour >= 0:
                # after midnight
                snooze = ((shStart - hour) * 60) - minute
            print(localnow().strftime('%Y-%m-%d %H:%M') + ' - Next shift starts in ' + \
                str(snooze) + ' minutes')
            sys.stdout.flush()
            snooze = snooze * 60  # seconds
            sleep(snooze)


if __name__ == '__main__':
    try:
        main_loop()
    except KeyboardInterrupt:
        print('\nExiting by user request.\n', file=sys.stderr)
        sys.exit(0)
