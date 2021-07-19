import json
import urllib2
import datetime

today = datetime.date.today()

cal_file = "https://www.google.com/calendar/ical/dnfcb10nk2fj96tcippfoprpak%40group.calendar.google.com/public/basic.ics"
tmp_cal = "/afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/cal.ics"
json_file = "/eos/user/t/tholmes/www/tova/other/cal.json"
data = urllib2.urlopen(cal_file)
output = data.read()

with open(tmp_cal, 'w') as f:
    f.write(output)

with open(tmp_cal, 'r') as f:
    ev_data = f.readlines()

events = []
this_event = {}
for line in ev_data:
    if line.startswith("BEGIN:VEVENT"):
        this_event = {}
    elif line.startswith("END:VEVENT"):
        events.append(this_event)
    else:
        try:
            this_event[line.split(":")[0]]=line.split(":")[1].strip()
        except:
            continue


events_to_write = []
for event in events:
    try:
        edate = datetime.datetime.strptime(event["DTSTART;VALUE=DATE"], '%Y%m%d').date()
    except:
        continue
    if (edate - today).days < 21 and (edate - today).days > -5:
        if event["SUMMARY"] not in ["FB", "MB"]:
            ev_data = {"name": event["SUMMARY"], "url": "https://indico.cern.ch/category/154/", "date": edate.strftime("%d %b")+": ", "ndays": (edate - today).days}
            events_to_write.append(ev_data)

if len(events_to_write)==0:
    ev_data = {"name": "None", "url": "/cms-internal/cms-calendar/", "date": "", "ndays": 0}
    events_to_write.append(ev_data)

sorted_events = sorted(events_to_write, key=lambda item: item["ndays"])

f = open(json_file, "w")
json.dump(sorted_events, f)
f.close()
