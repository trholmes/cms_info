

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

python3 ./getDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true' > ${loc}tenures_raw.json

# as long as CINCO is behind the old SSO, use lxplus7:
ssh -q lxplus7 "cd cms_info; python3 ./getOldDB.py 'https://cms-mgt-conferences.web.cern.ch/conferences/conferences_list_short.aspx' > ${loc}cinco_raw.json "

# check if there was a problem, if so, wait a bit and retry
grep 'Error: Cannot authenticate to: https://cms-mgt-conferences.web' /eos/project-c/cmsweb/www/icmssecr/cms-info/cinco_raw.json >/dev/null 2>&1
ret=$?
if [ "${ret}" == "0" ]; then
    sleep 10
    ssh -q lxplus7 "cd cms_info; python3 ./getOldDB.py 'https://cms-mgt-conferences.web.cern.ch/conferences/conferences_list_short.aspx' > ${loc}cinco_raw.json "
fi

python3 ./getDB.py 'https://icms.cern.ch/tools-api/restplus/cadi/xeb_report?xeb_report_period=14' > ${loc}cadi_raw.json
python3 ./getDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/job_openings' > ${loc}nominations_raw.json

python3 ./cleanup.py
python3 ./getCalendar.py
