#!/usr/bin/env python3

import sys
import subprocess

url = sys.argv[1]
args = sys.argv[2:]

urlAuth = 'https://icms.cern.ch/tools'

curlArgs = ''
if args: curlArgs = ' '.join(args).split('|',1)[0]

# print( 'got: %s %s ' % (url, sys.argv[1:]) )

# use these two lines for the old SSO
#cmd = 'cern-get-sso-cookie --krb --outfile ~/private/cadiana.sso --reprocess -u %s ;' % (url,)
#cmd += 'curl --silent --cookie-jar ~/private/cadiana.sso --cookie ~/private/cadiana.sso -k -L %s ' % (url,)

# these are for the new SSO:
cookieFileName = '~/private/sso-auth-cookie-cms_info'
cmd = f'rm -f {cookieFileName};'
cmd += f'auth-get-sso-cookie --outfile {cookieFileName} -u \'{urlAuth}\';'
cmd += f'curl --silent -b  {cookieFileName} -k -L \'{url}\';'
cmd += f'rm -f {cookieFileName};'

if curlArgs != '':
   cmd = '%s %s' % (cmd, curlArgs )

# print ( 'cmd: %s ' % (cmd.replace(';', '\n'),) )

res=''
try:
    res = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
    print( res.decode('utf-8') )
except Exception as e:
    print ( "ERROR: got: %s" % (str(e),) )
    print ( "    output: %s " % (str(res)) )

