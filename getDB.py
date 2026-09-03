#!/usr/bin/env python3

import datetime as dt
import sys
import subprocess
from urllib.parse import urlparse

url = sys.argv[1]
args = sys.argv[2:]

logInfo = [ f"Starting at: {dt.datetime.now().isoformat(timespec='minutes')}" ]

res = urlparse( url )
urlAuth = f'{res.scheme}://{res.netloc}'
if 'icms.cern' in  res.netloc: urlAuth += '/tools'
# print( f'got urlAuth: {urlAuth}' )

curlArgs = ''
if args: curlArgs = ' '.join(args).split('|',1)[0]

# print( 'got: %s %s ' % (url, sys.argv[1:]) )

# use these two lines for the old SSO
#cmd = 'cern-get-sso-cookie --krb --outfile ~/private/cadiana.sso --reprocess -u %s ;' % (url,)
#cmd += 'curl --silent --cookie-jar ~/private/cadiana.sso --cookie ~/private/cadiana.sso -k -L %s ' % (url,)

# these are for the new SSO:
cookieFileName = '~/private/sso-auth-cookie-cms_info-0'
cmd = f'rm -f {cookieFileName};'
cmd += f'auth-get-sso-cookie --outfile {cookieFileName} -u \'{urlAuth}\';'
cmd += f'curl --silent -b  {cookieFileName} -k -L \'{url}\';'
# cmd += f'rm -f {cookieFileName};'

if curlArgs != '':
   cmd = '%s %s' % (cmd, curlArgs )

logInfo.append( 'cmd: %s ' % (cmd.replace(';', '\n'),) )

res=''
try:
    res = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
    logInfo.append( "cmd returned:")
    logInfo.append( f"{res.decode('utf-8')}")
except Exception as e:
    logInfo.append( "ERROR: got: %s" % (str(e),) )
    logInfo.append( "    output: %s " % (str(res)) )


logFileName = '/afs/cern.ch/user/c/cmswww/cms_info/logs/logInfo.txt'
with open(logFileName, 'w') as lf:
   lf.write( '\n'.join(logInfo) )
