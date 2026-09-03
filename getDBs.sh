

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

# Job openings -> /incubator/api/job_openings, not in service yet: Glance
# still has configuration work to finish and its audience is not known, so
# nominations.json keeps whatever it last had.
#python3 getTokenDB.py 'https://cmsfence.cern.ch/incubator/api/job_openings' -o ${loc}nominations_raw.json --expect-json

# CADI xeb_report -> the ALCM analysis xeb-report (audience cms-alcm-api-prod).
# "period" replaces the old "xeb_report_period", and the reports come wrapped
# in a {"period": N, "reports": {...}} object which cleanup.py unwraps.
python3 getTokenDB.py 'https://cmsfence.cern.ch/alcm/api/analysis/xeb-report' -d 'period=14' -o ${loc}cadi_raw.json --expect-json

# CINCO is now on the new SSO with a fix for the SSO to allow scripts to go through instead of choking on some "javascript not enabled" URL in the sequence

# for now, use the tool with Sebastian's workaround:
cd auth-get-sso-cookie
. ./activate.sh
cd ..
python3 ./getDB.py 'https://cms-mgt-conferences.web.cern.ch/conferences/conferences_list_short.aspx' > ${loc}cinco_raw.json 

python3 ./cleanup.py
python3 ./getCalendar.py
