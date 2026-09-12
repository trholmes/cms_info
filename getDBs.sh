

datestr=`date +%F`
# loc=/eos/user/t/tholmes/www/tova/other/
# loc=/eos/user/c/cmswww/www/cms_info/
loc=/eos/project-c/cmsweb/www/icmssecr/cms-info/

#python3 /afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/getDB.py 'http://icms-dev.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true&amp;domain=Management&amp;unit_type=board&amp;as_of='$datestr > ${loc}tenures_raw.json 

#which python3
#which python
#python3 --version
#python --version

cd /afs/cern.ch/user/c/cmswww/cms_info

# try also to use this one here, as sometimes the standard one seems to fail to load:
cd auth-get-sso-cookie
. ./activate.sh
cd ..

# The old iCMS tools-api endpoints have been removed. Their Glance
# replacements take an OIDC access token instead of an SSO cookie, and each
# API has its own audience - see the README.
#
# Tenures -> the Membership appointments search. The limit matters: without it
# the API returns only the first 50 of ~1200 and the other paging parameters
# are ignored. cleanup.py parses these records into the old shape.
python3 getTokenDB.py 'https://cmsfence.cern.ch/membership/api/appointments/search' -d 'queryString="startDate" <= "'$datestr'" AND "endDate" >= "'$datestr'"' -d 'limit=5000' -o ${loc}tenures_raw.json --expect-json

# The appointments records name a member's institute but not its short code,
# which the pages display, so fetch the institutes to look the codes up.
python3 getTokenDB.py 'https://cmsfence.cern.ch/membership/api/institutes/search' -d 'limit=5000' -o ${loc}institutes_raw.json --expect-json

# Job openings -> the incubator API. Its audience is vocms0705, not the
# cms-*-api-prod the other two use. Note the trailing slash on the path.
python3 getTokenDB.py 'https://cmsfence.cern.ch/incubator/api/job_openings/' -o ${loc}nominations_raw.json --expect-json

# CADI xeb_report -> the ALCM analysis xeb-report (audience cms-alcm-api-prod).
# "period" replaces the old "xeb_report_period", and the reports come wrapped
# in a {"period": N, "reports": {...}} object which cleanup.py unwraps.
python3 getTokenDB.py 'https://cmsfence.cern.ch/alcm/api/analysis/xeb-report' -d 'period=14' -o ${loc}cadi_raw.json --expect-json

# CINCO has an API of its own now. It does not use the api-access flow: it
# has its own client (cinco_prod) and takes a plain client credentials grant
# at the standard token endpoint with a scope rather than an audience.
# getTokenDB.py knows that from its PROFILES table; the secret belongs to
# CINCO and lives in the "clients" block of cms_info_sso.json.
python3 getTokenDB.py 'https://cms-mgt-conferences.web.cern.ch/api/conferences_upcoming.ashx' -d 'months=6' -o ${loc}cinco_raw.json --expect-json

# The same API can list an institute's talks, if the site ever wants them:
#python3 getTokenDB.py 'https://cms-mgt-conferences.web.cern.ch/api/presentations_by_institute.ashx' -d 'inst_code=TENNESSEE' -o ${loc}talks_raw.json --expect-json

python3 ./cleanup.py
python3 ./getCalendar.py
