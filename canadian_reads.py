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

def read_single(row, index, unit=10):
    return float(row.registers[index]) / unit

def read_double(row, index, unit=10):
    return float((row.registers[index] << 16) + row.registers[index + 1]) / unit

class Inverter(object):

    def __init__(self, address, port):
        """Return a Inverter object with port set to *port* and
        values set to their initial state."""
        self._inv = ModbusClient(method='rtu', port=port, baudrate=9600, stopbits=1, parity='N', bytesize=8, timeout=1)
        self._unit = address

        # Inverter properties
        self.date = timezone('UTC').localize(datetime(1970, 1, 1, 0, 0, 0))
        self.status = -1      # Inverter run state
        self.ppv = 0.0        # Ppv // Input PV power (w)
        self.vpv = 0.0        # Vpv1 + Vpv2 // Input voltage 1 channel (V) // Input Voltage 2-way (V)
        self.epvtoday = 0.0   # Epv1_today + Epv2_today // PV1 Energy today  // PV2 Energy today
        self.pac = 0.0        # Pac // Output power (W)
        self.pactogrid = 0.0  # Pactogrid R // AC power to grid
        self.vac1 = 0.0       # Vac1 // Output voltage 1 channel (V)
        self.eactoday = 0     # EacToday // Electricity of the day (kWh)
        self.eactotal = 0     # EacTotal // Cumulative power generation (kWh)
        self.temp1 = 0        # Inverter temperature
        self.cmo_str = ''

    def read_inputs(self):
        """Try read input properties from inverter, return true if succeed"""
        ret = False

        if self._inv.connect():
            # Register Group 1
            r1 = self._inv.read_input_registers(0, 124, unit=self._unit)
            # Register Group 9
            r9 = self._inv.read_input_registers(1000, 66, unit=self._unit)

            if not r1.isError() and not r9.isError():
                ret = True
                self.date = localnow()

                self.status = r1.registers[0]
                if self.status != -1:
                    self.cmo_str = 'Status: '+str(self.status)
                self.ppv = read_double(r1, 1)
                self.vpv = read_single(r1, 3) + read_single(r1, 7)
                self.epvtoday = read_double(r1, 59) + read_double(r1, 63)
                self.pac = read_double(r1, 35)
                self.pactogrid = read_double(r9, 23)
                self.vac1 = read_single(r1, 38)
                self.eactoday = read_double(r1, 53)
                self.eactotal = read_double(r1, 55)
                self.temp1 = read_single(r1, 93)

                #print('{:10}'.format('Date:'), self.date)
                #if self.status == 0: print('{:10}'.format('Status:'), 'Waiting')
                #if self.status == 1: print('{:10}'.format('Status:'), 'Normal')
                #if self.status == 2: print('{:10}'.format('Status:'), 'Fault')
                #print('{:10}'.format('PPv:'), self.ppv, 'W')
                #print('{:10}'.format('Vpv:'), self.vpv, 'V')
                #print('{:10}'.format('EpvToday:'), self.epvtoday, 'kWh')
                #print('{:10}'.format('Pac:'), self.pac, 'W')
                #print('{:10}'.format('PacToGrid:'), self.pactogrid, 'W')
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

    def send_status(self, date, epvtoday=None, ppv=None, owm_temp=None, vpv=None, system_id=None):
        # format status payload
        payload = {
            'd': date.strftime('%Y%m%d'),
            't': date.strftime('%H:%M'),
        }

        if epvtoday is not None:
            payload['v1'] = epvtoday * 1000
        if ppv is not None:
            payload['v2'] = ppv
        if owm_temp is not None:
            payload['v5'] = owm_temp
        if vpv is not None:
            payload['v6'] = vpv

        # Send status
        print(payload)
        self.add_status(payload, system_id)

    def send_extend(self, date, eactoday=None, eactotal=None, pactogrid=None, pac=None, vac1=None, temp1=None, system_id=None):
        # format status payload
        payload = {
            'd': date.strftime('%Y%m%d'),
            't': date.strftime('%H:%M'),
        }
        payload['v7'] = eactoday
        payload['v8'] = eactotal
        payload['v9'] = pactogrid
        payload['v10'] = pac
        payload['v11'] = vac1
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
#    shStart = 5
#    shStop = 21
    # Loop until end of universe
    while True:
        print(localnow().strftime('%Y-%m-%d %H:%M'), "Running now.")
#        if shStart <= localnow().hour < shStop:
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
              pvo.send_status(date=inv.date, epvtoday=inv.epvtoday, ppv=inv.ppv, owm_temp=owm_temp, vpv=inv.vpv)
              pvo.send_extend(date=inv.date, eactoday=inv.eactoday, eactotal=inv.eactotal, pactogrid=inv.pactogrid, pac=inv.pac, vac1=inv.vac1, temp1=inv.temp1)
              sleep(5)

            # sleep until next multiple of 5 minutes
            min = 5 - localnow().minute % 5
            sleep(min*60 - localnow().second)
        else:
            # some error
            sleep(60)  # 1 minute before try again
#        else:
#            # it is too late or too early, let's sleep until next shift
#            hour = localnow().hour
#            minute = localnow().minute
#            if 24 > hour >= shStop:
#                # before midnight
#                snooze = (((shStart - hour) + 24) * 60) - minute
#            elif shStart > hour >= 0:
#                # after midnight
#                snooze = ((shStart - hour) * 60) - minute
#            print(localnow().strftime('%Y-%m-%d %H:%M') + ' - Next shift starts in ' + \
#                str(snooze) + ' minutes')
#            sys.stdout.flush()
#            snooze = snooze * 60  # seconds
#            sleep(snooze)


if __name__ == '__main__':
    try:
        main_loop()
    except KeyboardInterrupt:
        print('\nExiting by user request.\n', file=sys.stderr)
        sys.exit(0)
