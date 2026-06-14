

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

python3 ./getDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true' > ${loc}tenures_raw.json
python3 ./getDB.py 'https://icms.cern.ch/tools-api/restplus/cadi/xeb_report?xeb_report_period=14' > ${loc}cadi_raw.json
python3 ./getDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/job_openings' > ${loc}nominations_raw.json

# CINCO is now on the new SSO with a fix for the SSO to allow scripts to go through instead of choking on some "javascript not enabled" URL in the sequence

# for now, use the tool with Sebastian's workaround:
cd auth-get-sso-cookie
. ./activate.sh
cd ..
python3 ./getDB.py 'https://cms-mgt-conferences.web.cern.ch/conferences/conferences_list_short.aspx' > ${loc}cinco_raw.json 

python3 ./cleanup.py
python3 ./getCalendar.py
