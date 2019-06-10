#!/usr/bin/env python3

# Script for sending SMS via my Huawei router, after inspiration
# from https://blog.hqcodeshop.fi/archives/259-Huawei-E5186-AJAX-API.html
# and https://github.com/Salamek/huawei-lte-api
#
# Author: John Bergbom

# Prerequisites:
# sudo apt-get install python3-requests
# sudo apt-get install python3-xmltodict
#
# For creating the sqlite database for sms sending:
# CREATE TABLE sent_sms (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, time TIMESTAMP NOT NULL, sending_succeeded INTEGER NOT NULL, phone_number VARCHAR(30) NOT NULL, message VARCHAR(500) NOT NULL);
#
# The properties file may look something like this:
# baseurl = http://address_to_huawei_4g_router
# username = some_user_name
# password = some_password
# # allowed_phone_numbers is a comma separated list of allowed phone numbers
# allowed_phone_numbers = +358451111111,+358452222222
# database = /home/john/home_sensors/sms_sending.db


import requests
import re
import hashlib
import base64
import xmltodict
import time
import sys
import sqlite3
import datetime

properties_file = "/root/send_sms.properties"

def read_properties():
    properties = {}
    fh = None
    try:
        fh = open(properties_file)
    except PermissionError:
        print("Can't open properties file, aborting")
        exit(1)
    for line in fh:
        if "=" in line:
            name, value = line.split("=",1)
            properties[name.strip()] = value.strip()
    fh.close()
    return properties

def grep_csrf(html):
    pat = re.compile(r".*meta name=\"csrf_token\" content=\"(.*)\"", re.I)
    matches = (pat.match(line) for line in html.splitlines())
    return [m.group(1) for m in matches if m]

def hash_password(username,password_type,password,csrf_token):
    if password_type == "4":		# sha256
        blob = b''.join([
            username.encode('utf-8'),
            base64.b64encode(hashlib.sha256(password.encode('utf-8')).hexdigest().encode('ascii')),
            csrf_token.encode('utf-8')
        ])
        password = base64.b64encode(hashlib.sha256(blob).hexdigest().encode('ascii'))
        return password
    elif password_type == "0":	# base64
        print("Base64 password type not yet supported, aborting.")
        exit(1)
    else:
        print("Unknown password type, aborting.")
        exit(1)

def login(properties):
    # Start by getting the CSRF token
    s = requests.Session()
    r = s.get(properties["baseurl"] + "/html/index.html")
    csrf_tokens = grep_csrf(r.text)
    s.headers.update({
        '__RequestVerificationToken': csrf_tokens[0]
    })

    # Then figure out the expected password type
    r = s.get(properties["baseurl"]  + "/api/user/state-login")
    state_login_dict = xmltodict.parse(r.content, dict_constructor=dict)
    expected_password_type = state_login_dict['response']['password_type']

    hashed_password = hash_password(properties["username"],expected_password_type,properties["password"],csrf_tokens[0])
    login_data = "<?xml version=\"1.0\" encoding=\"UTF-8\" ?><request><Username type=\"str\">" + properties["username"] + "</Username><Password type=\"str\">" + hashed_password.decode() + "</Password><password_type type=\"int\">4</password_type></request>"
    r = s.post(properties["baseurl"] + "/api/user/login", data=login_data)
    logon_succeeded = False
    if r.text.find("<response>OK</response>") >= 0:
        logon_succeeded = True
    s.headers.update({
        '__RequestVerificationToken': r.headers["__RequestVerificationToken"]
    })
    return logon_succeeded, s

def send_sms(properties,s,message,phone_number,time_str):
    # Encode certain characters
    message = message.replace("&","&amp;")
    message = message.replace("(","&#40;")
    message = message.replace(")","&#41;")
    message = message.replace("'","&#39;")
    message = message.replace('"','&quot;')
    message = message.replace("/","&#x2F;")
    message = message.replace("<","&lt;")
    message = message.replace(">","&gt;")
    # No special treatment is needed of scandic characters
    # if they are in utf-8 encoding.
    #message = message.replace("å",chr(229))
    #message = message.replace("ä",chr(228))
    #message = message.replace("ö",chr(246))
    #message = message.replace("Å",chr(197))
    #message = message.replace("Ä",chr(196))
    #message = message.replace("Ö",chr(214))

    # Create the payload
    payload = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><request><Index>-1</Index><Phones><Phone>" + phone_number + "</Phone></Phones><Sca></Sca><Content>" + message + "</Content><Length>" + str(len(message)) + "</Length><Reserved>1</Reserved><Date>" + time_str + "</Date></request>"

    # Send the SMS
    headers = { 'Content-Type': 'charset=UTF-8' }
    r = s.post(properties["baseurl"] + "/api/sms/send-sms", data=payload.encode('utf-8'), headers=headers)
    sending_succeeded = False
    if r.text.find("<response>OK</response>") >= 0:
        sending_succeeded = True
    else:
        print("Sending SMS failed.")
    s.headers.update({
        '__RequestVerificationToken': r.headers["__RequestVerificationToken"]
    })
    return sending_succeeded, s

def logout(properties,s):
    r = s.post(properties["baseurl"] + "/api/user/logout", data="<?xml version=\"1.0\" encoding=\"UTF-8\"?><request><Logout>1</Logout></request>")
    if r.text.find("<response>OK</response>") == -1:
        print("Logout of SMS sending device failed.")
    s.headers.update({
        '__RequestVerificationToken': r.headers["__RequestVerificationToken"]
    })
    return s

if len(sys.argv) != 3:
    print("Syntax: " + sys.argv[0] + " <phone number> <SMS message>")
    exit(1)
phone_number = sys.argv[1]
message = sys.argv[2]
properties = read_properties()
if phone_number not in properties["allowed_phone_numbers"].split(","):
    print("Not allowed to send SMS to number " + phone_number)
    exit(1)
t = time.localtime()
time_str = str(t.tm_year) + "-" + str(t.tm_mon).zfill(2) + "-" + str(t.tm_mday).zfill(2) + " " + str(t.tm_hour).zfill(2) + ":" + str(t.tm_min).zfill(2) + ":" + str(t.tm_sec).zfill(2)


# Check if we have already sent at least five SMS's within the last
# five minutes, and if we have, then refuse to send any more. This
# is a safety precaution to make sure that we don't send out like
# a million SMS's in one hour due to some programming bug (that would
# get expensive).
sending_allowed = False
conn = None
c = None
try:
    conn = sqlite3.connect(properties["database"])
    c = conn.cursor()
    c.execute("select time from sent_sms order by time desc limit 5")
    last_five_sms_timestamps = c.fetchall()
    nbr_of_sent = len(last_five_sms_timestamps)
    if nbr_of_sent < 5:
        sending_allowed = True
    else:
        curr_time = datetime.datetime.strptime(time_str,"%Y-%m-%d %H:%M:%S")
        time_of_five_back = None
        try:
            time_of_five_back = datetime.datetime.strptime(last_five_sms_timestamps[4][0],"%Y-%m-%d %H:%M:%S")
        except:
            print("Database messed up, wrong format of timestamp " + last_five_sms_timestamps[4][0], + ". Aborting.")
            conn.close()
            exit(1)
        if time_of_five_back + datetime.timedelta(minutes = 5) < curr_time:
            sending_allowed = True
except:
    print("Can't talk to the database, aborting.")
    conn.close()
    exit(1)
if sending_allowed == False:
    print("Has already sent five SMS's within the last five minutes, aborting (rate throttled).")
    conn.close()
    exit(1)

logon_succeeded, s = login(properties)
if logon_succeeded == False:
    print("Logon to SMS sending device failed, aborting")
    conn.close()
    exit(1)
sending_succeeded, s = send_sms(properties,s,message,phone_number,time_str)
c.execute("insert into sent_sms (time,sending_succeeded,phone_number,message) values(?,?,?,?)",(time_str,sending_succeeded,phone_number,message))
s = logout(properties,s)

conn.commit()
conn.close()


