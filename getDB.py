#!/usr/bin/env python3

import sys
import subprocess

url = sys.argv[1]
args = sys.argv[2:]

curlArgs = ''
if args: curlArgs = ' '.join(args).split('|',1)[0]

# print( 'got: %s %s ' % (url, sys.argv[1:]) )

# use these two lines for the old SSO
#cmd = 'cern-get-sso-cookie --krb --outfile ~/private/cadiana.sso --reprocess -u %s ;' % (url,)
#cmd += 'curl --silent --cookie-jar ~/private/cadiana.sso --cookie ~/private/cadiana.sso -k -L %s ' % (url,)

# these are for the new SSO:
cmd = 'auth-get-sso-cookie --outfile ~/private/sso-auth-cookie -u \'%s\' ;' % (url,)
cmd += 'curl --silent --cookie-jar ~/private/sso-auth-cookie --cookie ~/private/sso-auth-cookie -k -L \'%s\' ' % (url,)

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

