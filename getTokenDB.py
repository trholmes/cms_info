#!/usr/bin/env python3
"""Fetch data from a CERN API using an OIDC API access token.

This is the token-based counterpart to getDB.py: instead of logging in with
Kerberos and carrying an SSO session cookie, it authenticates as a registered
OIDC client and sends a bearer token to the API. See
https://auth.docs.cern.ch/user-documentation/oidc/api-access/

The flow is:

  1. POST a client credentials grant to
     https://auth.cern.ch/auth/realms/cern/api-access/token
     with our client_id, client_secret, and an `audience` naming the target
     application (the Client ID of whoever owns the API, not ours).
  2. Send the returned access token to the API as
     `Authorization: Bearer <token>`.

No Kerberos ticket is needed, which makes this well suited to a cron job.
Note that the token identifies a service account (`service-account-<client
id>`), not a person, so the target application must have granted that account
access - via a role mapped to a group that our client subscribes to.

Usage:
    python3 getTokenDB.py <url> [-o outfile] [--expect-json] [--audience <client-id>]
    python3 getTokenDB.py --check --audience <client-id>   # test the credentials only

Credentials are read from, in order of precedence:
    1. the command line (--client-id, --audience)
    2. the environment (CERN_CLIENT_ID, CERN_CLIENT_SECRET, CERN_API_AUDIENCE)
    3. a JSON config file, by default cms_info_sso.json next to this
       script, e.g.

        {
            "client_id": "cms-info-scraper",
            "client_secret": "00000000-0000-0000-0000-000000000000",
            "audiences": {
                "icms.cern.ch": "the-target-api-client-id"
            }
        }

    Create it with restrictive permissions:
        touch cms_info_sso.json
        chmod 600 cms_info_sso.json
    That path is inside this git repository, so it is listed in .gitignore.
    Never commit the client secret.
"""

import argparse
import base64
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- defaults --

AUTH_SERVER = 'auth.cern.ch'
REALM = 'cern'

DEFAULT_CLIENT_ID = 'cms-info-scraper'
DEFAULT_CONFIG_FILE = 'cms_info_sso.json'
TOKEN_CACHE_FILE = '.cms_info_token_cache.json'

# Which target application (audience) to ask a token for, per host. The
# audience is the Client ID of the application that owns the API, not ours.
# These can also be set in the "audiences" block of the config file.
AUDIENCES = {
    # This is the application cms-info-scraper was actually granted access to,
    # which is what makes it the audience: permissions are granted per target
    # application, so the one we were let into is the one we can ask tokens
    # for. (An earlier guess of vocms0705, read off the browser login redirect
    # that cmsfence.cern.ch issues, was never granted to us and got a 401.)
    'cmsfence.cern.ch': 'glance-api-access-client',
    # The iCMS tools API is Glance-backed too, so the same audience may well
    # work for it. Untested - uncomment and try once cmsfence is confirmed.
    # 'icms.cern.ch': 'glance-api-access-client',
}

# Tokens are short lived; renew this many seconds before the stated expiry.
EXPIRY_MARGIN = 60
HTTP_TIMEOUT = 60
RETRIES = 3


def log(msg, verbose=True):
    """Diagnostics go to stderr so that stdout stays pure data."""
    if verbose:
        print(msg, file=sys.stderr)


# ------------------------------------------------------------ config --------

def load_config(path):
    """Merge the config file, the environment and the built-in defaults."""
    cfg = {
        'client_id': DEFAULT_CLIENT_ID,
        'client_secret': None,
        'audiences': dict(AUDIENCES),
    }

    path = os.path.expanduser(path)
    if os.path.exists(path):
        if os.stat(path).st_mode & (stat.S_IRGRP | stat.S_IROTH):
            log(f'WARNING: {path} is readable by others; run "chmod 600 {path}"')
        with open(path) as handle:
            try:
                from_file = json.load(handle)
            except json.JSONDecodeError as exc:
                raise SystemExit(f'ERROR: could not parse {path}: {exc}')
        cfg['audiences'].update(from_file.pop('audiences', {}))
        cfg.update({k: v for k, v in from_file.items() if v is not None})

    for key, env in (('client_id', 'CERN_CLIENT_ID'),
                     ('client_secret', 'CERN_CLIENT_SECRET')):
        if os.environ.get(env):
            cfg[key] = os.environ[env]

    return cfg


def audience_for(url, cfg, override=None):
    """The target application to request a token for, or None."""
    if override:
        return override
    if os.environ.get('CERN_API_AUDIENCE'):
        return os.environ['CERN_API_AUDIENCE']
    host = urllib.parse.urlparse(url).netloc.split(':')[0]
    return cfg['audiences'].get(host)


# ------------------------------------------------------------- tokens -------

def token_endpoint(auth_server=AUTH_SERVER, realm=REALM):
    return f'https://{auth_server}/auth/realms/{realm}/api-access/token'


def decode_claims(token):
    """Decode the (unverified) payload of a JWT, for diagnostics only."""
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def read_cached_token(audience, cache_file):
    try:
        with open(os.path.expanduser(cache_file)) as handle:
            cache = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    entry = cache.get(audience)
    if entry and entry.get('expires_at', 0) - EXPIRY_MARGIN > time.time():
        return entry['access_token']
    return None


def write_cached_token(audience, token, expires_in, cache_file):
    path = os.path.expanduser(cache_file)
    try:
        with open(path) as handle:
            cache = json.load(handle)
    except (OSError, json.JSONDecodeError):
        cache = {}
    cache[audience] = {
        'access_token': token,
        'expires_at': time.time() + float(expires_in),
    }
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(cache, handle)


def get_token(cfg, audience, auth_server=AUTH_SERVER, realm=REALM,
              cache_file=TOKEN_CACHE_FILE, use_cache=True, verbose=False):
    """Client credentials grant against the CERN api-access token endpoint."""
    if use_cache:
        cached = read_cached_token(audience, cache_file)
        if cached:
            log('using cached access token', verbose)
            return cached

    if not cfg.get('client_secret'):
        raise SystemExit(
            'ERROR: no client secret. Set CERN_CLIENT_SECRET or put it in '
            f'{DEFAULT_CONFIG_FILE} (see the docstring at the top of this file).')

    data = urllib.parse.urlencode({
        'grant_type': 'client_credentials',
        'client_id': cfg['client_id'],
        'client_secret': cfg['client_secret'],
        'audience': audience,
    }).encode()

    url = token_endpoint(auth_server, realm)
    log(f'requesting token for audience "{audience}" as "{cfg["client_id"]}"', verbose)
    request = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'})

    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')[:500]
        raise SystemExit(
            f'ERROR: token request failed ({exc.code} {exc.reason}): {body}\n'
            '       Check the client id and secret, that the audience is the '
            'target application\'s Client ID, and that the target application '
            'has granted this client API access.')
    except urllib.error.URLError as exc:
        raise SystemExit(f'ERROR: could not reach {url}: {exc.reason}')

    token = payload['access_token']
    write_cached_token(audience, token, payload.get('expires_in', 600), cache_file)
    return token


# ------------------------------------------------------------ fetching ------

class NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect to another host.

    A bearer token must never be replayed to a different host, and in practice
    a cross-host redirect here means the API did not accept the token and is
    bouncing us to the SSO login page. Failing loudly is much easier to debug
    than silently saving a login page into a .json file.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old_host = urllib.parse.urlparse(req.full_url).netloc
        new_host = urllib.parse.urlparse(newurl).netloc
        if old_host != new_host:
            raise urllib.error.URLError(
                f'redirected from {old_host} to {newurl} - the API did not '
                'accept the access token (wrong audience, missing permissions, '
                'or the endpoint expects a session cookie instead - in that '
                'case use getDB.py)')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_with_token(url, token, verify=True, verbose=False):
    opener = urllib.request.build_opener(NoCrossHostRedirect)
    if not verify:
        import ssl
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        opener.add_handler(urllib.request.HTTPSHandler(context=context))

    request = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
    })
    log(f'GET {url}', verbose)
    with opener.open(request, timeout=HTTP_TIMEOUT) as response:
        return response.read().decode('utf-8', 'replace')


def read_supplied_token(args):
    """A token obtained elsewhere, e.g. by `auth-get-user-token -o token.txt`.

    Useful for testing: that tool uses the device grant, so the token belongs
    to a real person rather than to our service account. If a URL works with
    one and not the other, the problem is permissions, not the endpoint.
    """
    if args.token:
        return args.token.strip()
    if args.token_file:
        with open(os.path.expanduser(args.token_file)) as handle:
            return handle.read().strip()
    return None


def describe_refusal(exc, token, audience, verbose=False):
    """Explain a 401/403 from the API.

    The two are different problems and it is worth not confusing them:
      401 the token was not accepted at all - wrong audience, or the endpoint
          validates against a different issuer/key. Nothing to do with roles.
      403 the token was accepted, but this identity may not read this resource,
          which is the case that needs a role on the target application.
    Apache's mod_auth_openidc puts the precise reason in WWW-Authenticate, so
    show that first; its HTML body says nothing useful.
    """
    claims = decode_claims(token)
    challenge = exc.headers.get('WWW-Authenticate') if exc.headers else None

    lines = [f'ERROR: the API refused the token ({exc.code} {exc.reason}).']
    if challenge:
        lines.append(f'       server said: {challenge}')
    lines.append(f'       token sent: sub="{claims.get("sub", "?")}" '
                 f'aud="{claims.get("aud", "?")}"')

    if verbose and exc.headers:
        # Which layer refused matters: mod_auth_openidc always challenges with
        # WWW-Authenticate, so a 401 without one tends to come from the
        # application behind Apache rather than from token validation.
        lines.append('       response headers:')
        lines += [f'         {k}: {v}' for k, v in exc.headers.items()]

    if exc.code == 401 and not challenge:
        lines += [
            '       401 with no WWW-Authenticate header: Apache\'s OIDC module',
            '       always challenges when it rejects a token, so this refusal',
            '       probably comes from the application behind it, not from',
            '       token validation. The token looks fine to the web server;',
            '       the application does not recognise this identity. Compare',
            '       with a personal token (--token-file) to confirm: if that',
            '       works, the service account needs an identity or permission',
            '       inside the application itself, not a different audience.',
        ]
    elif exc.code == 401:
        lines += [
            '       401 means the token was not accepted, which is usually the',
            f'       audience: we asked for "{audience}", but the API may validate',
            '       a different Client ID. Ask its owners which "aud" they expect.',
            '       Note this is not about your own CERN login: the token',
            f'       identifies "{claims.get("sub", "?")}", not you, so being',
            '       logged in on lxplus grants it nothing.',
        ]
    else:
        lines += [
            '       403 means the token was valid but this identity is not',
            '       allowed to read this. The target application needs to grant',
            f'       "{claims.get("sub", "?")}" a role.',
        ]
    return '\n'.join(lines)


def fetch(url, cfg, args):
    """Fetch `url` with a bearer token, retrying transient failures."""
    supplied = read_supplied_token(args)
    if supplied:
        claims = decode_claims(supplied)
        log(f'using supplied token for "{claims.get("sub", "?")}" '
            f'(audience "{claims.get("aud", "?")}")', args.verbose)
        try:
            return fetch_with_token(url, supplied, verify=not args.insecure,
                                    verbose=args.verbose)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SystemExit(
                    describe_refusal(exc, supplied, claims.get('aud', '?'),
                                     args.verbose))
            raise

    audience = audience_for(url, cfg, args.audience)
    if not audience:
        raise SystemExit(
            f'ERROR: no audience configured for {url}. Pass --audience, set '
            'CERN_API_AUDIENCE, or add the host to "audiences" in '
            f'{args.config}.')

    last_error = None
    for attempt in range(1, RETRIES + 1):
        try:
            # Only trust the cache on the first attempt; if the request failed
            # the cached token may be the reason.
            token = get_token(cfg, audience,
                              use_cache=(attempt == 1 and not args.no_cache),
                              verbose=args.verbose)
            return fetch_with_token(url, token, verify=not args.insecure,
                                    verbose=args.verbose)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SystemExit(describe_refusal(exc, token, audience,
                                                  args.verbose))
            last_error = exc
        except urllib.error.URLError as exc:
            last_error = exc

        if attempt < RETRIES:
            delay = 2 ** attempt
            log(f'attempt {attempt} failed ({last_error}); retrying in {delay}s')
            time.sleep(delay)

    raise SystemExit(f'ERROR: could not fetch {url}: {last_error}')


# ---------------------------------------------------------------- output ----

def write_output(body, outfile, expect_json):
    if expect_json:
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f'ERROR: the response is not valid JSON ({exc}). First 300 '
                f'characters:\n{body[:300]}')

    if not outfile:
        sys.stdout.write(body)
        return

    # Write via a temporary file so a failed run cannot truncate a good file.
    tmp = f'{outfile}.tmp'
    with open(tmp, 'w') as handle:
        handle.write(body)
    os.replace(tmp, outfile)


def check_credentials(cfg, args):
    """Request a token and print its claims, without calling any API."""
    audience = args.audience or os.environ.get('CERN_API_AUDIENCE')
    if not audience:
        audiences = sorted(set(cfg['audiences'].values()))
        if len(audiences) != 1:
            raise SystemExit(
                'ERROR: --check needs an audience: pass --audience <client-id> '
                f'(configured audiences: {audiences or "none"}).')
        audience = audiences[0]

    token = get_token(cfg, audience, use_cache=False, verbose=True)
    claims = decode_claims(token)
    print(f'OK: got a token for audience "{audience}"')
    print(f'  subject:   {claims.get("sub")}')
    print(f'  audience:  {claims.get("aud")}')
    print(f'  issuer:    {claims.get("iss")}')
    if claims.get('exp'):
        print(f'  valid for: {int(claims["exp"] - time.time())} s')
    for key in ('cern_roles', 'roles', 'resource_access'):
        if key in claims:
            print(f'  {key}: {json.dumps(claims[key])}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Fetch data from a CERN API using an OIDC access token.')
    parser.add_argument('url', nargs='?', help='the URL to fetch')
    parser.add_argument('-o', '--outfile',
                        help='write here instead of stdout (written atomically)')
    parser.add_argument('--audience',
                        help='Client ID of the target application')
    parser.add_argument('--client-id', help='our own OIDC client id')
    parser.add_argument('--config', default=DEFAULT_CONFIG_FILE,
                        help=f'credentials file (default: {DEFAULT_CONFIG_FILE})')
    parser.add_argument('--expect-json', action='store_true',
                        help='fail if the response does not parse as JSON')
    parser.add_argument('--token',
                        help='use this token instead of requesting one')
    parser.add_argument('--token-file',
                        help='read the token from this file, e.g. the output '
                             'of "auth-get-user-token -o token.txt"')
    parser.add_argument('--no-cache', action='store_true',
                        help='ignore any cached token and request a fresh one')
    parser.add_argument('--check', action='store_true',
                        help='request a token, print its claims and exit')
    parser.add_argument('--insecure', action='store_true',
                        help='do not verify TLS certificates')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.client_id:
        cfg['client_id'] = args.client_id

    if args.check:
        return check_credentials(cfg, args)
    if not args.url:
        parser.error('a URL is required (or use --check)')

    write_output(fetch(args.url, cfg, args), args.outfile, args.expect_json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
