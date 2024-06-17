import json
import datetime
from collections import OrderedDict

do_cinco=True

# Make function that returns the primary role of an ex-officio member
def getPrimaryRole(entry, full_db):
    my_id = entry["cms_id"]
    source_unit_id = entry["src_unit_id"]
    for dbentry in full_db:
        if dbentry["cms_id"]==my_id and dbentry["ex_officio_rule_id"]==None and source_unit_id == dbentry["unit_id"]:

            val = dbentry["domain"]
            if val in ["Collaboration"]: val += " Board"
            if val in ["Physics", "Technical", "Offline & Computing", "Run", "Upgrade"]: val += " Coordination"
            #if val in ["Physics", "Technical", "Offline & Computing", "Run", "Physics Performance & Datasets", "Trigger", "Upgrade"]: val += " Coordination"
            if val in ["International", "Awards", "Authorship", "Publications", "Detector Awards", "Industrial Awards", "Career", "Conference", "Schools", "Thesis Awards", "Data Preservation and Open Access"]: val += " Committee"
            if val in ["Diversity", "Communication", "Engagement"]: val += " Office"
            if val in ["Spokesperson"]: val += " Team"
            if val in ["Resources"]:
                if dbentry["position"] == "Manager": val = "Resources Manager"
                elif dbentry["position"] == "Deputy": val = "Deputy Resources Manager"

            return val
    return "Member"

# Clean up CINCO results
today = datetime.date.today()
year = str(today.year)

if do_cinco:
    f_cinco = "/eos/project-c/cmsweb/www/icmssecr/cms-info/cinco.json"

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

# Clean up nominations
f_nominations = "/eos/project-c/cmsweb/www/icmssecr/cms-info/nominations.json"
f = open(f_nominations.replace(".json", "_raw.json"), "r")
db_nominations = json.load(f)
f.close()

new_nominations = []
for entry in db_nominations:
    deadline = date_object = datetime.datetime.strptime(entry['nominations_deadline'], "%Y-%m-%d")
    entry["due_date"] = deadline.strftime("%b %d")
    if (deadline.date() - today).days > -14:
        new_nominations.append(entry)
f = open(f_nominations, "w")
json.dump(new_nominations, f)
f.close()

# Clean up CADI results
f_cadi = "/eos/project-c/cmsweb/www/icmssecr/cms-info/cadi.json"

with open(f_cadi.replace(".json", "_raw.json"), "r") as f:
    cadi_lines = f.readlines()
with open(f_cadi, "w") as f:
    for line in cadi_lines:
        if line.startswith("WARNING"): continue
        if line.startswith("ERROR"): continue
        f.write(line)

f = open(f_cadi, "r", encoding='utf-8')
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
f_tenures = "/eos/project-c/cmsweb/www/icmssecr/cms-info/tenures.json"

with open(f_tenures.replace(".json", "_raw.json"), "r") as f:
    tenures_lines = f.readlines()
with open(f_tenures, "w") as f:
    for line in tenures_lines:
        if line.startswith("ERROR"): continue
        if line.startswith("WARNING"): continue
        f.write(line)

f = open(f_tenures, "r", encoding='utf-8')
db_tenures = json.load(f)
f.close()

for entry in db_tenures:
    if entry["src_position_level"]==None: entry["src_position_level"]=4
    if entry["position_level"]==None: entry["position_level"]=4

db_tenures_sorted = sorted(db_tenures, key=lambda item: item["position_level"])
#db_tenures_sorted = sorted(db_tenures, key=lambda item: item["src_position_level"])
db_tenures_management = list(filter(lambda item: (item["domain"]=="Management"), db_tenures_sorted))

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
        "sp": "Spokesperson",
        }
collapse = ["eb", "mb", "cc", "ic", "sc", "co", "do", "eo", "oa", "pa", "ra", "ta", "tea", "ua"] # For these we won't actually display different sources
for b in boards:
    f = "/eos/project-c/cmsweb/www/icmssecr/cms-info/%s.json"%b
    db = OrderedDict()
    # Some little custom ordering (forcing these first)
    if b in ["mb", "eb"]: db["Office"] = []
    if b in ["cb", "eb", "fb"]: db["Board"] = []
    if b in ["ac"]: db["Committee"] = []
    for entry in db_tenures_sorted:
        if entry["domain"] == boards[b]:
            if entry["domain"] == "Publications" and entry["src_unit_type"] == "Editorial Board": continue
            if not entry["ex_officio_rule_id"]==None:
                key = "Ex-Officio Members"
                entry["position"] = getPrimaryRole(entry, db_tenures_sorted)
            else:
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
    f = "/eos/project-c/cmsweb/www/icmssecr/cms-info/%s.json"%b
    db = []
    for entry in db_tenures_sorted:
        if entry["domain"] == boards[b]:
            db.append(entry)
    f = open(f, "w")
    json.dump(db, f)
    f.close()
'''
