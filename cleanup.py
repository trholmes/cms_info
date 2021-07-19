import json
import datetime
from collections import OrderedDict

# Clean up CINCO results
today = datetime.date.today()
year = str(today.year)

f_cinco = "/eos/user/t/tholmes/www/tova/other/cinco.json"

f = open(f_cinco.replace(".json", "_raw.json"), "r")
db_cinco = json.load(f)
f.close()

new_cinco = []
for entry in db_cinco["JConference"]:
    if entry["ShortName"]=="":
        entry["ShortName"] = entry["Name"]
    if year in entry["Date"]:
        entry["Date"] = entry["Date"].replace(year,"").strip()
    if "virtual" in entry["Location"] or "Virtual" in entry["Location"]:
        entry["Location"] = "Virtual"
    if "SCHOOL" in entry["Category"]:
        continue
    if entry["CategoryDescription"]=="CERN seminars":
        continue
    if len(db_cinco)>10:
        if entry["Category"] in ["NATCONF", "SMALLCON"]:
            continue
    if len(new_cinco)>5: continue
    new_cinco.append(entry)

f = open(f_cinco, "w")
json.dump(new_cinco, f)
f.close()

# Clean up CADI results
f_cadi = "/eos/user/t/tholmes/www/tova/other/cadi.json"

f = open(f_cadi.replace(".json", "_raw.json"), "r")
db_cadi = json.load(f)
f.close()

for cat in db_cadi:
    try:
        for entry in db_cadi[cat]:
            if len(entry["day"].split("/"))==3:
                edate = datetime.datetime.strptime(entry["day"], '%d/%m/%Y')
                entry["day"] = edate.strftime("%d %b")
    except:
        continue
if "SUB" not in db_cadi:
    db_cadi["SUB"]=[{"code": "None", "url": "https://cms.cern.ch/iCMS/analysisadmin/cadilines"}]
if "CWR" not in db_cadi:
    db_cadi["CWR"]=[{"code": "None", "url": "https://cms.cern.ch/iCMS/analysisadmin/cadilines"}]

f = open(f_cadi, "w")
json.dump(db_cadi, f)
f.close()

# Clean up tenures results
f_tenures = "/eos/user/t/tholmes/www/tova/other/tenures.json"

f = open(f_tenures.replace(".json", "_raw.json"), "r")
db_tenures = json.load(f)
f.close()

for entry in db_tenures:
    if entry["src_position_level"]==None: entry["src_position_level"]=4

db_tenures_sorted = sorted(db_tenures, key=lambda item: item["src_position_level"])
db_tenures_management = filter(lambda item: (item["domain"]=="Management"), db_tenures_sorted)

f = open(f_tenures, "w")
json.dump(db_tenures_management, f)
f.close()

# Make separate pages for board memberships so I can sort them nicely
boards = {
        "mb": "Management",
        "cb": "Collaboration",
        "fb": "Finance",
        "eb": "Executive",
        "ac": "Authorship",
        "cc": "Career",
        "coc": "Conference",
        "ic": "International",
        "pc": "Publications",
        "sc": "Schools",
        "co": "Communication",
        "do": "Diversity",
        "eo": "Engagement",
        "oa": "Offline & Computing",
        "pa": "Physics Performance & Datasets",
        "pha": "Physics",
        "ra": "Run",
        "ta": "Trigger",
        "tea": "Technical",
        "ua": "Upgrade",
        }
collapse = ["cc", "coc", "ic", "pc", "sc", "co", "do", "eo", "oa", "pa", "ra", "ta", "tea", "ua"] # For these we won't actually display different sources
for b in boards:
    f = "/eos/user/t/tholmes/www/tova/other/%s.json"%b
    db = OrderedDict()
    # Some little custom ordering (forcing these first)
    if b in ["mb", "eb"]: db["Office"] = []
    if b in ["cb", "eb"]: db["Board"] = []
    for entry in db_tenures_sorted:
        if entry["domain"] == boards[b]:
            key = entry["src_unit_type"]
            if b in collapse: key = "all"
            if key not in db: db[key] = []
            db[key].append(entry)
    mod_db = []
    for entry in db:
        mod_db.append({"type":entry, "members":db[entry]})
    f = open(f, "w")
    json.dump(mod_db, f)
    f.close()

'''
# Simpler structure for committees
boards = {
        "pc": "Publications",
}
for b in boards:
    f = "/eos/user/t/tholmes/www/tova/other/%s.json"%b
    db = []
    for entry in db_tenures_sorted:
        if entry["domain"] == boards[b]:
            db.append(entry)
    f = open(f, "w")
    json.dump(db, f)
    f.close()
'''
