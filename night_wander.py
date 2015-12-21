#!/usr/bin/env python
# night_wander_app.py
# Copyright (C) ContinuumBridge Limited, 2014-2015 - All Rights Reserved
# Written by Peter Claydon
#

# Default values:
config = {
    "night_wandering": "True",
    "data_send_delay": 2,
    "night_start": "23:00",
    "night_end": "07:00",
    "ignore_time": 600
}

import sys
import os.path
import time
from cbcommslib import CbApp, CbClient
from cbconfig import *
from cbutils import nicetime, betweenTimes, hourMin2Epoch
import requests
import json
from twisted.internet import reactor
import smtplib
from email.mime.text import MIMEText

CONFIG_FILE                       = CB_CONFIG_DIR + "night_wander.config"
CID                               = "CID164"  # Client ID

class NightWander():
    def __init__(self):
        self.bridge_id = None
        self.activatedSensors = []
        self.s = []
        self.waiting = False
        self.state = {"wanderCount": 0}
        self.saveFile = None

    def setIDs(self, bridge_id, idToName):
        self.idToName = idToName
        self.bridge_id = bridge_id

    def reportEnds(self):
        #self.cbLog("debug", "reportEnds")
        try:
            now = time.strftime("%H:%M:%S", time.localtime()).split(":")[0:2]  # Format: ["06", "30"]
            nightEnd = config["night_end"].split(":")
            #self.cbLog("debug", "reportEnds, now: " + str(now) + ", nightEnd: " + str(nightEnd))
            if int(nightEnd[0]) == int(now[0]) and int(nightEnd[1]) == int(now[1]):
                timeStamp = time.time()
                values = {
                    "name": self.bridge_id + "/Night_Wander/" + "night_start",
                    "points": [[int(timeStamp*1000), int(hourMin2Epoch(config["night_start"]))*1000]]
                }
                self.storeValues(values)
                values = {
                    "name": self.bridge_id + "/Night_Wander/" + "night_end",
                    "points": [[int(timeStamp*1000), int(hourMin2Epoch(config["night_end"]))*1000]]
                }
                self.storeValues(values)
                values = {
                    "name": self.bridge_id + "/Night_Wander/" + "wander_count",
                    "points": [[int(timeStamp*1000), self.state["wanderCount"]]]
                }
                self.storeValues(values)
                self.state["wanderCount"] = 0
        except Exception as ex:
            self.cbLog("warning", "Problem running reportEnds. Type: " + str(type(ex)) + "exception: " +  str(ex.args))
        reactor.callLater(60, self.reportEnds)

    def onChange(self, devID, timeStamp, value):
        #self.cbLog("debug", "onChange, devID: " + devID + " value: " + value)
        if value == "on":
            alert = betweenTimes(timeStamp, config["night_start"], config["night_end"])
            self.cbLog("debug", "alert: " + str(alert) + ", activatedSensors: " + str(self.activatedSensors))
            if alert:
                sensor = self.idToName[devID]
                self.cbLog("debug", "sensor: " + sensor)
                values = {
                    "name": self.bridge_id + "/Night_Wander/" + sensor,
                    "points": [[int(timeStamp*1000), 1]]
                }
                self.storeValues(values)
                if sensor not in self.activatedSensors:
                    self.activatedSensors.append(sensor)
                    if len(self.activatedSensors) == 1:
                        self.state["wanderCount"] += 1
                        reactor.callLater(config["night_ignore_time"], self.endIgnoreTime)
                        self.reportAlert(timeStamp)

    def endIgnoreTime(self):
        self.cbLog("debug", "endIgnoreTime, activatedSensors: " + str(self.activatedSensors))
        if len(self.activatedSensors) > 1:
            self.reportAlert(time.time())
        self.activatedSensors = []

    def reportAlert(self, timeStamp):
        msg = {"m": "alert",
               "a": "Night wandering detected by " + str(", ".join(self.activatedSensors)) + " at " + nicetime(timeStamp),
               "t": timeStamp
              }
        self.client.send(msg)
        self.cbLog("debug", "msg send to client: " + str(json.dumps(msg, indent=4)))

    def sendValues(self):
        msg = {"m": "data",
               "d": self.s
               }
        self.cbLog("debug", "sendValues. Sending: " + str(json.dumps(msg, indent=4)))
        self.client.send(msg)
        self.s = []
        self.waiting = False

    def storeValues(self, values):
        if time.time() > 100000:  # To stop writing if time not updated by NTP
            self.s.append(values)
            if not self.waiting:
                self.waiting = True
                reactor.callLater(config["data_send_delay"], self.sendValues)
            else:
                self.cbLog("debug", "Values not stored because time is in 1970")

    def save(self):
        try:
            if self.state:
                with open(self.saveFile, 'w') as f:
                    json.dump(self.state, f)
                    self.cbLog("debug", "saving state:: " + str(self.bodies))
        except Exception as ex:
            self.cbLog("warning", "Problem saving state. Type: " + str(type(ex)) + "exception: " +  str(ex.args))

    def loadSaved(self):
        try:
            if os.path.isfile(self.saveFile):
                with open(self.saveFile, 'r') as f:
                    self.state = json.load(f)
                self.cbLog("debug", "Loaded saved state: " + str(self.state))
        except Exception as ex:
            self.cbLog("warning", "Problem loading saved state. Exception. Type: " + str(type(ex)) + "exception: " +  str(ex.args))
        finally:
            try:
                os.remove(self.saveFile)
                self.cbLog("debug", "deleted saved state file")
            except Exception as ex:
                self.cbLog("debug", "Cannot remove saved state file. Exception. Type: " + str(type(ex)) + "exception: " +  str(ex.args))

class App(CbApp):
    def __init__(self, argv):
        self.appClass = "monitor"
        self.state = "stopped"
        self.status = "ok"
        self.devices = []
        self.devTypes = {} 
        self.idToName = {} 
        self.entryExitIDs = []
        self.hotDrinkIDs = []
        self.nightWander = NightWander()
        #CbApp.__init__ MUST be called
        CbApp.__init__(self, argv)

    def setState(self, action):
        if action == "clear_error":
            self.state = "running"
        else:
            self.state = action
        msg = {"id": self.id,
               "status": "state",
               "state": self.state}
        self.sendManagerMessage(msg)

    def onStop(self):
        self.nightWander.save()
        self.client.save()

    def onConcMessage(self, message):
        #self.cbLog("debug", "onConcMessage, message: " + str(json.dumps(message, indent=4)))
        if "status" in message:
            if message["status"] == "ready":
                # Do this after we have established communications with the concentrator
                msg = {
                    "m": "req_config",
                    "d": self.id
                }
                self.client.send(msg)
        self.client.receive(message)

    def onClientMessage(self, message):
        self.cbLog("debug", "onClientMessage, message: " + str(json.dumps(message, indent=4)))
        global config
        if "config" in message:
            if "warning" in message["config"]:
                self.cbLog("warning", "onClientMessage: " + str(json.dumps(message["config"], indent=4)))
            else:
                try:
                    newConfig = message["config"]
                    copyConfig = config.copy()
                    copyConfig.update(newConfig)
                    if copyConfig != config or not os.path.isfile(CONFIG_FILE):
                        self.cbLog("debug", "onClientMessage. Updating config from client message")
                        config = copyConfig.copy()
                        with open(CONFIG_FILE, 'w') as f:
                            json.dump(config, f)
                        self.cbLog("info", "Config updated")
                        self.readLocalConfig()
                        # With a new config, send init message to all connected adaptors
                        for i in self.adtInstances:
                            init = {
                                "id": self.id,
                                "appClass": self.appClass,
                                "request": "init"
                            }
                            self.sendMessage(init, i)
                except Exception as ex:
                    self.cbLog("warning", "onClientMessage, could not write to file. Type: " + str(type(ex)) + ", exception: " +  str(ex.args))

    def onAdaptorData(self, message):
        #self.cbLog("debug", "onAdaptorData, message: " + str(json.dumps(message, indent=4)))
        if message["characteristic"] == "binary_sensor":
            if message["id"] in self.devTypes:
                if self.devTypes[message["id"]] == "inverted":
                    if message["data"] == "on":
                        state = "off"
                    else:
                        state = "on"
            else:
                state = message["data"]
            self.nightWander.onChange(message["id"], message["timeStamp"], state)

    def onAdaptorService(self, message):
        #self.cbLog("debug", "onAdaptorService, message: " + str(json.dumps(message, indent=4)))
        if self.state == "starting":
            self.setState("running")
        serviceReq = []
        for p in message["service"]:
            # Based on services offered & whether we want to enable them
            if p["characteristic"] == "binary_sensor":
                if "type" in p:
                    if p["type"] == "inverted":
                        self.devTypes[message["id"]] = "inverted"
                serviceReq.append({"characteristic": "binary_sensor", "interval": 0})
        msg = {"id": self.id,
               "request": "service",
               "service": serviceReq}
        self.sendMessage(msg, message["id"])
        self.cbLog("debug", "onAdaptorService, response: " + str(json.dumps(msg, indent=4)))

    def readLocalConfig(self):
        global config
        try:
            with open(CONFIG_FILE, 'r') as f:
                newConfig = json.load(f)
                self.cbLog("debug", "Read local config")
                config.update(newConfig)
        except Exception as ex:
            self.cbLog("warning", "Local config does not exist or file is corrupt. Exception: " + str(type(ex)) + str(ex.args))
        self.cbLog("debug", "Config: " + str(json.dumps(config, indent=4)))

    def onConfigureMessage(self, managerConfig):
        self.readLocalConfig()
        idToName2 = {}
        for adaptor in managerConfig["adaptors"]:
            adtID = adaptor["id"]
            if adtID not in self.devices:
                # Because managerConfigure may be re-called if devices are added
                name = adaptor["name"]
                friendly_name = adaptor["friendly_name"]
                self.cbLog("debug", "managerConfigure app. Adaptor id: " +  adtID + " name: " + name + " friendly_name: " + friendly_name)
                idToName2[adtID] = friendly_name
                self.idToName[adtID] = friendly_name.replace(" ", "_")
                self.devices.append(adtID)
        self.client = CbClient(self.id, CID, 5)
        self.client.onClientMessage = self.onClientMessage
        self.client.sendMessage = self.sendMessage
        self.client.cbLog = self.cbLog
        self.client.loadSaved()
        self.nightWander.bridge_id = self.bridge_id
        self.nightWander.cbLog = self.cbLog
        self.nightWander.client = self.client
        self.nightWander.setIDs(self.bridge_id, self.idToName)
        self.nightWander.saveFile = CB_CONFIG_DIR + self.id + ".savestate"
        self.nightWander.loadSaved()
        self.nightWander.reportEnds()
        self.setState("starting")

if __name__ == '__main__':
    App(sys.argv)
