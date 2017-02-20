import re
import time
import os
import socket
import sys
import json

import eight

simulate = True

if not simulate:
    import nav_imu

import nav_log
from nav_log import tolog, tolog0

from nav_util import sign, dist, start_new_thread

if not simulate:
    import nav_mqtt
import nav_tc

import nav_signal
import nav1
import nav2
import nav_comm
import wm
import driving

from math import pi, cos, sin, sqrt, atan2, acos, asin, log


class globals:
    pass

g = globals()

g.simulate = simulate

if not simulate:
    nav_imu.g = g
nav_log.g = g
if not simulate:
    nav_mqtt.g = g
nav_tc.g = g
nav_signal.g = g
nav_comm.g = g
wm.g = g
nav1.g = g
nav2.g = g
driving.g = g

g.s = None

g.VIN = None
#g.VIN = sys.argv[1]

g.parameter = 164
g.parameter = 100
g.parameter = 152
g.parameter = 120

#--------------------
# Configuration flags:

g.allangles = False

# setting this to True is the same as setting goodmarkers to []?
g.ignoremarkers = False

#g.detectcrashes = False
g.detectcrashes = True

#--------------------
# Configuration parameters:

g.anglefactor = 2.0
g.targetdist = 0.3

#g.minquality = 0.5
#g.maxmarkerdist = 1.0
#g.maxoffroad = 10

g.minquality = 0.35
g.maxmarkerdist = 2.0
g.maxoffroad = 0.1

g.slightlyoffroad = 0.03

# None to disable:
g.adjdistlimit = 0.4

g.badmarkers = [0]
#g.badmarkers = [5]

g.goodmarkers = [25, 10, 43]
g.goodmarkers = None

#--------------------
# Flags and variables for reporting by wm:

g.poserror = False
g.maxadjdist = 0

g.paused = False

#--------------------

# can be local to wm.py
g.adjust_t = None

# nav_imu and wm
#g.oldpos = dict()
g.oldpos = None

g.speedtime = None

g.speedsign = 1
g.braking = False

# magnetics
g.mxmin = None
g.mxmax = None
g.mymin = None
g.mymax = None

g.currentbox = None

# updated by wm (CAN)
g.inspeed = 0.0
g.finspeed = 0.0
g.inspeed_avg = 0.0
g.odometer = 0
g.fodometer = 0
g.can_steer = 0
g.can_speed = 0
g.can_ultra = 0.0

# set by wm (CAN) and not used now
g.rc_button = False


g.limitspeed = None

# local to 'heartbeat' in nav.py
g.limitspeed0 = "notset"

g.last_send = None

g.remote_control = False

g.obstacle = False

g.targetx = None
g.targety = None

g.logf = None
g.accf = None


# px etc. is the dead reckoning from the IMU acc and gyro
# ppx etc. is the dead reckoning from wheel speed and gyro
g.px = None
g.py = None
g.pz = None

g.ppx = 0
g.ppy = 0
g.ppz = None

g.vx = None
g.vy = None
g.vz = None

g.ang = 0.0

# set by nav_imu
g.crash = False

# local to nav.connect_to_ecm but interesting to look at
g.crashacc = None

# set by wm, used by nav_imu
g.angdiff = 0.0
g.ppxdiff = 0.0
g.ppydiff = 0.0

# set once by nav.py
g.t0 = None

# set my nav_mqtt
g.battery = 0.0
g.ultra = 0.0

g.signalling = False

g.ledcmd = None

wm.wminit()
nav1.nav1init()
if not simulate:
    nav_imu.imuinit()
    nav_mqtt.mqttinit()
nav_tc.tcinit()
driving.drivinginit()
nav_signal.signalinit()

def connect_to_ecm():
    stopped = False

    s = nav_comm.open_socket2()

    ecmt0 = time.time()

    counter = 0
    g.crashacc = None

    while True:
        if g.crashacc:
            #g.crash = False
            if not stopped:
                counter = 9
                #s.send("crash".encode('ascii'))
                print("crash: %f" % g.crash)
                g.remote_control = True
                #stop()
                driving.drive(0)
                #speak("ouch")
                nav_signal.warningblink(True)
                stopped = True
                s112 = nav_comm.open_socket3()
                sstr = ('accident %f %f %f %s\n' % (
                        g.ppx, g.ppy, g.crashacc, g.VIN)).encode("ascii")
                print(sstr)
                s112.send(sstr)
                print(sstr)
                resp = s112.recv(1024)
                print(resp)
                resp = resp.decode("ascii")
                print(resp)
                if True:
                    resp = json.loads(resp)
                    print(resp)
                    say = resp['speak']
                else:
                    say = resp
                print(say)
                speak(say)
                s112.close()

        if True:
            t = time.time()
            if t-ecmt0 > 1.0:
                #s.send("bar".encode('ascii'))
                g.crashacc = 0.0
                if g.crash:
                    g.crashacc = g.crash
                    nav_tc.send_to_ground_control(
                        "message crash %f" % g.crashacc)
                s.send(('{"crash":%d, "x":%f, "y":%f, "crashacc":%f}\n' % (
                            counter, g.ppx, g.ppy, g.crashacc)).encode("ascii"))
                ecmt0 = t
        time.sleep(0.05)
        if counter != 9:
            counter = (counter+1)%8

g.heartn = -1
g.heartn_r = -1

def heartbeat():
    while True:
        g.heartn += 1
        nav_tc.send_to_ground_control(
            "heart %.3f %d" % (time.time()-g.t0, g.heartn))

        if g.heartn-g.heartn_r > 1:
            print("waiting for heart echo %d %d" % (g.heartn, g.heartn_r))

        if g.heartn-g.heartn_r > 3:
            if g.limitspeed0 == "notset":
                print("setting speed to 0 during network pause")
                g.limitspeed0 = g.limitspeed
                g.limitspeed = 0.0

        if g.heartn-g.heartn_r < 2:
            if g.limitspeed0 != "notset":
                print("restoring speed limit to %s after network pause" % (str(g.limitspeed0)))
                g.limitspeed = g.limitspeed0
                g.limitspeed0 = "notset"

        time.sleep(5)

g.canSocket = None

def initializeCAN(network):
    """
    Initializes the CAN network, and returns the resulting socket.
    """
    # create a raw socket and bind it to the given CAN interface
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.bind((network,))
    return s

def readvin():
    if simulate:
        return "car0"

    f = open("/home/pi/can-utils/java/settings.properties")
    for line0 in f:
        line = line0[:-1]
        m = re.match("VIN=(.*)", line)
        if m:
            return m.group(1)
    return None

def init():
    g.VIN = readvin()
    print("VIN %s" % g.VIN)

    if g.VIN == "car5":
        g.mxmin = -99
        g.mxmax = -40
        g.mymin = 100
        g.mymax = 152

    if g.VIN == "car3":
        g.mxmin = -20
        g.mxmax = 39
        g.mymin = 37
        g.mymax = 85

    # fake, just to make them defined
    if g.VIN == "car4":
        g.mxmin = 0
        g.mxmax = 100
        g.mymin = 0
        g.mymax = 100

    canNetwork = "can0"
    canFrameID = 1025
    if not simulate:
        g.canSocket = initializeCAN(canNetwork)

    g.angleknown = False

    eight.eightinit()

    nav_signal.setleds(0, 7)

    start_new_thread(nav_tc.connect_to_ground_control, ())

    g.logf = open("navlog", "w")
    g.accf = open("acclog", "w")
    #g.accf.write("%f %f %f %f %f %f %f %f %f %f %f %f %f\n" % (
    #x, y, g.vx, g.vy, g.px, g.py, x0, y0, vvx, vvy, g.ppx, g.ppy, g.ang))
    g.accf.write("x y vx vy px py x0 y0 vvx vvy ppx ppy ang angvel steering speed inspeed outspeed odometer z0 r rx ry acc finspeed fodometer t can_ultra\n")

    g.t0 = time.time()
    print("t0 = %f" % g.t0)

    tolog("init")

    if not simulate:
        nav_imu.calibrate_imu()

    if not simulate:
        start_new_thread(wm.readmarker, ())
    if not simulate:
        start_new_thread(nav_mqtt.handle_mqtt, ())
    if not simulate:
        start_new_thread(wm.readspeed2, ())
    if not simulate:
        start_new_thread(nav_imu.readgyro, ())
    if not simulate:
        start_new_thread(driving.senddrive, ())
    if not simulate:
        start_new_thread(keepspeed, ())
    start_new_thread(heartbeat, ())
    if not simulate:
        start_new_thread(connect_to_ecm, ())

    if simulate:
        g.steering = 0
        g.finspeed = 0
        start_new_thread(wm.simulatecar, ())

g.senddriveinhibited = False

def inhibitdodrive():
    g.senddriveinhibited = True



def keepspeed():
    outspeedi = 0

    # 0 to 9
    speeds = [0, 7, 11, 15, 19, 23, 27, 37, 41, 45, 49,
              # 93 to 100 haven't been run yet
              53, 57, 73, 77, 81, 85, 89, 93, 97, 100]

    while True:
        time.sleep(0.1)

        if g.outspeedcm == None:
            continue

        spi = outspeedi

        desiredspeed = g.outspeedcm

        if g.limitspeed != None and desiredspeed > g.limitspeed:
            desiredspeed = g.limitspeed

        if g.user_pause:
            desiredspeed = 0

        if desiredspeed > g.finspeed:
            if spi < len(speeds)-1:
                spi += 1
        elif desiredspeed < g.finspeed:
            if spi > 0:
                spi -= 1

        desiredspeed_sign = sign(desiredspeed)
        desiredspeed_abs = abs(desiredspeed)
        if True:
            # bypass the control
            spi = int(desiredspeed_abs/10)
            if spi > len(speeds)-1:
                spi = len(speeds)-1
            sleeptime = 1
        else:
            sleeptime = 3

        sp = speeds[spi]
        outspeedi = spi
        # spi/outspeedi don't remember the sign

        sp *= desiredspeed_sign

        if False:
            print("outspeedcm %f finspeed %f outspeedi %d spi %d sp %f outspeed %f" % (
                    g.outspeedcm, g.finspeed, outspeedi, spi, sp, g.outspeed))

        if g.outspeed == sp and sp != 0:
#            pass
            continue

        g.outspeed = sp

        if abs(sp) >= 7:
            g.speedtime = time.time()
        else:
            g.speedtime = None

        if sp != 0 and not g.braking:
            g.speedsign = sign(sp)

        if sp != 0:
            nav_signal.warningblink(False)

#        if sp < 0:
#            sp += 256
        st = g.steering
#        if st < 0:
#            st += 256
        tolog("motor %d steer %d" % (sp, st))
        driving.dodrive(sp, st)
        time.sleep(sleeptime)


#============================================================
# User commands

def initpos():
    g.markercnt = 0
    g.angleknown = False
    g.crash = False
    g.crashacc = None
    g.remote_control = False

def reset():
    g.remote_control = False
    g.rc_button = False
    g.warningblinking = False
    nav_signal.setleds(0,7)
    g.markerno = 0
    g.markercnt = 0
    g.angleknown = False
    g.crash = False
    g.crashacc = None
    # should we reset the connect_to_ecm thread somehow?





global perc

def gooval(perc0):
    start_new_thread(goovalaux, (perc0,))

def goovalaux(perc0):
    global perc

    perc = perc0

    #g.goodmarkers = [25]

    driving.drive(0)
    time.sleep(4)
    sp = 15
    driving.drive(sp)

    while True:
        print("1")
        driving.steer(0)
        print("2")
        nav2.goto_1(1.9, 17)
        print("3")
        print("marker %s" % (str(g.lastpos)))
        driving.steer(-100)
        print("4")
        # 250 comes from pi*80 (cm)
        # it's the outer radius, but so is the speed we get
        print("finspeed1 %f dang1 %f ang1 %f" % (g.finspeed, g.dang, g.ang%360))
        time.sleep(250.0/g.finspeed*perc)
        print("finspeed2 %f dang2 %f ang2 %f" % (g.finspeed, g.dang, g.ang%360))
        driving.steer(0)
        print("5")
        nav2.goto_1(0.5, 13)
        print("6")
        driving.steer(-100)
        time.sleep(250.0/g.finspeed*perc)
