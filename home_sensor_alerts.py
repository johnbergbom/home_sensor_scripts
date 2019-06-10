#!/usr/bin/env python3

import sqlite3
import subprocess

# For creating the sqlite database for acknowledgements:
# CREATE TABLE acknowledged_wleaks (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, itemname VARCHAR(500) NOT NULL, time TIMESTAMP NOT NULL, value VARCHAR(6) NOT NULL, acknowledged INTEGER NOT NULL);
# CREATE TABLE human_sensor_names (openhab_sensor_name varchar(500) NOT NULL, human_name VARCHAR(40) NOT NULL)
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d00023ea30d_leak','garage-arbetsrum-temp');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d000233db38_leak','hallen-jk-fram');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d0002329984_leak','bastu-jk-2');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d000233dd55_leak','tvattstugan-jk');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d000237b474_leak','pannrum-vt');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d000233dd77_leak','garage-varmvattenberedare1');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d0002379b2e_leak','hallen-jk-bak');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d000233dd45_leak','garage-varmvattenberedare-golv');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d000233daa8_leak','kok-diskmaskin');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d000239ec47_leak','bastu-jk-1');
# INSERT INTO human_sensor_names values('mihome_sensor_wleak_aq1_158d000233db30_leak','kok-vask-vt');



# Connect to the databases
conn_sensor = sqlite3.connect('/var/lib/openhab2/home_sensors_sqlite.db')
cs = conn_sensor.cursor()
conn_alerts = sqlite3.connect('/home/john/home_sensors/home_sensor_alerts_sqlite.db')
ca = conn_alerts.cursor()

def send_sms_alert(phone_number,message):
    print("Sending the following alert via SMS: " + message)
    result = subprocess.Popen(["/usr/bin/sudo", "/usr/local/bin/send_sms.py", phone_number, message])
    test = result.communicate()[0]
    sms_sent = False
    if result.returncode == 0:
        sms_sent = True
    return sms_sent

def get_human_sensor_name(dict,sensor_name):
    #if dict[sensor_name] != None:
    if sensor_name in dict:
        return dict[sensor_name]
    # Look it up in the database if it didn't exist in the dictionary
    ca.execute("select human_name from human_sensor_names where openhab_sensor_name = ?",(sensor_name, ))
    human_name = ca.fetchone()
    if human_name == None:
        human_name = "UNKNOWN " + sensor_name
        dict[sensor_name] = human_name
    else:
        dict[sensor_name] = human_name[0]
    return dict[sensor_name]


def acknowledge_sent_alert(sensor,time,value):
    ca.execute("INSERT INTO acknowledged_wleaks (itemname,time,value,acknowledged) values(?,?,?,1)",(sensor,time,value))



# Check for water leaks
dict_sensor_name = {}
cs.execute("select ItemId, itemname from items where itemname like '%wleak%_leak'")
water_leak_detectors = cs.fetchall()
for wleak in water_leak_detectors:
    #print(wleak[1])
    #print("Executing sql query: select time, value from item" + str(wleak[0]).zfill(4) + " order by time desc limit 10")
    cs.execute("select time, value from item" + str(wleak[0]).zfill(4) + " order by time desc limit 10")
    alerts = cs.fetchall()
    for alert in reversed(alerts):
        ca.execute("select acknowledged from acknowledged_wleaks where itemname = ? and time = ? and value = ? and acknowledged = 1",(wleak[1],alert[0],alert[1]))
        acknowledged = ca.fetchone()
        if acknowledged == None:
            human_sensor_name = get_human_sensor_name(dict_sensor_name,wleak[1])
            #print("Not acknowledged: water leak in " + str(human_sensor_name) + " at " + alert[0] + " with value " + alert[1])
            sms_sent = send_sms_alert("+358451329257","water leak in " + human_sensor_name + " at " + alert[0] + " with value " + alert[1])
            sms_sent = send_sms_alert("+358407268528","water leak in " + human_sensor_name + " at " + alert[0] + " with value " + alert[1])
            if sms_sent == False:
                print("Failed to send SMS.")
            else:
                acknowledge_sent_alert(wleak[1],alert[0],alert[1])
		




# Close the databases
conn_alerts.commit()
conn_alerts.close()
conn_sensor.close()
