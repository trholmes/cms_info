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

# The Glance appointments API replaced the old org_chart/tenures endpoint. Its
# records cover the same appointments, but the unit somebody was appointed to
# is only there as prose in categoryName, of the form
# "<position> of <unit> <unit type>", so the fields the board pages below are
# built from have to be parsed back out of it.
appointmentUnitTypes = ["Coordination Area", "Editorial Board", "Funding Agency",
                        "Subdetector", "Committee", "Institute", "Region",
                        "Board", "Office", "Advisors"]

# Which parsed unit belongs to which of the domains the board pages use.
# Anything not listed here has no page and is left out of them.
appointmentDomains = {
        "Management": "Management",
        "Collaboration": "Collaboration",
        "Finance": "Finance",
        "Authorship": "Authorship",
        "Career": "Career",
        "Conference": "Conference",
        "Publications": "Publications",
        "Schools": "Schools",
        "Communication": "Communication",
        "External Communication": "Communication",
        "Internal Communication": "Communication",
        "Diversity": "Diversity",
        "Engagement": "Engagement",
        "Offline & Computing": "Offline & Computing",
        "Physics Performance & Datasets": "Physics Performance & Datasets",
        "Physics": "Physics",
        "Run": "Run",
        "Trigger": "Trigger",
        "Technical": "Technical",
        "Upgrade": "Upgrade",
        "Spokesperson": "Spokesperson",
        "Spokesperson & Technical Coordination": "Spokesperson",
        }

# Rough ordering within a page, standing in for the position_level the old
# endpoint gave us and this one does not.
appointmentPositionLevels = {
        "Spokesperson": 0,
        "Chairperson": 1,
        "Coordinator": 1,
        "Manager": 1,
        "Deputy Coordinator": 2,
        "Deputy": 2,
        "Secretary": 2,
        "Advisor": 3,
        "Member": 4,
        }

# Split a categoryName into its position, unit and unit type
def parseCategoryName(name):
    for unit_type in appointmentUnitTypes:
        suffix = " %s"%unit_type
        if name.endswith(suffix) and " of " in name:
            position, unit = name[:-len(suffix)].split(" of ", 1)
            return position, unit, unit_type
    # e.g. "Chairperson of External Communication", with no unit type
    if " of " in name:
        position, unit = name.split(" of ", 1)
        return position, unit, "Committee"
    # e.g. "Team Leader", "TRG working group convenor" - no unit, so no page
    return name, None, None

# Turn an appointments record into the shape the rest of this script expects
def appointmentToTenure(entry):
    position, unit, unit_type = parseCategoryName(entry.get("categoryName") or "")
    tenure = dict(entry)
    tenure["position"] = position
    tenure["domain"] = appointmentDomains.get(unit)
    tenure["src_unit_type"] = unit_type
    # The new records carry no ex-officio information, so nobody is grouped as
    # an ex-officio member any more and getPrimaryRole is not reached.
    tenure["ex_officio_rule_id"] = None
    tenure["position_level"] = appointmentPositionLevels.get(position, 5)
    tenure["src_position_level"] = tenure["position_level"]
    tenure["cms_id"] = entry.get("memberId")
    tenure["unit_id"] = entry.get("categoryId")
    tenure["src_unit_id"] = entry.get("categoryId")
    # the names the pages were reading before
    tenure["name"] = entry.get("memberName")
    tenure["institute"] = entry.get("instituteName")
    tenure["start_date"] = entry.get("startDateString")
    tenure["end_date"] = entry.get("endDateString")
    return tenure

# Clean up CINCO results
today = datetime.date.today()
year = str(today.year)

if do_cinco:
    f_cinco = "/eos/project-c/cmsweb/www/icmssecr/cms-info/cinco.json"

    try:
        f = open(f_cinco.replace(".json", "_raw.json"), "r")
        try:
            db_cinco = json.load(f)
        except json.decoder.JSONDecodeError as e:
            print( f'ERROR when trying to read json from cinco - got: {str(e)} ' )
            f.seek(0)
            [ print( f'{x}' ) for x in f.readlines()[:5] ]
            raise
        finally:
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
    except Exception as e:
        print( f'ERROR when cleaning up cinco, leaving the old file - got: {str(e)} ' )

# Clean up nominations
# Each source is handled on its own so that one dead endpoint leaves the other
# pages alone instead of stopping the script: the .json a section cannot
# rebuild keeps whatever it had from the last good run.
f_nominations = "/eos/project-c/cmsweb/www/icmssecr/cms-info/nominations.json"
try:
    f = open(f_nominations.replace(".json", "_raw.json"), "r")
    db_nominations = json.load(f)
    f.close()

    new_nominations = []
    for entry in db_nominations:
        deadline = date_object = datetime.datetime.strptime(entry['nominations_deadline'], "%Y-%m-%d")
        entry["due_date"] = deadline.strftime("%b %d")
        # The Glance job openings endpoint renames this field, so take either
        status = entry.get('job_open_position_status', entry.get('status'))
        if (deadline.date() - today).days > -14 and status == 'active':
            new_nominations.append(entry)
    f = open(f_nominations, "w")
    json.dump(new_nominations, f)
    f.close()
except Exception as e:
    print( f'ERROR when cleaning up nominations, leaving the old file - got: {str(e)} ' )

# Clean up CADI results
f_cadi = "/eos/project-c/cmsweb/www/icmssecr/cms-info/cadi.json"

try:
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
except Exception as e:
    print( f'ERROR when cleaning up cadi, leaving the old file - got: {str(e)} ' )

# Clean up tenures results
f_tenures = "/eos/project-c/cmsweb/www/icmssecr/cms-info/tenures.json"

db_tenures_sorted = []
try:
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

    # The appointments API wraps its records in "results" and includes ones
    # that have expired, which the old endpoint did not.
    if isinstance(db_tenures, dict) and "results" in db_tenures:
        db_tenures = [ appointmentToTenure(entry) for entry in db_tenures["results"]
                       if entry.get("status") == "Active" ]

    for entry in db_tenures:
        if entry["src_position_level"]==None: entry["src_position_level"]=4
        if entry["position_level"]==None: entry["position_level"]=4

    db_tenures_sorted = sorted(db_tenures, key=lambda item: item["position_level"])
    #db_tenures_sorted = sorted(db_tenures, key=lambda item: item["src_position_level"])
    db_tenures_management = list(filter(lambda item: (item["domain"]=="Management"), db_tenures_sorted))

    f = open(f_tenures, "w")
    json.dump(db_tenures_management, f)
    f.close()
except Exception as e:
    print( f'ERROR when cleaning up tenures, leaving the old files - got: {str(e)} ' )


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
    if not db_tenures_sorted: continue # tenures unreadable, leave the pages alone
    f = "/eos/project-c/cmsweb/www/icmssecr/cms-info/%s.json"%b
    db = OrderedDict()
    # Some little custom ordering (forcing these first)
    if b in ["eb"]: db["Office"] = []
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

    # Manual sorting for the Management Board
    if b in ["mb"]:
        preferred_positions = ["Spokesperson Team", "Secretary", "Collaboration Board", "Resources Manager", "Engagement Office", "Spokesperson & Technical Coordination", "Advisor"]
        rank = {position: i for i, position in enumerate(preferred_positions)}
        for members in db.values():
            members.sort(key=lambda entry: rank.get(entry.get("position"), len(rank)))

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
