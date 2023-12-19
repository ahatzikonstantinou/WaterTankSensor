# !/usr/bin/env python
# -*- coding: utf-8 -*-

# standard library imports
import json  # for working with data file
from threading import Thread
from time import sleep
import os
from enum import IntEnum
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from math import acos, pi, sqrt
import xmpp
import smtplib
from email.mime.text import MIMEText
import traceback # for exception debugging
import ast      # for logging
import io       # for logging
import codecs   # for logging
import threading as th # for timing dead sensors
import time # for timing dead sensors

# local module imports
from blinker import signal
import gv  # Get access to SIP's settings
from sip import template_render  #  Needed for working with web.py templates
from urls import urls  # Get access to SIP's URLs
import web  # web.py framework
from webpages import ProtectedPage  # Needed for security
from webpages import showInFooter # Enable plugin to display readings in UI footer
from webpages import showOnTimeline # Enable plugin to display station data on timeline
from webpages import report_program_toggle 
from plugins import mqtt
from helpers import load_programs, jsave, run_program, stop_stations, schedule_stations, report_stations_scheduled


class WaterTankType(IntEnum):
    RECTANGULAR = 1
    CYLINDRICAL_HORIZONTAL = 2
    CYLINDRICAL_VERTICAL = 3
    ELLIPTICAL = 4


class WaterTankState(IntEnum):
    NORMAL = 1
    OVERFLOW = 2
    OVERFLOW_UNSAFE = 3
    WARNING = 4
    WARNING_UNSAFE = 5
    CRITICAL = 6
    CRITICAL_UNSAFE = 7


class LengthUnit(IntEnum):
    CENTIMETERS = 1
    METERS = 2
    INCHES = 3
    FEET = 4

    @staticmethod
    def ConvertToMeters(unit, number):
        if( unit == LengthUnit.METERS ):
            return number
        elif( unit == LengthUnit.CENTIMETERS ):
            return number / 100
        elif( unit == LengthUnit.INCHES):
            return number * 0.0254
        else:
            return number * 0.3048


class WaterTankProgram():
    """
    These are the programs that run, are enabled or suspended when 
    the water tank enters a state
    """
    def __init__(self, id, run, enable, suspend, start_datetime = None, end_datetime = None, original_enabled = None):
        self.id = id
        self.original_enabled = original_enabled
        self.run = run
        self.enable = enable
        self.suspend = suspend
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime


class WaterTankStation():
    """
    This is a station that will run when the water tank enters a state
    for a certain amount of time or until a certain percentage is reached
    """
    def __init__(self, station_id, run, minutes, percentage, stop_on_exit, start_datetime = None, end_datetime = None):
        self.station_id = station_id
        self.run = run
        self.minutes = minutes
        self.percentage = percentage
        self.stop_on_exit = stop_on_exit
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime


class WaterTank(ABC):
    def __init__(self, id, label, type, sensor_mqtt_topic, invalid_sensor_measurement_email, invalid_sensor_measurement_xmpp, sensor_id, sensor_offset_from_top, min_valid_sensor_measurement, max_valid_sensor_measurement, water_tank_units, sensor_units, enabled, overflow_level, overflow_email, overflow_xmpp, overflow_safe_level, overflow_programs, warning_level, warning_safe_level, warning_email, warning_xmpp, warning_programs, critical_level, critical_safe_level, critical_email, critical_xmpp, critical_programs, loss_email, loss_xmpp, overflow_stations = None, warning_stations = None, critical_stations = None):
        self.id = id
        self.label = label
        self.type = type
        self.sensor_mqtt_topic = sensor_mqtt_topic
        self.invalid_sensor_measurement_email = invalid_sensor_measurement_email
        self.invalid_sensor_measurement_xmpp = invalid_sensor_measurement_xmpp
        self.sensor_id = sensor_id
        self.sensor_offset_from_top = sensor_offset_from_top
        self.min_valid_sensor_measurement = min_valid_sensor_measurement
        self.max_valid_sensor_measurement = max_valid_sensor_measurement
        self.water_tank_units = water_tank_units
        self.sensor_units = sensor_units
        self.enabled = enabled
        self.overflow_level = overflow_level
        self.overflow_email = overflow_email
        self.overflow_xmpp = overflow_xmpp
        self.overflow_safe_level = overflow_safe_level
        self.overflow_programs = overflow_programs
        self.warning_level = warning_level
        self.warning_safe_level = warning_safe_level
        self.warning_email = warning_email
        self.warning_xmpp = warning_xmpp
        self.warning_programs = warning_programs
        self.critical_level = critical_level
        self.critical_safe_level = critical_safe_level
        self.critical_email = critical_email
        self.critical_xmpp = critical_xmpp
        self.critical_programs = critical_programs
        self.loss_email = loss_email
        self.loss_xmpp = loss_xmpp
        self.overflow_stations = overflow_stations
        self.warning_stations = warning_stations
        self.critical_stations = critical_stations
        self.last_updated = None
        self.sensor_measurement = None
        self.invalid_sensor_measurement = False
        self.percentage = None
        self.order = None
        self.state = None
        self.state_change_observers = []
        self.percentage_change_observers = []

    def RegisterStateChangeObserver(self, observer):
        self.state_change_observers.append(observer)
    
    def RegisterPercentageChangeObserver(self, observer):
        self.percentage_change_observers.append(observer)

    def InitFromDict(self, d):
        overflow_programs = {}
        warning_programs = {}
        critical_programs = {}
        overflow_stations = {}
        warning_stations = {}
        critical_stations = {}
                
        #check if this dictionary came from file where fields are stored as dictionary objects
        if("overflow_programs" in d or "warning_programs" in d or "critical_programs" in d):
            for id, program in d['overflow_programs'].items():
                overflow_programs[id] = WaterTankProgram(
                    id = id,
                    run = program["run"],
                    enable = program["enable"],
                    suspend = program["suspend"],
                    start_datetime = program["start_datetime"],
                    end_datetime = program["end_datetime"],
                    original_enabled = program["original_enabled"]
                )
            for id, program in d['warning_programs'].items():            
                warning_programs[id] = WaterTankProgram(
                    id = id,
                    run = program["run"],
                    enable = program["enable"],
                    suspend = program["suspend"],
                    start_datetime = program["start_datetime"],
                    end_datetime = program["end_datetime"],
                    original_enabled = program["original_enabled"]
                )
            for id, program in d['critical_programs'].items():                        
                critical_programs[id] = WaterTankProgram(
                    id = id,
                    run = program["run"],
                    enable = program["enable"],
                    suspend = program["suspend"],
                    start_datetime = program["start_datetime"],
                    end_datetime = program["end_datetime"],
                    original_enabled = program["original_enabled"]
                )
            for id, station in d['overflow_stations'].items():
                overflow_stations[id] = WaterTankStation(
                    station_id = id,
                    run = station["run"],
                    minutes = station['minutes'],
                    percentage = station['percentage'],
                    stop_on_exit = station['stop_on_exit'],
                    start_datetime = station["start_datetime"],
                    end_datetime = station["end_datetime"]
                )
            for id, station in d['warning_stations'].items():
                warning_stations[id] = WaterTankStation(
                    station_id = id,
                    run = station["run"],
                    minutes = station['minutes'],
                    percentage = station['percentage'],
                    stop_on_exit = station['stop_on_exit'],
                    start_datetime = station["start_datetime"],
                    end_datetime = station["end_datetime"]
                )
            for id, station in d['critical_stations'].items():
                critical_stations[id] = WaterTankStation(
                    station_id = id,
                    run = station["run"],
                    minutes = station['minutes'],
                    percentage = station['percentage'],
                    stop_on_exit = station['stop_on_exit'],
                    start_datetime = station["start_datetime"],
                    end_datetime = station["end_datetime"]
                )
        else:   #this dictionary came from form submission, fields are like overflow_pr_run_#
            for i in range(0, len(gv.pnames)):
                overflow_programs[i] = WaterTankProgram(
                    id = i,
                    run = ('overflow_pr_run_' + str(i) in d and str(d['overflow_pr_run_' + str(i)]) in ["on", "true", "True"]),
                    enable = ('overflow_pr_enable_' + str(i) in d and str(d['overflow_pr_enable_' + str(i)]) in ["on", "true", "True"]),
                    suspend = ('overflow_pr_suspend_' + str(i) in d and str(d['overflow_pr_suspend_' + str(i)]) in ["on", "true", "True"]),
                    original_enabled = None if 'overflow_original_enabled_pr' + str(i) not in d else d['overflow_original_enabled_pr' + str(i)]
                )
            
                warning_programs[i] = WaterTankProgram(
                    id = i,
                    run = ('warning_pr_run_' + str(i) in d and str(d['warning_pr_run_' + str(i)]) in ["on", "true", "True"]),
                    enable = ('warning_pr_enable_' + str(i) in d and str(d['warning_pr_enable_' + str(i)]) in ["on", "true", "True"]),
                    suspend = ('warning_pr_suspend_' + str(i) in d and str(d['warning_pr_suspend_' + str(i)]) in ["on", "true", "True"]),
                    original_enabled = None if 'warning_original_enabled_pr' + str(i) not in d else d['warning_original_enabled_pr' + str(i)]
                )
            
                critical_programs[i] = WaterTankProgram(
                    id = i,
                    run = ('critical_pr_run_' + str(i) in d and str(d['critical_pr_run_' + str(i)]) in ["on", "true", "True"]),
                    enable = ('critical_pr_enable_' + str(i) in d and str(d['critical_pr_enable_' + str(i)]) in ["on", "true", "True"]),
                    suspend = ('critical_pr_suspend_' + str(i) in d and str(d['critical_pr_suspend_' + str(i)]) in ["on", "true", "True"]),
                    original_enabled = None if 'critical_original_enabled_pr' + str(i) not in d else d['critical_original_enabled_pr' + str(i)]
                )

            for i in range(0, len(gv.snames)):
                station_enabled = (gv.sd['show'][i//8]>>(i%8))&1
                if station_enabled == 1:                        
                    overflow_stations[i] = WaterTankStation(
                        station_id = i,
                        run = ('overflow_sn_run_' + str(i) in d and str(d['overflow_sn_run_' + str(i)]) in ["on", "true", "True"]),
                        minutes = None if not d["overflow_sn_minutes_" + str(i)] else int(d["overflow_sn_minutes_" + str(i)]),
                        percentage = None if not d["overflow_sn_percentage_" + str(i)] else int(d["overflow_sn_percentage_" + str(i)]),
                        stop_on_exit = ('overflow_sn_stop_on_exit_' + str(i) in d and str(d['overflow_sn_stop_on_exit_' + str(i)]) in ["on", "true", "True"]),
                    )

                    warning_stations[i] = WaterTankStation(
                        station_id = i,
                        run = ('warning_sn_run_' + str(i) in d and str(d['warning_sn_run_' + str(i)]) in ["on", "true", "True"]),
                        minutes = None if not d["warning_sn_minutes_" + str(i)] else int(d["warning_sn_minutes_" + str(i)]),
                        percentage = None if not d["warning_sn_percentage_" + str(i)] else int(d["warning_sn_percentage_" + str(i)]),
                        stop_on_exit = ('warning_sn_stop_on_exit_' + str(i) in d and str(d['warning_sn_stop_on_exit_' + str(i)]) in ["on", "true", "True"]),
                    )

                    critical_stations[i] = WaterTankStation(
                        station_id = i,
                        run = ('critical_sn_run_' + str(i) in d and str(d['critical_sn_run_' + str(i)]) in ["on", "true", "True"]),
                        minutes = None if not d["critical_sn_minutes_" + str(i)] else int(d["critical_sn_minutes_" + str(i)]),
                        percentage = None if not d["critical_sn_percentage_" + str(i)] else int(d["critical_sn_percentage_" + str(i)]),
                        stop_on_exit = ('critical_sn_stop_on_exit_' + str(i) in d and str(d['critical_sn_stop_on_exit_' + str(i)]) in ["on", "true", "True"]),
                    )

        self.id = d["id"]
        self.label = d["label"]
        self.sensor_mqtt_topic = d["sensor_mqtt_topic"]
        self.invalid_sensor_measurement_email = (INVALID_SENSOR_MEASUREMENT_EMAIL in d and (str(d[INVALID_SENSOR_MEASUREMENT_EMAIL]) in ["on", "true", "True"]))
        self.invalid_sensor_measurement_xmpp = (INVALID_SENSOR_MEASUREMENT_XMPP in d and (str(d[INVALID_SENSOR_MEASUREMENT_XMPP]) in ["on", "true", "True"]))
        self.sensor_id = d["sensor_id"]
        self.sensor_offset_from_top = float(d["sensor_offset_from_top"])
        self.min_valid_sensor_measurement = None if "min_valid_sensor_measurement" not in d or not d["min_valid_sensor_measurement"] else float(d["min_valid_sensor_measurement"])
        self.max_valid_sensor_measurement = None if "max_valid_sensor_measurement"not in d or not d["max_valid_sensor_measurement"] else float(d["max_valid_sensor_measurement"])
        self.water_tank_units = WaterTankType( int(d["water_tank_units"]) )
        self.sensor_units = WaterTankType( int(d["sensor_units"]) )
        self.enabled = ("enabled" in d and str(d["enabled"]) in ["on", "true", "True"])
        self.overflow_level = None if not d["overflow_level"] else float(d["overflow_level"])
        self.overflow_email = ('overflow_email' in d and (str(d["overflow_email"]) in ["on", "true", "True"]))
        self.overflow_xmpp = ('overflow_xmpp' in d and (str(d["overflow_xmpp"]) in ["on", "true", "True"]))
        self.overflow_safe_level = None if not d["overflow_safe_level"] else float(d["overflow_safe_level"])
        self.overflow_programs = overflow_programs
        self.warning_level = None if not d["warning_level"] else float(d["warning_level"])
        self.warning_safe_level = None if not d["warning_safe_level"] else float(d["warning_safe_level"])
        self.warning_email = ('warning_email' in d and (str(d["warning_email"]) in ["on", "true", "True"]))
        self.warning_xmpp = ('warning_xmpp' in d and (str(d["warning_xmpp"]) in ["on", "true", "True"]))
        self.warning_programs = warning_programs
        self.critical_level = None if not d["critical_level"] else float( d["critical_level"])
        self.critical_safe_level = None if not d["critical_safe_level"] else float( d["critical_safe_level"])
        self.critical_email = ('critical_email' in d and (str(d["critical_email"]) in ["on", "true", "True"]))
        self.critical_xmpp = ('critical_xmpp' in d and (str(d["critical_xmpp"]) in ["on", "true", "True"]))
        self.critical_programs = critical_programs
        self.loss_email = ('loss_email' in d and (str(d["loss_email"]) in ["on", "true", "True"]))
        self.loss_xmpp = ('loss_xmpp' in d and (str(d["loss_xmpp"]) in ["on", "true", "True"]))
        self.overflow_stations = overflow_stations
        self.warning_stations = warning_stations
        self.critical_stations = critical_stations
        self.last_updated = None if 'last_updated' not in d else d["last_updated"]
        self.sensor_measurement = None if 'sensor_measurement' not in d else d["sensor_measurement"]
        self.invalid_sensor_measurement = None if 'invalid_sensor_measurement' not in d else d["invalid_sensor_measurement"]
        self.percentage = None if 'percentage' not in d else float(d["percentage"])
        self.order = None if "order" not in d else int( d["order"])
        self.state = None if "state" not in d or d["state"] is None or d["state"] == "null" else WaterTankState( int(d["state"]) )

    def MeasurementIsValid(self, measurement):
        h = LengthUnit.ConvertToMeters(self.water_tank_units, self.GetHeight())
        m = LengthUnit.ConvertToMeters(self.sensor_units, measurement)
        o = LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top)
        print( "Validating h:{}, m: {}, offset:{}".format(h, m, o))
        if( (self.min_valid_sensor_measurement is not None and measurement < self.min_valid_sensor_measurement) or 
            (self.max_valid_sensor_measurement is not None and measurement > self.max_valid_sensor_measurement) or
            (h < (m - o)) or
            (measurement < 0)
        ):
            return False
         
        return True
    
    def UpdateSensorMeasurement(self, sensor_id, measurement):
        self.last_updated = datetime.now().replace(microsecond=0)
        self.sensor_measurement = measurement
        if( not self.MeasurementIsValid(measurement) ):
            self.invalid_sensor_measurement = True
            self.percentage = None
            send_invalid_measurement_msg(self, self.AdditionalInfo4Msg())
            return False

        percentageBefore = self.percentage
        self.invalid_sensor_measurement = False
        percentage = self.CalculatePercentage(measurement)
        if percentage is None:
            self.invalid_sensor_measurement = True
            self.percentage = None
            return False
        
        self.percentage = percentage
        self.StopStationsOnPercentageChange(percentageBefore)
        self.SignalPercentageChanged() # in order to let parent class call observers
        self.SetState()
        return True

    def AdditionalInfo4Msg(self):
        return "type: {}, min_valid_sensor_measurement: '{}', max_valid_sensor_measurement: '{}'".format(WaterTankType(self.type).name, self.min_valid_sensor_measurement, self.max_valid_sensor_measurement)
    
    @abstractmethod
    def GetHeight(self):
        """
        Should return the actual height of the tank. Straightforward for rectangular and vertical cylindrical.
        For horizontal cylindrical it should be the diameter, and for elliptical it should be the vertical axis.
        """
        pass
        
    @abstractmethod
    def CalculatePercentage(self, measurement):
        """
        Return the percentage at which the tank is filled.
        """
        pass

    def CalculateNewState(self):
        print("Existing state:{}".format("None" if self.state is None else WaterTankState(self.state).name))

        if(self.percentage is None):
            print("New state is None")
            return None
        
        if(self.overflow_level is not None and self.percentage >= self.overflow_level):
            print("New state is OVERFLOW")
            return WaterTankState.OVERFLOW
        
        if(self.overflow_safe_level is not None and 
           (self.state in [WaterTankState.OVERFLOW, WaterTankState.OVERFLOW_UNSAFE]) and
           self.percentage >= self.overflow_safe_level and self.percentage < self.overflow_level
        ):
            print("New state is OVERFLOW_UNSAFE")
            return WaterTankState.OVERFLOW_UNSAFE
    
        if(self.critical_level is not None and self.percentage <= self.critical_level):
            print("New state is CRITICAL")
            return WaterTankState.CRITICAL
        
        if(self.critical_safe_level is not None and 
           (self.state in [WaterTankState.CRITICAL, WaterTankState.CRITICAL_UNSAFE]) and
           self.percentage <= self.critical_safe_level and self.percentage > self.critical_level
        ):
            print("New state is CRITICAL_UNSAFE")
            return WaterTankState.CRITICAL_UNSAFE

        # Tank is not in OVERFLOW, OVERFLOW_UNSAFE, CRITICAL, CRITICAL_UNSAFE
        if(self.warning_level is not None and self.percentage <= self.warning_level):
            print("New state is WARNING")
            return WaterTankState.WARNING
        
        # Tank is not in OVERFLOW, OVERFLOW_UNSAFE, CRITICAL, CRITICAL_UNSAFE, WARNING
        if(self.warning_safe_level is not None and 
           (self.state in [WaterTankState.WARNING, WaterTankState.WARNING_UNSAFE]) and
           self.percentage <= self.warning_safe_level and self.percentage > self.warning_level
        ):
            print("New state is WARNING_UNSAFE")
            return WaterTankState.WARNING_UNSAFE

        # Tank is not in OVERFLOW, OVERFLOW_UNSAFE, CRITICAL, CRITICAL_UNSAFE, WARNING, WARNING_UNSAFE
        # and there is a valid percentage
        print("New state is NORMAL")
        return WaterTankState.NORMAL

    def StopSignleStationOnPercentageChange(self, percentageBefore, station, station_mask, board_index, station_board_index,
                                            overall_station_index):
        if(station.run and station.percentage is not None and
            station.start_datetime is not None and station.end_datetime is None
        ):
            if( (percentageBefore <= station.percentage and self.percentage > station.percentage) or
                (percentageBefore >= station.percentage and self.percentage < station.percentage)
            ):                           
                print("Stopping on percentage change running station {}. {}".format(overall_station_index, gv.snames[overall_station_index]))
                station_mask[board_index] = station_mask[board_index] | (1 << station_board_index);
                station.end_datetime = datetime.now().replace(microsecond=0)                
                gv.rs[overall_station_index][2] = 0         #set duration to 0
                gv.rs[overall_station_index][1] = gv.now    #set stop time now
                return True                                    

        return False
    
    def StopStationsOnPercentageChange(self, percentageBefore):
        station_changed = False
        station_mask = [0] * gv.sd["nbrd"] # a list of bitmasks, each bitmask representing the 8 stations of a board                        
        try:
            for b in range(gv.sd["nbrd"]): # for all boards
                for s in range(8): # for each station in the board
                    i = b*8 + s
                    key_i = str(i)
                    if i + 1 == gv.sd["mas"]:
                        continue  # skip if this is master valve
                    station_changed = self.StopSignleStationOnPercentageChange(percentageBefore, self.overflow_stations[key_i],
                        station_mask, b, s, i ) or station_changed
                    station_changed = self.StopSignleStationOnPercentageChange(percentageBefore, self.warning_stations[key_i],
                        station_mask, b, s, i ) or station_changed
                    station_changed = self.StopSignleStationOnPercentageChange(percentageBefore, self.critical_stations[key_i],
                        station_mask, b, s, i ) or station_changed

            if(station_changed):
                report_stations_scheduled()
        except Exception as e:
            print("Exception in StopStationsOnPercentageChange", e)

    def StopStationsOnEventExit(self, state):
        valid_states = [WaterTankState.OVERFLOW, WaterTankState.WARNING, WaterTankState.CRITICAL, WaterTankState.OVERFLOW_UNSAFE, WaterTankState.WARNING_UNSAFE, WaterTankState.CRITICAL_UNSAFE]
        if(state not in valid_states):
            raise Exception("Invalid state: '{}'. Only states {} allowed in StopStations".
                            format(state.name, ", ".join([v.name for v in valid_states])))
        
        stations = self.overflow_stations
        if(state in [WaterTankState.WARNING, WaterTankState.WARNING_UNSAFE]):
            stations = self.warning_stations
        elif(state in [WaterTankState.CRITICAL, WaterTankState.CRITICAL_UNSAFE]):
            stations = self.critical_stations

        station_changed = False
        station_mask = [0] * gv.sd["nbrd"] # a list of bitmasks, each bitmask representing the 8 stations of a board                        
        try:
            for b in range(gv.sd["nbrd"]): # for all boards
                for s in range(8): # for each station in the board
                    i = b*8 + s
                    key_i = str(i)
                    station_enabled = (gv.sd['show'][b]>>s)&1
                    if( station_enabled == 1 and
                        stations[key_i].run and stations[key_i].stop_on_exit and
                        stations[key_i].start_datetime is not None and stations[key_i].end_datetime is None ):
                        print("Stopping on event exit running station {}. {}".format(i, gv.snames[i]))
                        station_mask[b] = station_mask[b] | (1 << s);
                        stations[key_i].end_datetime = datetime.now().replace(microsecond=0)
                        if i + 1 == gv.sd["mas"]:
                            continue  # skip if this is master valve
                        gv.rs[i][2] = 0         #set duration to 0
                        gv.rs[i][1] = gv.now    #set stop time now
                        station_changed = True                                    

            if(station_changed):
                report_stations_scheduled()
        except Exception as e:
            print("Exception in StopStationsOnEventExit", e)
            
    def RevertPrograms(self, state):
        """
        Put progams to their original enabled state.
        This method should be called when exiting one of OVERFLOW, WARNING, CRITICAL states
        """
        valid_states = [WaterTankState.OVERFLOW, WaterTankState.WARNING, WaterTankState.CRITICAL, WaterTankState.OVERFLOW_UNSAFE, WaterTankState.WARNING_UNSAFE, WaterTankState.CRITICAL_UNSAFE]
        if(state not in valid_states):
            raise Exception("Invalid state: '{}'. Only states {} allowed in ActivatePrograms".
                            format(state.name, ", ".join([v.name for v in valid_states])))
        
        print("Reverting {} programs".format(state.name))
        prs = self.overflow_programs
        if(state in [WaterTankState.WARNING, WaterTankState.WARNING_UNSAFE]):
            prs = self.warning_programs
        elif(state in [WaterTankState.CRITICAL, WaterTankState.CRITICAL_UNSAFE]):
            prs = self.critical_programs

        program_changed = False
        for i in range(0, len(gv.pd) ):
            key_i = str(i)
            if(prs[key_i].original_enabled is not None and gv.pd[i]["enabled"] != prs[key_i].original_enabled):
                print("{} program {}. {}"
                      .format(('Enabling' if prs[key_i].original_enabled else 'Disabling'), i, gv.pnames[i]))
                gv.pd[i]["enabled"] = prs[key_i].original_enabled
                program_changed = True
            
            # if a program is still running
            # print("Checking gv.pon:{} against running program:{}".format(gv.pon, json.dumps(prs[key_i], default=serialize_datetime)))
            if(self.CheckAndMarkProgramEnd(prs[key_i])):
                # stop it
                # actually stop all running stations as all can only belong to the same program
                # since only one program can run at a time
                print("Program {} was still running, stopping it now".format(gv.pnames[i]))
                stop_stations()

        if(program_changed):
            jsave(gv.pd, "programData")
            report_program_toggle()
        print("RevertPrograms finished")

    def ActivateStations(self, state):
        """
        Activate stations.
        This method should be called when entering one of OVERFLOW, WARNING, CRITICAL states
        """
        valid_states = [WaterTankState.OVERFLOW, WaterTankState.WARNING, WaterTankState.CRITICAL]
        if(state not in valid_states):
            raise Exception("Invalid state: '{}'. Only states {} allowed in ActivatePrograms".
                            format(state.name, ", ".join([v.name for v in valid_states])))
        
        print("Activating {} stations".format(state.name))
        sns = self.overflow_stations
        if(state == WaterTankState.WARNING):
            sns = self.warning_stations
        elif(state == WaterTankState.CRITICAL):
            sns = self.critical_stations

        settings = get_settings()
        station_changed = False
        station_mask = [0] * gv.sd["nbrd"] # a list of bitmasks, each bitmask representing the 8 stations of a board                        
        try:
            for b in range(gv.sd["nbrd"]): # for all boards
                for s in range(8): # for each station in the board
                    i = b*8 + s
                    key_i = str(i)
                    station_enabled = (gv.sd['show'][b]>>s)&1
                    if( station_enabled == 1 and sns[key_i].run):
                        print("Running station {}. {}".format(i, gv.snames[i]))
                        station_mask[b] = station_mask[b] | (1 << s);
                        sns[key_i].start_datetime = datetime.now().replace(microsecond=0)
                        sns[key_i].end_datetime = None
                        if i + 1 == gv.sd["mas"]:
                            continue  # skip if this is master valve
                        duration = sns[key_i].minutes*60 if sns[key_i].minutes is not None else settings[MAX_STATION_DURATION]
                        gv.rs[i][2] = duration
                        station_changed = True                                    

            if(station_changed):
                schedule_stations(station_mask)
        except Exception as e:
            print("Exception in ActivatePrograms state", e)

    def ActivatePrograms(self, state):
        """
        Activate progams.
        This method should be called when entering one of OVERFLOW, WARNING, CRITICAL states
        """
        valid_states = [WaterTankState.OVERFLOW, WaterTankState.WARNING, WaterTankState.CRITICAL]
        if(state not in valid_states):
            raise Exception("Invalid state: '{}'. Only states {} allowed in ActivatePrograms".
                            format(state.name, ", ".join([v.name for v in valid_states])))
        
        print("Activating {} programs".format(state.name))
        prs = self.overflow_programs
        if(state == WaterTankState.WARNING):
            prs = self.warning_programs
        elif(state == WaterTankState.CRITICAL):
            prs = self.critical_programs

        program_changed = False
        try:
            for i in range(0, len(gv.pd) ):
                key_i = str(i)
                if(prs[key_i].run):
                    print("Running program {}. {}".format(i, gv.pnames[i]))
                    prs[key_i].start_datetime = datetime.now().replace(microsecond=0)
                    prs[key_i].end_datetime = None
                    run_program(i)
                if(prs[key_i].suspend and gv.pd[i]["enabled"] == 1):
                    print("Disabling previously enabled program {}. {}".format(i, gv.pnames[i]))
                    prs[key_i].original_enabled = gv.pd[i]["enabled"]
                    gv.pd[i]["enabled"] = 0
                    program_changed = True
                if(prs[key_i].enable and gv.pd[i]["enabled"] == 0):
                    print("Enabling previously disabled program {}. {}".format(i, gv.pnames[i]))
                    prs[key_i].original_enabled = gv.pd[i]["enabled"]
                    gv.pd[i]["enabled"] = 1
                    program_changed = True

            if(program_changed):
                jsave(gv.pd, "programData")
                report_program_toggle()
        except Exception as e:
            print("Exception in ActivatePrograms state", e)

    @staticmethod
    def CheckAndMarkProgramEnd(program, except_same_id_program = False):
        # print("Comparing gv.pon: {} against program:{}".format(gv.pon, json.dumps(program, default=serialize_datetime)))
        if(except_same_id_program):
            if((gv.pon is None or (gv.pon-1) != int(program.id)) and 
                program.start_datetime is not None and program.end_datetime is None
            ):
                print("except_same_id_program:{}, gv.pon:{}, Program ({}) {} was still running, marking it stopped now".format(except_same_id_program, gv.pon, program.id, gv.pnames[int(program.id)]))
                program.end_datetime = datetime.now().replace(microsecond=0)
                return True
        else:
            if(program.start_datetime is not None and program.end_datetime is None):
                print("except_same_id_program:{}, gv.pon:{}, Program ({}) {} was still running, marking it stopped now".format(except_same_id_program, gv.pon, program.id, gv.pnames[int(program.id)]))
                program.end_datetime = datetime.now().replace(microsecond=0)
                return True
        
        return False
    
    @staticmethod
    def CheckAndMarkStationEnd(station):
        # print("CheckAndMarkStationEnd gv.srvals:".format(json.dumps(gv.srvals, default=serialize_datetime)))
        # print(gv.srvals)
        #    
        # mark end_datetime for stopped stations
        station_index = int(station.station_id)
        if( gv.srvals[station_index] == 0 and station.run and 
           station.start_datetime is not None and station.end_datetime is None):
            print("Marking ended station {}. {}".format(station_index, gv.snames[station_index]))
            station.end_datetime = datetime.now().replace(microsecond=0)
            return True
        
        return False

    def RunningProgramChanged(self):
        # print("RunningProgramChanged for state: {}".format(None if self.state is None else self.state.name))
        programUpdated = False
        # print("Doing OVERFLOW programs.")
        for p_id, program in self.overflow_programs.items():
            programUpdated = self.CheckAndMarkProgramEnd(program, self.state in [WaterTankState.OVERFLOW, WaterTankState.OVERFLOW_UNSAFE] ) or programUpdated
        # print("Doing WARNING programs.")
        for p_id, program in self.warning_programs.items():
            programUpdated = self.CheckAndMarkProgramEnd(program, self.state in [WaterTankState.WARNING, WaterTankState.WARNING_UNSAFE]) or programUpdated
        # print("Doing CRITICAL programs.")
        for p_id, program in self.critical_programs.items():
            programUpdated = self.CheckAndMarkProgramEnd(program, self.state in [WaterTankState.CRITICAL, WaterTankState.CRITICAL_UNSAFE]) or programUpdated

        return programUpdated
    
    def ZoneChanged(self):
        # print("StationCompleted for state: {}".format(None if self.state is None else self.state.name))
        stationUpdated = False
        # print("Doing OVERFLOW stations.")
        for station_id, station in self.overflow_stations.items():
            stationUpdated = self.CheckAndMarkStationEnd(station) or stationUpdated
        # print("Doing WARNING stations.")
        for station_id, station in self.warning_stations.items():
            stationUpdated = self.CheckAndMarkStationEnd(station) or stationUpdated
        # print("Doing CRITICAL stations.")
        for station_id, station in self.critical_stations.items():
            stationUpdated = self.CheckAndMarkStationEnd(station) or stationUpdated

        return stationUpdated
        
    def SignalPercentageChanged(self):
        """
        This function is called by child classes when mearument has been accepted as valid
        and before state change.
        WaterTank will call observers e.g. detect water loss if no valves are open
        This function must be called before SetState because setting the new state may involve
        running an emergency program in case the new state is CRITICAL, etc. In such a case valves are
        already open because of the emergency program and PercentageChange observers will 
        not detect water loss
        """
        for o in self.percentage_change_observers:
            o.WaterTankPercentageChanged(self)

    def SetState(self):
        new_state = self.CalculateNewState()
        if(new_state is None or self.state == new_state):
            return
        
        # water tank is definitely entering a new state
        #
        # Revert activated programs
        if( (self.state == WaterTankState.OVERFLOW and new_state != WaterTankState.OVERFLOW_UNSAFE) or
            (self.state == WaterTankState.OVERFLOW_UNSAFE and new_state != WaterTankState.OVERFLOW) or
            (self.state == WaterTankState.CRITICAL and new_state != WaterTankState.CRITICAL_UNSAFE) or
            (self.state == WaterTankState.CRITICAL_UNSAFE and new_state != WaterTankState.CRITICAL) or
            (self.state == WaterTankState.WARNING and new_state != WaterTankState.WARNING_UNSAFE) or
            (self.state == WaterTankState.WARNING_UNSAFE and new_state != WaterTankState.WARNING)
        ):
            if(self.enabled):
                self.RevertPrograms(self.state)
                self.StopStationsOnEventExit(self.state)

        #
        # Activate programs for entering new state
        if( (new_state == WaterTankState.OVERFLOW and self.state != WaterTankState.OVERFLOW_UNSAFE) or
            (new_state == WaterTankState.CRITICAL and self.state != WaterTankState.CRITICAL_UNSAFE) or
            (new_state == WaterTankState.WARNING and self.state != WaterTankState.WARNING_UNSAFE)
        ):
            if(self.enabled):            
                self.ActivatePrograms(new_state)
                self.ActivateStations(new_state)

        self.state = new_state

        for o in self.state_change_observers:
            o.WaterTankStateChanged(self)
    

class WaterTankRectangular(WaterTank):
    def __init__(self, id = None, label = None, width = None, length = None, height = None, sensor_mqtt_topic = None, invalid_sensor_measurement_email = None, invalid_sensor_measurement_xmpp = None, sensor_id = None, sensor_offset_from_top = None, min_valid_sensor_measurement = None,max_valid_sensor_measurement = None, water_tank_units = None, sensor_units = None, enabled = None, overflow_level = None, overflow_email = None, overflow_xmpp = None, overflow_safe_level = None, overflow_programs = None, warning_level = None, warning_safe_level = None, warning_email = None, warning_xmpp = None, warning_programs = None, critical_level = None, critical_safe_level = None, critical_email = None, critical_xmpp = None, critical_programs = None, loss_email = None, loss_xmpp = None):
        super().__init__(id, label, WaterTankType.RECTANGULAR.value, sensor_mqtt_topic, invalid_sensor_measurement_email, invalid_sensor_measurement_xmpp, sensor_id, sensor_offset_from_top, min_valid_sensor_measurement, max_valid_sensor_measurement,  water_tank_units, sensor_units, enabled, overflow_level, overflow_email, overflow_xmpp, overflow_safe_level, overflow_programs, warning_level, warning_safe_level, warning_email, warning_xmpp, warning_programs, critical_level, critical_safe_level, critical_email, critical_xmpp, critical_programs, loss_email, loss_xmpp)
        self.width = width
        self.length = length
        self.height = height
    
    def FromDict(d):
        wt = WaterTankRectangular()
        wt.InitFromDict(d)
        wt.width = None if not d["width"] else float(d["width"])
        wt.length = None if not d["length"] else float(d["length"])
        wt.height = None if not d["height"] else float(d["height"])
        return wt
                
    def MeasurementIsValid(self, measurement):
        if( not super().MeasurementIsValid(measurement)):
            return False
        
        if( LengthUnit.ConvertToMeters(self.water_tank_units, self.height) < (LengthUnit.ConvertToMeters(self.sensor_units, measurement) - LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top)) ):
            return False
        
        return True

    def CalculatePercentage(self, measurement):
        if self.width is not None and self.length is not None and self.height is not None and self.height > 0:
            h = LengthUnit.ConvertToMeters(self.water_tank_units, self.height)
            d = LengthUnit.ConvertToMeters(self.sensor_units, measurement) - LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top)
            return round(100.0 * (h -d) / h)
        
        return None

    def GetHeight(self):
        return self.height


class WaterTankCylindricalHorizontal(WaterTank):
    def __init__(self, id = None, label = None, length = None, diameter = None, sensor_mqtt_topic = None, invalid_sensor_measurement_email = None, invalid_sensor_measurement_xmpp = None, sensor_id = None, sensor_offset_from_top = None, min_valid_sensor_measurement = None,max_valid_sensor_measurement = None, water_tank_units = None, sensor_units = None, enabled = None, overflow_level = None, overflow_email = None, overflow_xmpp = None, overflow_safe_level = None, overflow_programs = None, warning_level = None, warning_safe_level = None, warning_email = None, warning_xmpp = None, warning_programs = None, critical_level = None, critical_safe_level = None, critical_email = None, critical_xmpp = None, critical_programs = None, loss_email = None, loss_xmpp = None):
        super().__init__(id, label, WaterTankType.CYLINDRICAL_HORIZONTAL.value, sensor_mqtt_topic, invalid_sensor_measurement_email, invalid_sensor_measurement_xmpp, sensor_id, sensor_offset_from_top, min_valid_sensor_measurement, max_valid_sensor_measurement, water_tank_units, sensor_units, enabled, overflow_level, overflow_email, overflow_xmpp, overflow_safe_level, overflow_programs, warning_level, warning_safe_level, warning_email, warning_xmpp, warning_programs, critical_level, critical_safe_level, critical_email, critical_xmpp, critical_programs, loss_email, loss_xmpp)
        self.length = length
        self.diameter = diameter

    def FromDict(d):
        wt = WaterTankCylindricalHorizontal()
        wt.InitFromDict(d)
        wt.length = None if not d["length"] else float(d["length"])
        wt.diameter = None if not d["diameter"] else float(d["diameter"])
        return wt

    def MeasurementIsValid(self, measurement):
        if( not super().MeasurementIsValid(measurement)):
            return False
        
        if( LengthUnit.ConvertToMeters(self.water_tank_units, self.diameter) < (LengthUnit.ConvertToMeters(self.sensor_units, measurement) - LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top))):
            return False
        
        return True
    
    def CalculatePercentage(self, measurement):
        if self.diameter is not None and self.length is not None:
            volume = LengthUnit.ConvertToMeters(self.water_tank_units, self.diameter) * LengthUnit.ConvertToMeters(self.water_tank_units, self.length)
            r = LengthUnit.ConvertToMeters(self.water_tank_units, self.diameter) / 2.0
            h = LengthUnit.ConvertToMeters(self.water_tank_units, self.diameter) - (LengthUnit.ConvertToMeters(self.sensor_units, measurement) - LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top))
            try:
                liquid_volume = acos((r-h)/r)*(r**2) - (r-h)*sqrt(2*r*h - (h**2))
                return round(100.0 * liquid_volume / volume)
            except:
                return None
        
        return None

    def GetHeight(self):
        return self.diameter


class WaterTankCylindricalVertical(WaterTank):
    def __init__(self, id = None, label = None, diameter = None, height = None, sensor_mqtt_topic = None, invalid_sensor_measurement_email = None, invalid_sensor_measurement_xmpp = None, sensor_id = None, sensor_offset_from_top = None, min_valid_sensor_measurement = None,max_valid_sensor_measurement = None, water_tank_units = None, sensor_units = None, enabled = None, overflow_level = None, overflow_email = None, overflow_xmpp = None, overflow_safe_level = None, overflow_programs = None, warning_level = None, warning_safe_level = None, warning_email = None, warning_xmpp = None, warning_programs = None, critical_level = None, critical_safe_level = None, critical_email = None, critical_xmpp = None, critical_programs = None, loss_email = None, loss_xmpp = None):
        super().__init__(id, label, WaterTankType.CYLINDRICAL_VERTICAL.value, sensor_mqtt_topic, invalid_sensor_measurement_email, invalid_sensor_measurement_xmpp, sensor_id, sensor_offset_from_top, min_valid_sensor_measurement, max_valid_sensor_measurement, water_tank_units, sensor_units, enabled, overflow_level, overflow_email, overflow_xmpp, overflow_safe_level, overflow_programs, warning_level, warning_safe_level, warning_email, warning_xmpp, warning_programs, critical_level, critical_safe_level, critical_email, critical_xmpp, critical_programs, loss_email, loss_xmpp)
        self.height = height
        self.diameter = diameter

    def FromDict(d):
        wt = WaterTankCylindricalVertical()
        wt.InitFromDict(d)
        wt.height = None if not d["height"] else float(d["height"])
        wt.diameter = None if not d["diameter"] else float(d["diameter"])
        return wt

    def MeasurementIsValid(self, measurement):
        if( not super().MeasurementIsValid(measurement)):
            return False
        
        if( LengthUnit.ConvertToMeters(self.water_tank_units, self.height) < (LengthUnit.ConvertToMeters(self.sensor_units, measurement) - LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top) ) ):
            return False
        
        return True
    
    def CalculatePercentage(self, measurement):
        if self.diameter is not None and self.height is not None and self.height > 0:
            h = LengthUnit.ConvertToMeters(self.water_tank_units, self.height)
            d = LengthUnit.ConvertToMeters(self.water_tank_units, self.diameter)
            x = LengthUnit.ConvertToMeters(self.sensor_units, measurement) - LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top)
            volume = d * h
            return round(100.0 * (h - x) / h)
        
        return None

    def GetHeight(self):
        return self.height


class WaterTankElliptical(WaterTank):
    def __init__(self, id = None, label = None, length = None, horizontal_axis = None, vertical_axis = None, sensor_mqtt_topic = None, invalid_sensor_measurement_email = None, invalid_sensor_measurement_xmpp = None, sensor_id = None, sensor_offset_from_top = None, min_valid_sensor_measurement = None,max_valid_sensor_measurement = None, water_tank_units = None, sensor_units = None, enabled = None, overflow_level = None, overflow_email = None, overflow_xmpp = None, overflow_safe_level = None, overflow_programs = None, warning_level = None, warning_safe_level = None, warning_email = None, warning_xmpp = None, warning_programs = None, critical_level = None, critical_safe_level = None, critical_email = None, critical_xmpp = None, critical_programs = None, loss_email = None, loss_xmpp = None):
        super().__init__(id, label, WaterTankType.ELLIPTICAL.value, sensor_mqtt_topic, invalid_sensor_measurement_email, invalid_sensor_measurement_xmpp, sensor_id, sensor_offset_from_top, min_valid_sensor_measurement, max_valid_sensor_measurement, water_tank_units, sensor_units, enabled, overflow_level, overflow_email, overflow_xmpp, overflow_safe_level, overflow_programs, warning_level, warning_safe_level, warning_email, warning_xmpp, warning_programs, critical_level, critical_safe_level, critical_email, critical_xmpp, critical_programs, loss_email, loss_xmpp)
        self.length = length
        self.horizontal_axis = horizontal_axis
        self.vertical_axis = vertical_axis

    def FromDict(d):
        wt = WaterTankElliptical()
        wt.InitFromDict(d)
        wt.length = None if not d["length"] else float(d["length"])
        wt.horizontal_axis = None if not d["horizontal_axis"] else float(d["horizontal_axis"])
        wt.vertical_axis = None if not d["vertical_axis"] else float(d["vertical_axis"])
        return wt

    def MeasurementIsValid(self, measurement):
        if( not super().MeasurementIsValid(measurement)):
            return False
        
        if( LengthUnit.ConvertToMeters(self.water_tank_units, self.vertical_axis) < (LengthUnit.ConvertToMeters(self.sensor_units, measurement) - LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top) ) ):
            return False
        
        return True
    
    def CalculatePercentage(self, measurement):
        if self.length is not None and self.horizontal_axis is not None and self.vertical_axis is not None and self.vertical_axis > 0:
            # from https://www.had2know.org/academics/ellipse-segment-tank-volume-calculator.html
            A = LengthUnit.ConvertToMeters(self.water_tank_units, self.vertical_axis)
            B = LengthUnit.ConvertToMeters(self.water_tank_units, self.horizontal_axis)
            H = LengthUnit.ConvertToMeters(self.water_tank_units, self.vertical_axis) - (LengthUnit.ConvertToMeters(self.sensor_units, measurement) - LengthUnit.ConvertToMeters(self.water_tank_units, self.sensor_offset_from_top) )
            L = LengthUnit.ConvertToMeters(self.water_tank_units, self.length)
            volume = B/2.0 * A/2.0 * L * pi
            try:
                liquid_volume = ((A*B*L)/4)*( acos(1.0 - 2.0*H/A) - (1.0 - 2.0*H/A)*sqrt(4*H/A - 4*(H**2)/(A**2)) )
                return round(100.0 * liquid_volume / volume)
            except:
                return None
            
        return None

    def GetHeight(self):
        return self.vertical_axis


class WaterTankFactory():
    def FromDict(d, addSettingsProperties = True):
        wt = None
        type = int(d["type"])
        if type == WaterTankType.RECTANGULAR.value:
            wt = WaterTankRectangular.FromDict(d)
        elif type == WaterTankType.CYLINDRICAL_HORIZONTAL.value:
            wt = WaterTankCylindricalHorizontal.FromDict(d)
        elif type == WaterTankType.CYLINDRICAL_VERTICAL.value:
            wt = WaterTankCylindricalVertical.FromDict(d)
        elif type == WaterTankType.ELLIPTICAL.value:
            wt = WaterTankElliptical.FromDict(d)

        return wt


class MessageSender():
    def __init__(self, mqtt_msg, water_tank):
        self.mqtt_msg = mqtt_msg
        self.water_tank = water_tank
        self.percentage_mark = None

        self.water_tank.RegisterStateChangeObserver(self)
        self.water_tank.RegisterPercentageChangeObserver(self)

    def WaterTankStateChanged(self, water_tank):
        print("WaterTankStateChanged. water_tank id:{}, state:{}".format(water_tank.id, water_tank.state.name))
        if(water_tank.id != self.water_tank.id):
            raise Exception("WaterTankStateChanged called on MessageSender initialised with water_tank id:{} but called by water_Tank id: {}".format(self.water_tank.id, water_tank.id))
        settings = get_settings()

        if( water_tank.state == WaterTankState.OVERFLOW ):
            print("Will send overflow message")
            msg = settings[XMPP_OVERFLOW_MSG].format(
                water_tank_id = water_tank.id,
                water_tank_label = water_tank.label,
                sensor_id = water_tank.sensor_id,
                percentage = water_tank.percentage,
                measurement = water_tank.sensor_measurement,
                last_updated = water_tank.last_updated,
                mqtt_topic = self.mqtt_msg.topic,
                additional_info = water_tank.AdditionalInfo4Msg()
            )
            print("Overflow email:{}, xmpp:{}".format(water_tank.overflow_email, water_tank.overflow_xmpp))
            if( water_tank.overflow_xmpp ):
                xmpp_send_msg( msg )
            if( water_tank.overflow_email ):
                email_send_msg( msg, "Overflow" )
        elif( water_tank.state == WaterTankState.CRITICAL ):
            print("Will send xmpp critical message")
            msg = settings[XMPP_CRITICAL_MSG].format(
                water_tank_id = water_tank.id,
                water_tank_label = water_tank.label,
                sensor_id = water_tank.sensor_id,
                percentage = water_tank.percentage,
                measurement = water_tank.sensor_measurement,
                last_updated = water_tank.last_updated,
                mqtt_topic = self.mqtt_msg.topic,
                additional_info = water_tank.AdditionalInfo4Msg()
            )
            print("Critical email:{}, xmpp:{}".format(water_tank.critical_email, water_tank.critical_xmpp))
            if( water_tank.critical_xmpp ):
                xmpp_send_msg( msg )
            if( water_tank.critical_email ):
                email_send_msg( msg, "Critical" )
        elif( water_tank.state == WaterTankState.WARNING ):
            print("Will send xmpp warning message")
            msg = settings[XMPP_WARNING_MSG].format(
                water_tank_id = water_tank.id,
                water_tank_label = water_tank.label,
                sensor_id = water_tank.sensor_id,
                percentage = water_tank.percentage,
                measurement = water_tank.sensor_measurement,
                last_updated = water_tank.last_updated,
                mqtt_topic = self.mqtt_msg.topic,
                additional_info = water_tank.AdditionalInfo4Msg()
            )
            print("Warning email:{}, xmpp:{}".format(water_tank.warning_email, water_tank.warning_xmpp))
            if( water_tank.warning_xmpp ):
                xmpp_send_msg( msg )
            if( water_tank.warning_email ):
                email_send_msg( msg, "Warning" )

    def MarkPercentage(self):
        self.percentage_mark = self.water_tank.percentage

    def WaterTankPercentageChanged(self, water_tank):
        print("WaterTankPercentageChanged. water_tank id:{}, state:{}".format(water_tank.id, ('None' if water_tank.state is None else water_tank.state.name)))
        if(water_tank.id != self.water_tank.id):
            raise Exception("WaterTankPercentageChanged called on MessageSender initialised with water_tank id:{} but called by water_Tank id: {}".format(self.water_tank.id, water_tank.id))
        
        settings = get_settings()

        if( self.water_tank.percentage is not None and 
        (self.percentage_mark is not None and self.percentage_mark > self.water_tank.percentage) and
        no_stations_are_on()
        ):
            print("Will send xmpp water loss message")
            msg = settings[XMPP_WATER_LOSS_MSG].format(
                water_tank_id = self.water_tank.id,
                water_tank_label = self.water_tank.label,
                sensor_id = self.water_tank.sensor_id,
                percentage = self.water_tank.percentage,
                measurement = self.water_tank.sensor_measurement,
                last_updated = self.water_tank.last_updated,
                mqtt_topic = self.mqtt_msg.topic,
                additional_info = self.water_tank.AdditionalInfo4Msg()
            )
            print("Water Loss email:{}, xmpp:{}".format(self.water_tank.loss_email, self.water_tank.loss_xmpp))
            if( self.water_tank.loss_xmpp ):
                xmpp_send_msg( msg )
            if( self.water_tank.loss_email ):
                email_send_msg( msg, "Water Loss" )

    def DeadSensorDetected(self):
        settings = get_settings()
        if( self.water_tank.sensor_id is not None 
            and self.water_tank.last_updated is not None 
            and (settings[DEAD_SENSOR_EMAIL] or settings[DEAD_SENSOR_XMPP])
        ):
            print("Will send dead-sensor message")
            msg = settings[DEAD_SENSOR_MSG].format(
                water_tank_id = self.water_tank.id,
                water_tank_label = self.water_tank.label,
                sensor_id = self.water_tank.sensor_id,
                percentage = self.water_tank.percentage,
                measurement = self.water_tank.sensor_measurement,
                last_updated = self.water_tank.last_updated,
                mqtt_topic = self.water_tank.sensor_mqtt_topic,
                additional_info = self.water_tank.AdditionalInfo4Msg()
            )
            print("Dead-sensor email:{}, xmpp:{}".format(settings[DEAD_SENSOR_EMAIL], settings[DEAD_SENSOR_XMPP]))
            if( settings[DEAD_SENSOR_XMPP] ):
                xmpp_send_msg( msg )
            if( settings[DEAD_SENSOR_EMAIL] ):
                email_send_msg( msg, "Dead Sensor" )


### Station Completed ###
def notify_zone_change(name, **kw):
    print(u"Zone change signal received")
    settings = get_settings()
    for swt_id, swt in settings["water_tanks"].items():
        wt = WaterTankFactory.FromDict(swt)
        water_tank_updated = wt.ZoneChanged()

complete = signal(u"zone_change")
complete.connect(notify_zone_change)


### program change ##
def notify_running_program_change(name, **kw):
    print("Programs changed")
    #  Programs are in gv.pd and /data/programs.json
    settings = get_settings()
    water_tank_updated = False
    for swt_id, swt in settings["water_tanks"].items():
        wt = WaterTankFactory.FromDict(swt)
        water_tank_updated = wt.RunningProgramChanged()
        if(water_tank_updated):
            settings["water_tanks"][wt.id] = wt.__dict__

    if(water_tank_updated):
        print("Programs were updated, saving settings to file")
        with open(DATA_FILE, u"w") as f:
            json.dump(settings, f, default=serialize_datetime, indent=4)  # save to file

running_program_change = signal("running_program_change")
running_program_change.connect(notify_running_program_change)


DATA_FILE = u"./data/water_tank.json"
LOG_FILE = u"./data/water_tank.sensor_log.json"
MQTT_BROKER_WS_PORT = u"mqtt_broker_ws_port"
WATER_PLUGIN_REQUEST_MQTT_TOPIC = u"request_subscribe_mqtt_topic"
WATER_PLUGIN_DATA_PUBLISH_MQTT_TOPIC = u"data_publish_mqtt_topic"
MAX_STATION_DURATION = "max_station_duration"
MAX_SENSOR_NO_SIGNAL_TIME = "max_sensor_no_signal_time"
MAX_SENSOR_LOG_RECORDS = "max_sensor_log_records"
SENSOR_LOG_ENABLED = "sensor_log_enabled"
DEAD_SENSOR_EMAIL = "dead_sensor_email"
DEAD_SENSOR_XMPP = "dead_sensor_xmpp"
DEAD_SENSOR_MSG = "dead_sensor_msg"
XMPP_USERNAME = u"xmpp_username"
XMPP_PASSWORD = u"xmpp_password"
XMPP_SERVER = u"xmpp_server"
XMPP_SUBJECT = u"xmpp_subject"
XMPP_RECIPIENTS = u"xmpp_recipients"
EMAIL_USERNAME = u"email_username"
EMAIL_PASSWORD = u"email_password"
EMAIL_SERVER = u"email_server"
EMAIL_SERVER_PORT = u"email_server_port"
EMAIL_SUBJECT = u"email_subject"
EMAIL_RECIPIENTS = u"email_recipients"
UNRECOGNISED_MSG = u"unrecognised_msg"
UNRECOGNISED_MSG_EMAIL = u"unrecognised_msg_email"
UNRECOGNISED_MSG_XMPP = u"unrecognised_msg_xmpp"
XMPP_UNASSOCIATED_SENSOR_MSG = u"xmpp_unassociated_sensor_msg"
UNASSOCIATED_SENSOR_XMPP = u"unassociated_sensor_xmpp"
UNASSOCIATED_SENSOR_EMAIL = u"unassociated_sensor_email"
XMPP_INVALID_SENSOR_MEASUREMENT_MSG = u"xmpp_invalid_sensor_measurement_msg"
INVALID_SENSOR_MEASUREMENT_XMPP = u"invalid_sensor_measurement_xmpp"
INVALID_SENSOR_MEASUREMENT_EMAIL = u"invalid_sensor_measurement_email"
XMPP_OVERFLOW_MSG = u"xmpp_overflow_msg"
XMPP_WARNING_MSG = u"xmpp_warning_msg"
XMPP_CRITICAL_MSG = u"xmpp_critical_msg"
XMPP_WATER_LOSS_MSG = u"water_loss_msg"
xmpp_msg_placeholders = ["water_tank_id", "water_tank_label", "sensor_id", "measurement", "last_updated", "mqtt_topic"]
_settings = {
    MQTT_BROKER_WS_PORT: 8080,
    WATER_PLUGIN_REQUEST_MQTT_TOPIC: "WaterTankDataRequest",
    WATER_PLUGIN_DATA_PUBLISH_MQTT_TOPIC: "WaterTankData",
    MAX_STATION_DURATION: 60,
    MAX_SENSOR_NO_SIGNAL_TIME: 10,
    MAX_SENSOR_LOG_RECORDS: 1000,
    SENSOR_LOG_ENABLED: True,
    DEAD_SENSOR_EMAIL: True,
    DEAD_SENSOR_XMPP: True,
    DEAD_SENSOR_MSG: u"Sensor '{sensor_id}' of water tank '{water_tank_label}' ('water_tank_id: {water_tank_id}') may be dead. Last update was on '{last_updated}'. Listening for sensor messages on MQTT topic:'{mqtt_topic}'.",
    XMPP_USERNAME: "ahat_sip@ahat1.duckdns.org",
    XMPP_PASSWORD: u"312ggp12",
    XMPP_SERVER: u"ahat1.duckdns.org",
    XMPP_SUBJECT: u"SIP",
    XMPP_RECIPIENTS: u"ahat@ahat1.duckdns.org",
    EMAIL_USERNAME: "ahatzikonstantinou.SIP@gmail.com",
    EMAIL_PASSWORD: u"pbem zcnq noiq zygz",
    EMAIL_SERVER: u"smtp.gmail.com",
    EMAIL_SERVER_PORT: 465,
    EMAIL_SUBJECT: u"SIP",
    EMAIL_RECIPIENTS: u"ahatzikonstantinou@gmail.com,ahatzikonstantinou@protonmail.com",
    UNRECOGNISED_MSG: u"Unrecognised mqtt msg! MQTT topic:'{mqtt_topic}', date:'{date}', msg:[{message}]",
    UNRECOGNISED_MSG_EMAIL: True,
    UNRECOGNISED_MSG_XMPP: True,
    XMPP_UNASSOCIATED_SENSOR_MSG: u"Unassociated sensor measurement msg! sensor_id:'{sensor_id}', measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'",
    UNASSOCIATED_SENSOR_XMPP: True,
    UNASSOCIATED_SENSOR_EMAIL: True,
    XMPP_INVALID_SENSOR_MEASUREMENT_MSG: u"Invalid sensor measurement! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    XMPP_OVERFLOW_MSG: u"Overflow! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    XMPP_WARNING_MSG: u"Warning! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    XMPP_CRITICAL_MSG: u"Critical! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    XMPP_WATER_LOSS_MSG: u"Water loss! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    
    u"water_tanks": {}
        # {
        # "water_tank_1": {
        #     "id": "water_tank_1",
        #     "label": "\u03a4\u03c3\u03b9\u03bc\u03b5\u03bd\u03c4\u03ad\u03bd\u03b9\u03b1",
        #     "type": 1,
        #     "sensor_mqtt_topic": "WATER_TANK_MEASUREMENT",
        #     INVALID_SENSOR_MEASUREMENT_XMPP: True,
        #     INVALID_SENSOR_MEASUREMENT_EMAIL: True,
        #     "sensor_offset_from_top": 0.0,
        #     "enabled": True,
        #     "overflow_level": 80.0,
        #     "overflow_email": True,
        #     "overflow_xmpp": True,
        #     "overflow_safe_level": None,
        #     "overflow_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "warning_level": 25.0,
        #     "warning_email": True,
        #     "warning_xmpp": True,
        #     "warning_suspend_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "warning_activate_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "critical_level": 8.0,
        #     "critical_email": True,
        #     "critical_xmpp": True,
        #     "critical_suspend_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "critical_activate_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "loss_email": True,
        #     "loss_xmpp": True,
        #     "last_updated": None,
        #     "sensor_id": None, 
        #     "sensor_measurement": None,
        #     "invalid_sensor_measurement": False,
        #     "percentage": None,
        #     "width": 2.0,
        #     "length": 5.0,
        #     "height": 2.0,
        #     "order": 0
        # },
        # "water_tank_2": {
        #     "id": "water_tank_2",
        #     "label": "\u03a3\u03b9\u03b4\u03b5\u03c1\u03ad\u03bd\u03b9\u03b1",
        #     "type": 1,
        #     "sensor_mqtt_topic": "WATER_TANK_MEASUREMENT",
        #     INVALID_SENSOR_MEASUREMENT_XMPP: True,
        #     INVALID_SENSOR_MEASUREMENT_EMAIL: True,
        #     "sensor_offset_from_top": 0.0,
        #     "enabled": True,
        #     "overflow_level": 85.0,
        #     "overflow_email": True,
        #     "overflow_xmpp": True,
        #     "overflow_safe_level": None,
        #     "overflow_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "warning_level": 30.0,
        #     "warning_email": True,
        #     "warning_xmpp": True,
        #     "warning_suspend_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "warning_activate_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "critical_level": 5.0,
        #     "critical_email": False,
        #     "critical_xmpp": False,
        #     "critical_suspend_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "critical_activate_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "loss_email": True,
        #     "loss_xmpp": True,
        #     "last_updated": "2023-11-12 13:47",
        #     "sensor_id": "Sensor_2", 
        #     "sensor_measurement": 0.9,
        #     "invalid_sensor_measurement": True,
        #     "percentage": 40.0,
        #     "width": 2.0,
        #     "length": 3.0,
        #     "height": 1.5,
        #     "order": 1
        # },
        # "water_tank_3": {
        #     "id": "water_tank_3",
        #     "label": "\u039c\u03b1\u03cd\u03c1\u03b7",
        #     "type": 3,
        #     "sensor_mqtt_topic": "WATER_TANK_MEASUREMENT",
        #     INVALID_SENSOR_MEASUREMENT_XMPP: True,
        #     INVALID_SENSOR_MEASUREMENT_EMAIL: True,
        #     "sensor_offset_from_top": 0.0,
        #     "enabled": True,
        #     "overflow_level": 85.0,
        #     "overflow_email": True,
        #     "overflow_xmpp": False,
        #     "overflow_safe_level": None,
        #     "overflow_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "warning_level": 30.0,
        #     "warning_email": False,
        #     "warning_xmpp": True,
        #     "warning_suspend_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "warning_activate_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "critical_level": 5.0,
        #     "critical_email": True,
        #     "critical_xmpp": True,
        #     "critical_suspend_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "critical_activate_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "loss_email": False,
        #     "loss_xmpp": False,
        #     "last_updated": "2023-11-12 13:47",
        #     "sensor_id": "Sensor_3", 
        #     "sensor_measurement": 1.5,
        #     "invalid_sensor_measurement": False,
        #     "percentage": 25.0,
        #     "height": 2.0,
        #     "diameter": 2.0,
        #     "order": 2
        # },
        # "water_tank_4": {
        #     "id": "water_tank_4",
        #     "label": "\u039d\u03b5\u03c1\u03cc \u03b4\u03b9\u03ba\u03c4\u03cd\u03bf\u03c5",
        #     "type": 4,
        #     "sensor_mqtt_topic": "WATER_TANK_MEASUREMENT",
        #     INVALID_SENSOR_MEASUREMENT_XMPP: True,
        #     INVALID_SENSOR_MEASUREMENT_EMAIL: True,
        #     "sensor_offset_from_top": 0.0,
        #     "enabled": True,
        #     "overflow_level": 85.0,
        #     "overflow_email": False,
        #     "overflow_xmpp": True,
        #     "overflow_safe_level": None,
        #     "overflow_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "warning_level": 40.0,
        #     "warning_email": True,
        #     "warning_xmpp": True,
        #     "warning_suspend_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "warning_activate_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "critical_level": 5.0,
        #     "critical_email": True,
        #     "critical_xmpp": True,
        #     "critical_suspend_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "critical_activate_programs": {
        #         "1": False,
        #         "2": False,
        #         "3": False,
        #         "4": False
        #     },
        #     "loss_email": True,
        #     "loss_xmpp": True,
        #     "last_updated": "2023-11-12 13:47",
        #     "sensor_id": "Sensor_4", 
        #     "sensor_measurement": 0.6,
        #     "invalid_sensor_measurement": False,
        #     "percentage": 61.41848493043786,
        #     "length": 2.0,
        #     "horizontal_axis": 1.0,
        #     "vertical_axis": 0.8,
        #     "order": 4
        # }
    # }
}


defaults = {
    DEAD_SENSOR_MSG: u"Sensor '{sensor_id}' of water tank '{water_tank_label}' ('water_tank_id: {water_tank_id}') may be dead. Last update was on '{last_updated}'. Listening for sensor messages on MQTT topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    UNRECOGNISED_MSG: u"Unrecognised mqtt msg! MQTT topic:'{mqtt_topic}', date:'{date}', msg:[{message}]",
    UNRECOGNISED_MSG_EMAIL: True,
    UNRECOGNISED_MSG_XMPP: True,
    XMPP_UNASSOCIATED_SENSOR_MSG: u"Unassociated sensor measurement msg! sensor_id:'{sensor_id}', measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'",
    UNASSOCIATED_SENSOR_XMPP: True,
    UNASSOCIATED_SENSOR_EMAIL: True,
    XMPP_INVALID_SENSOR_MEASUREMENT_MSG: u"Invalid sensor measurement! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    XMPP_OVERFLOW_MSG: u"Overflow! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    XMPP_WARNING_MSG: u"Warning! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    XMPP_CRITICAL_MSG: u"Critical! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]",
    XMPP_WATER_LOSS_MSG: u"Water loss! water tank:'{water_tank_id}'/'{water_tank_label}', sensor_id:'{sensor_id}', percentage: {percentage}%, measurement:'{measurement}', date:'{last_updated}', mqtt topic:'{mqtt_topic}'. Additional info:[{additional_info}]"
}


# Add new URLs to access classes in this plugin.
# fmt: off
urls.extend([
    u"/water-tank-sp", u"plugins.water_tank.settings",
    u"/water-tank-save-settings", u"plugins.water_tank.save_settings",
    u"/water-tank-save-water-tanks", u"plugins.water_tank.save_water_tanks",
    u"/water-tank-get-all", u"plugins.water_tank.get_all",
    u"/water-tank-get_mqtt_settings", u"plugins.water_tank.get_mqtt_settings",
    u"/water_tank_get_settings_json", u"plugins.water_tank.get_settings_json",
    u"/water-tank-delete", u"plugins.water_tank.delete",
    u"/water-tank-save-order", u"plugins.water_tank.save_order",
    u"/water-tank-revert-programs", u"plugins.water_tank.revert_programs",
    u"/water_plugin_sensor_log", u"plugins.water_tank.sensor_log",
    u"/water_plugin_clear_sensor_log", u"plugins.water_tank.clear_sensor_log",
    u"/water_plugin_download_sensor_log", u"plugins.water_tank.csv_sensor_log"
    ])
# fmt: on

# Add this plugin to the PLUGINS menu ["Menu Name", "URL"], (Optional)
gv.plugin_menu.append([_(u"Water Tank Plugin"), u"/water-tank-sp"])


# Define a custom function to serialize datetime objects 
def serialize_datetime(obj): 
    # print('Serializing: {}'.format(obj))
    if isinstance(obj, datetime): 
        return obj.isoformat(sep=' ', timespec='seconds')
    elif isinstance(obj, WaterTankType):
        return obj.value
    elif isinstance(obj, WaterTankState):
        return obj.value
    elif  isinstance(obj, WaterTankProgram):
        return obj.__dict__
    elif  isinstance(obj, WaterTankStation):
        return obj.__dict__
    elif  isinstance(obj, WaterTank):
        val = obj.__dict__.copy()
        val.pop("state_change_observers")  # do not serialze observer objects
        return val
    elif isinstance(obj, MessageSender):
        return
    raise TypeError("Type {} not serializable".format(type(obj))) 


def get_settings():
    global _settings
    try:
        fh = open(DATA_FILE, "r")
        try:
            settings = json.load(fh)
            _settings = settings
        except ValueError as e:
            print(u"Water Tank pluging couldn't parse data file:", e)
        finally:
            fh.close()
    except IOError as e:
        print(u"Water-Tank Plugin couldn't open data file:", e)
    # print( 'get_settings() returns : {}'.format(json.dumps(_settings, default=serialize_datetime, indent=4)))
    return _settings


def detect_water_tank_js():
    """
    Search base.html for the line that includes the water_tank.js script
    """
    path = os.getcwd()
    print('Current dir is {}'.format(path))
    file_path = path + '/templates/base.html'
    mqtt_line = '\t<script src="static/scripts/mqttws31.js"></script>\n'
    validation_line = '\t<script src="static/scripts/jquery.validate.min.js"></script>\n'
    additional_validation_line = '\t<script src="static/scripts/additional-methods.min.js"></script>\n'
    script_line = '\t<script src="static/scripts/water_tank.js"></script>\n'
    css_line = '\t<link href="static/css/water_tank.css" rel="stylesheet" type="text/css"/>\n'
    header_end_word = '</head>'
    header_end_word_index = 0
    found = False
    contents = []
    with open(file_path, 'r') as file:
        for(i, line) in enumerate(file):
            contents.append(line)
            if script_line in line:
                found = True
                print('{} found in {}:{}'.format(script_line, file_path, i))
                break
            if header_end_word in line:
                print('{} found in {}:{}'.format(header_end_word, file_path, header_end_word_index))
                header_end_word_index = i

    if not found:
        if header_end_word_index == 0:
            print('{} was not found in {}. Water Tank plugin cannot work.')
        else:
            print('{} not found in {}, will add it above {} to line {}'.format(script_line, file_path, header_end_word, header_end_word_index-1))
            contents.insert(header_end_word_index, script_line)
            contents.insert(header_end_word_index, additional_validation_line)
            contents.insert(header_end_word_index, validation_line)
            contents.insert(header_end_word_index, mqtt_line)
            contents.insert(header_end_word_index, css_line)
            with open(file_path, 'w') as file:
                contents = "".join(contents)
                file.write(contents)
            print('{} and {} were added to line {}. Please refresh the page in you browser.'.format(script_line, mqtt_line, header_end_word_index-1))
        return


def readWaterTankData():
    water_tank_data = {}
    try:
        settings = get_settings()
        water_tank_data = []
        if( len(settings[u"water_tanks"]) > 0):
            water_tank_data = sorted(list(settings[u"water_tanks"].values()), key= lambda wt : wt["order"])
            # print("readWaterTankData returns sorted list: {}".format(json.dumps(water_tank_data, default=serialize_datetime, indent=4 )))
    except IOError:  # If file does not exist return empty value
        water_tank_data = []
        
    return water_tank_data


def no_stations_are_on():
    print("gv.srvals: {}, open valve exists: {}".format(''.join(str(gv.srvals)), (1 in gv.srvals)))
    return 1 not in gv.srvals


def email_send_msg(text, tank_event):
    """Send email"""
    settings = get_settings()
    print("Sending email [{}] for tank event: {}, with subject: '{}'".format(text, tank_event,settings[EMAIL_SUBJECT]))
    
    if settings[EMAIL_USERNAME] != "" and settings[EMAIL_PASSWORD] != "" and settings[EMAIL_SERVER] != "" and settings[EMAIL_SERVER_PORT] != "" and settings[EMAIL_RECIPIENTS] != "":
        mail_user = settings[EMAIL_USERNAME]  # SMTP username
        mail_from = mail_user
        mail_pwd = settings[EMAIL_PASSWORD]  # SMTP password
        mail_server = settings[EMAIL_SERVER]  # SMTP server address
        mail_port = settings[EMAIL_SERVER_PORT]  # SMTP port
        # --------------
        msg = MIMEText(text)
        msg[u"From"] = mail_from
        msg[u"To"] = settings[EMAIL_RECIPIENTS]
        # print("Sending email to: {}".format(msg[u"To"]))
        msg[u"Subject"] = settings[EMAIL_SUBJECT] + " " + tank_event
        
        with smtplib.SMTP_SSL(mail_server, mail_port) as smtp_server:
            smtp_server.login(mail_user, mail_pwd)
            smtp_server.sendmail(mail_user, [x.strip() for x in settings[EMAIL_RECIPIENTS].split(',')], msg.as_string())
        print("Message sent!")

    else:
        raise Exception(u"E-mail plug-in is not properly configured!")


def get_xmpp_receipients():
    """
    Returns a list of recipients for xmpp messages
    """
    settings = get_settings()
    if "," not in settings[XMPP_RECIPIENTS]:
        return [settings[XMPP_RECIPIENTS]]

    return [s.strip() for s in settings[XMPP_RECIPIENTS].split(", ")]


def xmpp_send_msg(message):
    # print("Will try to send message '{}'".format(message))
    settings = get_settings()

    if( (not(settings[XMPP_USERNAME] and not settings[XMPP_USERNAME].isspace())) or
       (not(settings[XMPP_PASSWORD] and not settings[XMPP_PASSWORD].isspace())) or
       (not(settings[XMPP_SERVER] and not settings[XMPP_SERVER].isspace()))
       ):
       print("XMPP_USERNAME:'{}', or XMPP_PASSWORD:'{}', or XMPP_SERVER:'{}' are empty, cannot send xmpp message."
             .format(settings[XMPP_USERNAME], settings[XMPP_PASSWORD], settings[XMPP_SERVER]))
       return

    jid = xmpp.protocol.JID( settings[XMPP_USERNAME] )
    cl = xmpp.Client( settings[XMPP_SERVER], debug=[] )
    con = cl.connect()
    if not con:
        print('could not connect!')
        return False
    # print('connected with {} to {} with user {}'.format(con, settings[XMPP_SERVER], settings[XMPP_USERNAME]))
    auth = cl.auth( jid.getNode(), settings[XMPP_PASSWORD], resource = jid.getResource() )
    if not auth:
        print('could not authenticate!')
        return False
    # print('authenticated using {}'.format(auth) )

    #cl.SendInitPresence(requestRoster=0)   # you may need to uncomment this for old server
    for r in get_xmpp_receipients():
        id = cl.send(xmpp.protocol.Message( r, message ) )
        # print('sent message with id {} to {}'.format(id, r) )


def send_unrecognised_msg(mqtt_topic, date, message):
    settings = get_settings()
    msg = settings[UNRECOGNISED_MSG].format(
        mqtt_topic = mqtt_topic,
        date = date,
        message = message
    )
    if( settings[UNRECOGNISED_MSG_EMAIL] ):
        email_send_msg( msg, "Unrecognised MQTT message!" )
    if( settings[UNRECOGNISED_MSG_XMPP] ):
        xmpp_send_msg( msg )


def send_unassociated_sensor_msg(sensor_id, measurement, last_updated, mqtt_topic):
    settings = get_settings()
    msg = settings[XMPP_UNASSOCIATED_SENSOR_MSG].format(
        sensor_id = sensor_id,
        measurement = measurement,
        last_updated = last_updated,
        mqtt_topic = mqtt_topic
    )
    if( settings[UNASSOCIATED_SENSOR_XMPP] ):
        xmpp_send_msg( msg )
    if( settings[UNASSOCIATED_SENSOR_EMAIL] ):
        email_send_msg( msg, "Unassociated sensor" )


def send_invalid_measurement_msg(water_tank, additional_info):
    settings = get_settings()
    msg = settings[XMPP_INVALID_SENSOR_MEASUREMENT_MSG].format(
        water_tank_id = water_tank.id,
        water_tank_label = water_tank.label,
        sensor_id = water_tank.sensor_id,
        percentage = water_tank.percentage,
        measurement = water_tank.sensor_measurement,
        last_updated = water_tank.last_updated,
        mqtt_topic = water_tank.sensor_mqtt_topic,
        additional_info = additional_info
    )
    print("Invalid measurement email:{}, xmpp:{}".format(water_tank.invalid_sensor_measurement_email, water_tank.invalid_sensor_measurement_xmpp))
    if( water_tank.invalid_sensor_measurement_xmpp ):
        xmpp_send_msg( msg )
    if( water_tank.invalid_sensor_measurement_email ):
        email_send_msg( msg, "Invalid measurement" )


def updateSensorMeasurementFromCmd(cmd, water_tanks, msg):
    associated_wts = [ wt for wt in list(water_tanks.values()) if wt["sensor_id"] == cmd["sensor_id"]]
    if len(associated_wts) == 0:
        send_unassociated_sensor_msg(
            cmd[u"sensor_id"],
            cmd[u"measurement"],
            datetime.now().replace(microsecond=0),
            msg.topic
        )
        return
    
    water_tank_updated = False
    for awt in associated_wts:
        # print("Doing {}".format(awt["id"]))
        wt = WaterTankFactory.FromDict(awt)
        # print("Wt from {}".format(json.dumps(wt, default=serialize_datetime, indent=4)))
        # print("Before UpdateSensorMeasurement. awt['enabled']:{}, wt.enabled:{}".format(awt['enabled'], wt.enabled))
        msgSender = MessageSender(msg, wt)
        msgSender.MarkPercentage()
        if wt.UpdateSensorMeasurement(cmd[u"sensor_id"], cmd[u"measurement"]):
            print("updateSensorMeasurementFromCmd. A water tank was updated")
            water_tanks[wt.id] = wt.__dict__
            # print("After UpdateSensorMeasurement. water_tanks[wt.id]['enabled']:{}, wt.enabled:{}".format(water_tanks[wt.id]['enabled'], wt.enabled))        
            # print("After wt.UpdateSensorMeasurement {}".format(json.dumps(wt, default=serialize_datetime, indent=4)))
            # check_events_and_send_msg(cmd, percentageBefore, wt, msg)
            water_tank_updated = True
            # print("Update water tank '{}' with measurment: {}".format(wt.id, wt.sensor_measurement))

    return water_tank_updated


def read_sensor_log():
    """
    Read data from sensor log file.
    """
    result = []
    try:
        with io.open(LOG_FILE) as logf:
            records = logf.readlines()
            for i in records:
                try:
                    rec = ast.literal_eval(json.loads(i))
                except ValueError:
                    rec = json.loads(i)
                result.append(rec)
        return result
    except IOError:
        return result


def log_sensor_msg(msg):
    settings = get_settings()

    logline = (
        '{' +
        '"date":"' + datetime.now().isoformat(sep=' ', timespec='seconds') + '",' +
        '"mqtt_topic":"' + str(msg.topic) + '",' +
        '"mqtt_payload":' + json.dumps(str(msg.payload)) +
        '}'
    )
    lines = []
    lines.append(logline + "\n")
    log = read_sensor_log()
    for r in log:
        lines.append(json.dumps(r) + "\n")
    with codecs.open(LOG_FILE, "w", encoding="utf-8") as f:
        if settings[MAX_SENSOR_LOG_RECORDS]:
            f.writelines(lines[: settings[MAX_SENSOR_LOG_RECORDS]])
        else:
            f.writelines(lines) 


def on_sensor_mqtt_message(client, msg):
    """
    Callback when MQTT message is received from sensor
    """
    print('Received MQTT message: {}'.format(msg.payload))
    settings = get_settings()
    if settings[SENSOR_LOG_ENABLED]:
        log_sensor_msg(msg)
    try:
        cmd = json.loads(msg.payload)
        print('MQTT cmd: {}'.format(cmd))
    except ValueError as e:
        print(u"Water Tank plugin could not decode command: ", msg.payload, e)
        send_unrecognised_msg(msg.topic, datetime.now().replace(microsecond=0), msg.payload)
        return

    try:
        water_tanks = settings[u"water_tanks"]
        water_tank_updated = False
        # print("Before updateSensorMeasurementFromCmd water_tanks: {}".format(json.dumps(settings[u"water_tanks"], default=serialize_datetime, indent=4)))
        if isinstance(cmd, dict) and 'sensor_id' in cmd:
            water_tank_updated = updateSensorMeasurementFromCmd(cmd, water_tanks, msg)
        elif isinstance(cmd, list):
            print('Cmd is a list')
            for singleTankCmd in cmd:
                print('Cmd item:{}'.format(json.dumps(singleTankCmd, default=serialize_datetime,indent=4)))
                if isinstance(singleTankCmd, dict) and 'sensor_id' in singleTankCmd:
                    print("Will call updateSensorMeasurementFromCmd for sensor '{}'".format(singleTankCmd["sensor_id"]))
                    water_tank_updated = updateSensorMeasurementFromCmd(singleTankCmd, water_tanks, msg) or water_tank_updated
                else:
                    print("Skipping sensor: {}".format(singleTankCmd["sensor_id"]))
        else:
            print("Unknown mqtt command {}".format(repr(cmd)))
            send_unrecognised_msg(msg.topic, datetime.now().replace(microsecond=0), msg.payload)
            return

        if not water_tank_updated:
            print("No water tank with cmd '{}' was updated.".format(cmd))
            return
        
        settings[u"water_tanks"] = water_tanks
        print("on_sensor_mqtt_message. Water tank update, saving settings to file")
        # print("Saving water_tanks: {}".format(json.dumps(settings[u"water_tanks"], default=serialize_datetime, indent=4)))
        with open(DATA_FILE, u"w") as f:
                json.dump(settings, f, default=serialize_datetime, indent=4)  # save to file                

        publish_water_tanks_mqtt()
    except Exception as e:
        print("Exception in on_sensor_mqtt_message. ", e)
        traceback.print_exc()


def on_data_request_mqtt_message(client, msg):
    """
    Callback when MQTT message is received requesting water tank data
    """
    publish_water_tanks_mqtt()


def subscribe_mqtt():
    """
    Start listening for mqtt messages
    """
    settings = get_settings()

    #subscribe to data-request topic
    topic = settings[WATER_PLUGIN_REQUEST_MQTT_TOPIC]
    if topic:
        print("Subscribing to topic '{}'".format(topic))
        mqtt.subscribe(topic, on_data_request_mqtt_message, 2)

    #subscribe to sensor topics
    for wt in list( settings[u"water_tanks"].values() ):
        topic = wt[u"sensor_mqtt_topic"]
        if topic and topic not in mqtt._subscriptions:
            print("Subscribing to topic '{}'".format(topic))
            mqtt.subscribe(topic, on_sensor_mqtt_message, 2)


def unsubscribe_mqtt():
    settings = get_settings()
    topic = settings[WATER_PLUGIN_REQUEST_MQTT_TOPIC]
    if topic:
        mqtt.unsubscribe(topic)

    for wt in list( settings[u"water_tanks"].values() ):
        topic = wt[u"sensor_mqtt_topic"]
        if topic:
            mqtt.unsubscribe(topic)


def refresh_mqtt_subscriptions():
    unsubscribe_mqtt()
    subscribe_mqtt()    


def publish_water_tanks_mqtt():
    settings = get_settings()
    client = mqtt.get_client()
    if client:
        # print("Publishing: {}".format(json.dumps(settings['water_tanks'], default=serialize_datetime, indent=4)))
        client.publish(
            settings[WATER_PLUGIN_DATA_PUBLISH_MQTT_TOPIC], 
            json.dumps(readWaterTankData(), default=serialize_datetime, indent=4), 
            qos=1, 
            retain=True
        )


class settings(ProtectedPage):
    """
    Load an html page for entering plugin settings.
    """

    def GET(self):
        try:
            with open(DATA_FILE, u"r") as f:  # Read settings from json file if it exists
                settings = json.load(f)
        except IOError:  # If file does not exist return empty value
            settings = _settings

        show_settings = 'showSettings' in web.input()
        water_tank_id = None
        if 'water_tank_id' in web.input():
            water_tank_id = web.input()["water_tank_id"]

        if( len(settings[u"water_tanks"]) > 0 ):
            settings[u"water_tanks"] = sorted(list(settings[u"water_tanks"].values()), key= lambda wt : wt["order"])
        # print("Sending settings: {}".format(json.dumps(settings, default=serialize_datetime, indent=4)))
        return template_render.water_tank(settings, json.dumps(defaults, ensure_ascii=False), gv.pnames, gv.snames, water_tank_id, show_settings)  # open settings page


class save_settings(ProtectedPage):
    """
    Save user input to json file.
    Will create or update file when SUBMIT button is clicked
    CheckBoxes only appear in qdict if they are checked.
    """

    def POST(self):
        d = (
            web.input()
        )  # Dictionary of values returned as query string from settings page.
        print('Received: {}'.format(json.dumps(d, default=serialize_datetime, indent=4, sort_keys=True))) # for testing
        settings = get_settings()

        previous_MAX_SENSOR_NO_SIGNAL_TIME = settings[MAX_SENSOR_NO_SIGNAL_TIME]

        settings[MQTT_BROKER_WS_PORT] = d[MQTT_BROKER_WS_PORT]
        settings[WATER_PLUGIN_REQUEST_MQTT_TOPIC] = d[WATER_PLUGIN_REQUEST_MQTT_TOPIC]
        settings[WATER_PLUGIN_REQUEST_MQTT_TOPIC] = d[WATER_PLUGIN_REQUEST_MQTT_TOPIC]
        settings[MAX_SENSOR_NO_SIGNAL_TIME] = int(d[MAX_SENSOR_NO_SIGNAL_TIME])
        settings[MAX_SENSOR_LOG_RECORDS] = int(d[MAX_SENSOR_LOG_RECORDS])
        settings[SENSOR_LOG_ENABLED] = (SENSOR_LOG_ENABLED in d)
        settings[DEAD_SENSOR_EMAIL] = (DEAD_SENSOR_EMAIL in d)
        settings[DEAD_SENSOR_XMPP] = (DEAD_SENSOR_XMPP in d)
        settings[DEAD_SENSOR_MSG] = d[DEAD_SENSOR_MSG]
        settings[MAX_STATION_DURATION] = int(d[MAX_STATION_DURATION])
        settings[XMPP_USERNAME] = d[XMPP_USERNAME]
        settings[XMPP_PASSWORD] = d[XMPP_PASSWORD]
        settings[XMPP_SERVER] = d[XMPP_SERVER]
        settings[XMPP_SUBJECT] = d[XMPP_SUBJECT]
        settings[XMPP_RECIPIENTS] = d[XMPP_RECIPIENTS]
        settings[UNRECOGNISED_MSG] = d[UNRECOGNISED_MSG]
        settings[UNRECOGNISED_MSG_EMAIL] = (UNRECOGNISED_MSG_EMAIL in d)
        settings[UNRECOGNISED_MSG_XMPP] = (UNRECOGNISED_MSG_XMPP in d)
        settings[XMPP_UNASSOCIATED_SENSOR_MSG] = d[XMPP_UNASSOCIATED_SENSOR_MSG]
        settings[UNASSOCIATED_SENSOR_EMAIL] = (UNASSOCIATED_SENSOR_EMAIL in d)
        settings[UNASSOCIATED_SENSOR_XMPP] = (UNASSOCIATED_SENSOR_XMPP in d)
        settings[XMPP_INVALID_SENSOR_MEASUREMENT_MSG] = d[XMPP_INVALID_SENSOR_MEASUREMENT_MSG]
        settings[XMPP_OVERFLOW_MSG] = d[XMPP_OVERFLOW_MSG]
        settings[XMPP_WARNING_MSG] = d[XMPP_WARNING_MSG]
        settings[XMPP_CRITICAL_MSG] = d[XMPP_CRITICAL_MSG]
        settings[XMPP_WATER_LOSS_MSG] = d[XMPP_WATER_LOSS_MSG]
        settings[EMAIL_USERNAME] = d[EMAIL_USERNAME]
        settings[EMAIL_PASSWORD] = d[EMAIL_PASSWORD]
        settings[EMAIL_SERVER] = d[EMAIL_SERVER]
        settings[EMAIL_SERVER_PORT] = d[EMAIL_SERVER_PORT]
        settings[EMAIL_SUBJECT] = d[EMAIL_SUBJECT]
        settings[EMAIL_RECIPIENTS] = d[EMAIL_RECIPIENTS]

        with open(DATA_FILE, u"w") as f:
            json.dump(settings, f, default=serialize_datetime, indent=4)  # save to file
        # print('Saved settings: {}'.format(json.dumps(settings, default=serialize_datetime, indent=4)))

        # if the max-no-signal time has changed restart the dead-sensor monitor
        if( previous_MAX_SENSOR_NO_SIGNAL_TIME != settings[MAX_SENSOR_NO_SIGNAL_TIME] ):
            dead_sensor_monitor.reset(settings[MAX_SENSOR_NO_SIGNAL_TIME])

        raise web.seeother(u"/water-tank-sp?showSettings") 


class save_water_tanks(ProtectedPage):
    """
    Save user input to json file.
    Will create or update file when SUBMIT button is clicked
    CheckBoxes only appear in qdict if they are checked.
    """

    def POST(self):
        d = (
            web.input()
        )  # Dictionary of values returned as query string from settings page.
        print('Received: {}'.format(json.dumps(d, default=serialize_datetime, indent=4, sort_keys=True))) # for testing
        settings = get_settings()
        
        water_tank = WaterTankFactory.FromDict(d)
        original_water_tank_id = d[u"original_water_tank_id"]
        
        if d[u"id"]:
            if d[u"action"] == "add":
                #add new water_Tank
                # print('Adding new water tank: {}'.format(json.dumps(water_tank, default=serialize_datetime, indent=4)))
                water_tank.order = len(settings['water_tanks'])
                settings['water_tanks'][water_tank.id] = water_tank
            elif d[u"action"] == "update" and original_water_tank_id:
                # print('Updating water tank with id: "{}". New values: {}'.format(original_water_tank_id, json.dumps(water_tank, default=serialize_datetime, indent=4)))
                wt = settings['water_tanks'][original_water_tank_id]
                # print('Old values: {}'.format(json.dumps(wt, default=serialize_datetime, indent=4)))
                water_tank.last_updated = wt["last_updated"]
                water_tank.order = wt["order"]
                water_tank.state = wt["state"]
                # if wt["sensor_measurement"]:
                #     water_tank.UpdateSensorMeasurement(wt["sensor_measurement"])
                if water_tank.id == original_water_tank_id:
                    settings['water_tanks'][original_water_tank_id] = water_tank
                else:
                    del settings['water_tanks'][original_water_tank_id]
                    settings['water_tanks'][water_tank.id] = water_tank
                
        with open(DATA_FILE, u"w") as f:
            json.dump(settings, f, default=serialize_datetime, indent=4)  # save to file
        # print('Saved water tanks: {}'.format(json.dumps(settings, default=serialize_datetime, indent=4)))

        if d[u"id"] and (d[u"action"] == "add" or (d[u"action"] == "update" and original_water_tank_id)):
            refresh_mqtt_subscriptions()
            publish_water_tanks_mqtt()
            raise web.seeother(u"/water-tank-sp?water_tank_id=" + d[u"id"])
        else:
            raise web.seeother(u"/water-tank-sp")


class get_all(ProtectedPage):
    """
    Read last saved water-tank data and return it as json
    """
    def GET(self):
        print(u"Reading water tank data")
        data = readWaterTankData()
        web.header('Content-Type', 'application/json')
        return json.dumps(data, default=serialize_datetime, indent=4)
    

class get_mqtt_settings(ProtectedPage):
    """
    Return the mqtt settings. Js/Paho will use them to
    subscibe to water tank topics and update the relevant
    widgets
    """
    def GET(self):
        water_tank_settings = get_settings()
        settings = mqtt.get_settings()
        settings[MQTT_BROKER_WS_PORT] = int(water_tank_settings[MQTT_BROKER_WS_PORT])
        settings[WATER_PLUGIN_REQUEST_MQTT_TOPIC] = water_tank_settings[WATER_PLUGIN_REQUEST_MQTT_TOPIC]
        settings[WATER_PLUGIN_DATA_PUBLISH_MQTT_TOPIC] = water_tank_settings[WATER_PLUGIN_DATA_PUBLISH_MQTT_TOPIC]
        # Get the ip in case of localhost or 127.0.0.1
        # from https://stackoverflow.com/a/28950776
        if settings['broker_host'].lower() in ['localhost', '127.0.0.1']:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            try:
                # doesn't even have to be reachable
                s.connect(('10.254.254.254', 1))
                IP = s.getsockname()[0]
            except Exception:
                IP = '127.0.0.1'
            finally:
                s.close()
            settings['broker_host'] = IP
    
        return json.dumps(settings, default=serialize_datetime, indent=4)


class get_settings_json(ProtectedPage):
    """
    Return the water_tank settings.
    """
    def GET(self):
        return json.dumps(get_settings(), default=serialize_datetime, indent=4)


class delete(ProtectedPage)    :
    """
    Deletes a water tank record from settings based on water tank id
    """
    def POST(self):
        data = web.input()
        # print(repr(data))
        id = data[u"original_water_tank_id"]
        # print('id: {}\n'.format(id))
        settings = get_settings()
        if id in settings[u"water_tanks"]:
            del settings[u"water_tanks"][id]
            # print('Settings after delete:{}'.format(repr(settings)))            
            with open(DATA_FILE, u"w") as f:
                json.dump(settings, f, default=serialize_datetime, indent=4)  # save to file
            refresh_mqtt_subscriptions()
        raise web.seeother(u"/water-tank-sp")  # open settings page        


class save_order(ProtectedPage):
    """
    Saves the order of a water tank
    """
    def POST(self):
        data = web.input()
        try:
            print(repr(data))
            id = data["water_tank_id"]
            order = int(data["order"])
            move = data["move"]
            print('id: {}, move: {}, order: {}'.format(id, move, order))
            settings = get_settings()
            if id in settings[u"water_tanks"]:
                previous_order = settings[u"water_tanks"][id]["order"]
                for x in settings[u"water_tanks"]:
                    if( x == id ):
                        settings[u"water_tanks"][id]["order"] = order
                    elif( move == "down" and settings[u"water_tanks"][x]["order"] >= order and settings[u"water_tanks"][x]["order"] < previous_order):
                        settings[u"water_tanks"][x]["order"] += 1 
                    elif( move == "up" and settings[u"water_tanks"][x]["order"] <= order and settings[u"water_tanks"][x]["order"] > previous_order):
                        settings[u"water_tanks"][x]["order"] -= 1 
                with open(DATA_FILE, u"w") as f:
                    json.dump(settings, f, default=serialize_datetime, indent=4)  # save to file

                # publish all water-tank data for new order
                publish_water_tanks_mqtt()
                return json.dumps('{"success": true, "reason": ""}')
            return json.dumps('{"success": false, "reason": "water tank with id [' + str(id) + '] was not found"}')
        except Exception as e:
            return json.dumps('{"success": false, "reason": "An exception occured: ' + e + '"}')


class revert_programs(ProtectedPage):
    def GET(self):
        data = web.input()
        try:
            id = data["water_tank_id"]
            state = WaterTankState( int(data["state"]) )
            print('id: {}, state: {}'.format(id, state.name))
            settings = get_settings()
            if id in settings[u"water_tanks"]:
                wt = WaterTankFactory.FromDict(settings[u"water_tanks"][id])
                wt.RevertPrograms(state)
                return '{"success": true, "reason": ""}'
            return '{"success": false, "reason": "water tank with id [' + str(id) + '] was not found"}'
        except Exception as e:
            return '{"success": false, "reason": "An exception occured: ' + e + '"}'


class sensor_log(ProtectedPage):
    def GET(self):
        records = read_sensor_log()
        return template_render.water_tank_log(records, get_settings())


class clear_sensor_log(ProtectedPage):
    """Delete all log records"""

    def GET(self):
        with io.open(LOG_FILE, "w") as f:
            f.write("")
        raise web.seeother("/water_plugin_sensor_log")


class csv_sensor_log(ProtectedPage):
    """Simple Log API"""

    def GET(self):
        records = read_sensor_log()
        data = _("Date, MQTT Topic, MQTT Payload") + "\n"
        for r in records:
            event = ast.literal_eval(json.dumps(r))
            data += (
                event["date"]
                + ", "
                + event["mqtt_topic"]
                + ", "
                + event["mqtt_payload"]
                + "\n"
            )

        web.header("Content-Type", "text/csv")
        return data


class DeadSensorMonitor(th.Thread):
    def __init__(self, interval_seconds):
        self.interval_seconds = interval_seconds
        # init last_check_time with yesterday's datetime to ensure first check at start
        self.last_check_time = datetime.now() - timedelta(days=1)    
        self._timer_runs = th.Event()
        self._timer_runs.set()
        super().__init__()

    def run(self):
        # NOTE: if a sensor sends a message and then dies it will not be detected at the 
        # first check. This is because the timer was already running and by the time it 
        # expires the sensor will not be considered dead. The sensor will be considered
        # dead the next time the timer expires
        while self._timer_runs.is_set():
            now = datetime.now()
            print("Time passed {} secs".format((now - self.last_check_time).total_seconds()))
            if( (now - self.last_check_time).total_seconds() > self.interval_seconds ):
                self.last_check_time = now
                self.check_dead_sensors()
                print("DeadSensorMonitor no check for the next {} seconds".format(self.interval_seconds))
            time.sleep(1)

    def stop(self):
        self._timer_runs.clear()

    def reset(self, interval_seconds):
        print("DeadSensorMonitor reset interval_seconds to {}".format(interval_seconds))
        self.interval_seconds = interval_seconds

    def check_dead_sensors(self):
        print("DeadSensorMonitor.check_dead_sensors()")
        settings = get_settings()
        for wtd in settings[u"water_tanks"].values():
            wt = WaterTankFactory.FromDict(wtd)
            dateDiff = datetime.now() - datetime.fromisoformat(wt.last_updated)
            if( dateDiff.total_seconds() < settings[MAX_SENSOR_NO_SIGNAL_TIME] ):
                continue
            
            msgSender = MessageSender(None, wt)
            msgSender.DeadSensorDetected()
            


#  Run when plugin is loaded
detect_water_tank_js() # add water_tank.js to base.html if ncessary
load_programs() # in order to load program names in gv.pnames
subscribe_mqtt()

dead_sensor_monitor = DeadSensorMonitor(get_settings()[MAX_SENSOR_NO_SIGNAL_TIME])
dead_sensor_monitor.start()
