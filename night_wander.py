#!/usr/bin/env python
# night_wander_app.py
# Copyright (C) ContinuumBridge Limited, 2014-2015 - All Rights Reserved
# Written by Peter Claydon
#

# Default values:
config = {
    "night_wandering": "False"
}

import sys
import os.path
import time
from cbcommslib import CbApp, CbClient
from cbconfig import *
import requests
import json
from twisted.internet import reactor
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

CONFIG_FILE                       = CB_CONFIG_DIR + "night_wander.config"
CID                               = "CID164"  # Client ID

def betweenTimes(t, t1, t2):
    # True if epoch t is between times of day t1 and t2 (in 24-hour clock format: "23:10")
    t1secs = (60*int(t1.split(":")[0]) + int(t1.split(":")[1])) * 60
    t2secs = (60*int(t2.split(":")[0]) + int(t2.split(":")[1])) * 60
    stamp = time.strftime("%Y %b %d %H:%M", time.localtime(t)).split()
    today = stamp
    today[3] = "00:00"
    today_e = time.mktime(time.strptime(" ".join(today), "%Y %b %d %H:%M"))
    yesterday_e = today_e - 24*3600
    #print "today_e: ", today_e, "yesterday_e: ", yesterday_e
    tt1 = [yesterday_e + t1secs, today_e + t1secs]
    tt2 = [yesterday_e + t2secs, today_e + t2secs]
    #print "tt1: ", tt1, " tt2: ", tt2
    smallest = 50000
    decision = False
    if t - tt1[0] < smallest and t - tt1[0] > 0:
        smallest = t - tt1[0]
        decision = True
    if t - tt2[0] < smallest and t -tt2[0] > 0:
        smallest = t - tt2[0]
        decision = False
    if t - tt1[1] < smallest and t -tt1[1] > 0:
        smallest = t - tt1[1]
        decision = True
    if t - tt2[1] < smallest and t - tt2[1] > 0:
        smallest = t - tt2[1]
        decision = False
    return decision

def nicetime(timeStamp):
    localtime = time.localtime(timeStamp)
    milliseconds = '%03d' % int((timeStamp - int(timeStamp)) * 1000)
    now = time.strftime('%H:%M:%S, %d-%m-%Y', localtime)
    return now

class NightWander():
    def __init__(self, bridge_id):
        self.bridge_id = bridge_id
        self.lastActive = 0
        self.activatedSensors = []
        self.s = []
        self.waiting = False

    def setNames(self, idToName):
        self.idToName = idToName

    def onChange(self, devID, timeStamp, value):
        self.cbLog("debug", "onChange, devID: " + devID + " value: " + value)
        if value == "on":
            alert = betweenTimes(timeStamp, config["night_start"], config["night_end"])
            self.cbLog("debug", "alert: " + str(alert))
            if alert:
                sensor = self.idToName[devID]
                self.cbLog("debug", "sensor: " + sensor)
                if sensor not in self.activatedSensors:
                    self.activatedSensors.append(self.idToName[devID])
                if timeStamp - self.lastActive > config["night_ignore_time"]:
                    self.cbLog("debug", "Night Wander: " + str(alert) + ": " + str(time.asctime(time.localtime(timeStamp))) + \
                    " sensors: " + str(self.activatedSensors))
                    msg = {"m": "alert",
                           "a": "Night wandering detected by " + str(", ".join(self.activatedSensors)) + " at " + nicetime(timeStamp),
                           "t": timeStamp
                          }
                    self.client.send(msg)
                    self.cbLog("debug", "msg send to client: " + str(json.dumps(msg, indent=4)))
                    self.lastActive = timeStamp
                    self.activatedSensors = []
                    values = {
                        "name": self.bridge_id + "/Night_Wander/" + sensor,
                        "points": [[int(timeStamp*1000), 1]]
                    }
                    self.storeValues(values)

    def sendValues(self):
        msg = {"m": "data",
               "d": self.s
               }
        self.cbLog("debug", "sendValues. Sending: " + str(json.dumps(msg, indent=4)))
        self.client.send(msg)
        self.s = []
        self.waiting = False

    def storeValues(self, values):
        self.s.append(values)
        if not self.waiting:
            self.waiting = True
            reactor.callLater(config["data_send_delay"], self.sendValues)

class App(CbApp):
    def __init__(self, argv):
        self.appClass = "monitor"
        self.state = "stopped"
        self.status = "ok"
        self.devices = []
        self.devServices = [] 
        self.idToName = {} 
        self.entryExitIDs = []
        self.hotDrinkIDs = []
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
        #self.cbLog("debug", "onClientMessage, message: " + str(json.dumps(message, indent=4)))
        global config
        if "config" in message:
            if "warning" in message["config"]:
                self.cbLog("warning", "onClientMessage: " + str(json.dumps(message["config"], indent=4)))
            else:
                try:
                    config = message["config"]
                    with open(CONFIG_FILE, 'w') as f:
                        json.dump(config, f)
                    self.cbLog("info", "Config updated")
                except Exception as ex:
                    self.cbLog("warning", "onClientMessage, could not write to file. Type: " + str(type(ex)) + ", exception: " +  str(ex.args))
                self.readLocalConfig()

    def onAdaptorData(self, message):
        #self.cbLog("debug", "onAdaptorData, message: " + str(json.dumps(message, indent=4)))
        if message["characteristic"] == "binary_sensor":
            self.nightWander.onChange(message["id"], message["timeStamp"], message["data"])

    def onAdaptorService(self, message):
        #self.cbLog("debug", "onAdaptorService, message: " + str(json.dumps(message, indent=4)))
        if self.state == "starting":
            self.setState("running")
        self.devServices.append(message)
        serviceReq = []
        for p in message["service"]:
            # Based on services offered & whether we want to enable them
            if p["characteristic"] == "binary_sensor":
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
            self.cbLog("warning", "LoCAL config does not exist or file is corrupt. Exception: " + str(type(ex)) + str(ex.args))
        for c in config:
            if c.lower in ("true", "t", "1"):
                config[c] = True
            elif c.lower in ("false", "f", "0"):
                config[c] = False
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
        self.nightWander = NightWander(self.bridge_id)
        self.nightWander.cbLog = self.cbLog
        self.nightWander.client = self.client
        self.nightWander.setNames(idToName2)
        self.setState("starting")

if __name__ == '__main__':
    App(sys.argv)
