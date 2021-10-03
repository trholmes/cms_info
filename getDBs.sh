datestr=`date +%F`
loc=/eos/user/t/tholmes/www/tova/other/

#python3 /afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/getDB.py 'http://icms-dev.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true&amp;domain=Management&amp;unit_type=board&amp;as_of='$datestr > ${loc}tenures_raw.json 

#which python3
#which python
#python3 --version
#python --version

python3 /afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/getDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true' > ${loc}tenures_raw.json

python3 /afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/getOldDB.py 'https://cms-mgt-conferences.web.cern.ch/conferences/conferences_list_short.aspx' > ${loc}cinco_raw.json
python3 /afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/getDB.py 'https://icms.cern.ch/tools-api/restplus/cadi/xeb_report?xeb_report_period=14' > ${loc}cadi_raw.json

python3 /afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/cleanup.py
python /afs/cern.ch/user/t/tholmes/useful_files/cron_scripts/cms-info/getCalendar.py
