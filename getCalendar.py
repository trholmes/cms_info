import json
import urllib2
import datetime

today = datetime.date.today()

urls = {
        "cms week": "https://indico.cern.ch/category/154/",
        "tracker week": "https://indico.cern.ch/category/1080/",
        "lhcc": "https://indico.cern.ch/category/3427/",
        "induction": "https://indico.cern.ch/category/14397/",
        "o&c": "https://indico.cern.ch/category/1382/",
        "rrb": "https://indico.cern.ch/category/12324/",
        "p2ug": "https://indico.cern.ch/category/11282/",
        }

def getURL(ev):
    default_url = "https://indico.cern.ch/category/6803/"
    if ev.lower() in urls: return urls[ev.lower()]
    for url in urls:
        if url in ev: return urls[url]
    return default_url

def getEvents(ev_data):
    events = []
    this_event = {}
    for line in ev_data:
        if line.startswith("BEGIN:VEVENT"):
            this_event = {}
        elif line.startswith("END:VEVENT"):
            events.append(this_event)
        else:
            try:
                this_event[line.split(":")[0]]=":".join(line.split(":")[1:]).strip()
            except:
                continue
    return events

def isSoon(event, days_from_now = 21, days_ago = 5):
    try:
        time_str = ""
        for val in event:
            if "DTSTART" in val: time_str = val
        try:
            edate = datetime.datetime.strptime(event[time_str], '%Y%m%d').date()
        except:
            edate = datetime.datetime.strptime(event[time_str].split("T")[0], '%Y%m%d').date()
    except Exception as e:
        return False, None
    if (edate - today).days < days_from_now and (today-edate).days < days_ago:
        return True, edate
    return False, edate

tmp_cal = "/afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/cal.ics"
json_file = "/eos/user/t/tholmes/www/tova/other/cal.json"

## Grab events from the CMS calendar

cal_file = "https://www.google.com/calendar/ical/dnfcb10nk2fj96tcippfoprpak%40group.calendar.google.com/public/basic.ics"
data = urllib2.urlopen(cal_file)
output = data.read()
with open(tmp_cal, 'w') as f:
    f.write(output)
with open(tmp_cal, 'r') as f:
    ev_data = f.readlines()
events = getEvents(ev_data)
events_to_write = []
for event in events:
    is_soon, edate = isSoon(event)
    if is_soon:
        if event["SUMMARY"] not in ["FB", "MB", "MB/FB"]:
            url = getURL(event["SUMMARY"])
            ev_data = {"name": event["SUMMARY"], "url": url, "date": edate.strftime("%d %b")+": ", "ndays": (edate - today).days}
            events_to_write.append(ev_data)

## Add in Physics events
for cal_file in ["https://indico.cern.ch/category/1304/events.ics?user_token=46464_KKxBLg2bPTWlvzJzUUgVRR3KFKxxvOF9wYA2A6jAnuM"]:
    data = urllib2.urlopen(cal_file)
    output = data.read()
    with open(tmp_cal, 'w') as f:
        f.write(output)
    with open(tmp_cal, 'r') as f:
        ev_data = f.readlines()
    events = getEvents(ev_data)
    for event in events:
        is_soon, edate = isSoon(event, 10, 1)
        if is_soon:
            ev_data = {"name": event["SUMMARY"], "url": event["URL"], "date": edate.strftime("%d %b")+": ", "ndays": (edate - today).days}
            events_to_write.append(ev_data)

## Add in CERN EP and LHC seminars
for cal_file in ["https://indico.cern.ch/category/3249/events.ics", "https://indico.cern.ch/category/3247/events.ics"]:
    data = urllib2.urlopen(cal_file)
    output = data.read()
    with open(tmp_cal, 'w') as f:
        f.write(output)
    with open(tmp_cal, 'r') as f:
        ev_data = f.readlines()
    events = getEvents(ev_data)
    for event in events:
        is_soon, edate = isSoon(event, 10, 1)
        if is_soon:
            ev_data = {"name": "CERN Seminar: " + event["SUMMARY"], "url": event["URL"], "date": edate.strftime("%d %b")+": ", "ndays": (edate - today).days}
            events_to_write.append(ev_data)

## Check if empty and package up in a json

if len(events_to_write)==0:
    ev_data = {"name": "None", "url": "/cms-internal/cms-calendar/", "date": "", "ndays": 0}
    events_to_write.append(ev_data)

sorted_events = sorted(events_to_write, key=lambda item: item["ndays"])

f = open(json_file, "w")
json.dump(sorted_events, f)
f.close()


###### Make a separate file for PC events
json_file = "/eos/user/t/tholmes/www/tova/other/cal_physics.json"
events_to_write = []

## add approvals

cal_file = "https://calendar.google.com/calendar/ical/teir7hdjshmfgvcl2jmopq186g%40group.calendar.google.com/public/basic.ics"
data = urllib2.urlopen(cal_file)
output = data.read()
with open(tmp_cal, 'w') as f:
    f.write(output)
with open(tmp_cal, 'r') as f:
    ev_data = f.readlines()
events = getEvents(ev_data)
for event in events:
    is_soon, edate = isSoon(event, 21, 5)
    if is_soon:
        ev_data = {"name": event["SUMMARY"], "url": event["DESCRIPTION"], "date": edate.strftime("%d %b")+": ", "ndays": (edate - today).days}
        events_to_write.append(ev_data)

## Check if empty and package up in a json

if len(events_to_write)==0:
    ev_data = {"name": "None", "url": "/cms-internal/cms-calendar/", "date": "", "ndays": 0}
    events_to_write.append(ev_data)

sorted_events = sorted(events_to_write, key=lambda item: item["ndays"])

f = open(json_file, "w")
json.dump(sorted_events, f)
f.close()
