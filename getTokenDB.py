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
    python3 getTokenDB.py <url> -d 'queryString="startDate" <= "2026-12-31"'
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


def audience_for(url, cfg, override=None, with_source=False):
    """The target application to request a token for, or None.

    Also reports where the value came from. A stale audience in the config
    file silently overrides the built-in one for that host, which is hard to
    spot when the only symptom is a 401 from the API.
    """
    host = urllib.parse.urlparse(url).netloc.split(':')[0]
    if override:
        audience, source = override, '--audience'
    elif os.environ.get('CERN_API_AUDIENCE'):
        audience, source = os.environ['CERN_API_AUDIENCE'], 'CERN_API_AUDIENCE'
    else:
        audience = cfg['audiences'].get(host)
        source = ('the audiences map' if audience == AUDIENCES.get(host)
                  else 'the config file')
    return (audience, source) if with_source else audience


# ------------------------------------------------------------- tokens -------

def token_endpoint(auth_server=AUTH_SERVER, realm=REALM):
    return f'https://{auth_server}/auth/realms/{realm}/api-access/token'


def introspection_endpoint(auth_server=AUTH_SERVER, realm=REALM):
    return (f'https://{auth_server}/auth/realms/{realm}'
            '/protocol/openid-connect/token/introspect')


def introspect(cfg, token, auth_server=AUTH_SERVER, realm=REALM):
    """Ask the SSO whether a token is active (RFC 7662).

    Some APIs, Glance among them, validate a token by introspecting it rather
    than by checking its signature. When such an API reports that
    introspection failed, this says whether the SSO itself considers the token
    active: if it does, the token is sound and the problem is on the API's
    side of the introspection call.
    """
    if not cfg.get('client_secret'):
        raise SystemExit('ERROR: introspection needs the client secret.')

    data = urllib.parse.urlencode({
        'client_id': cfg['client_id'],
        'client_secret': cfg['client_secret'],
        'token': token,
    }).encode()
    request = urllib.request.Request(
        introspection_endpoint(auth_server, realm), data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')[:300]
        raise SystemExit(f'ERROR: introspection request failed '
                         f'({exc.code} {exc.reason}): {body}')


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


def cached_token_for(audience, cache_file=TOKEN_CACHE_FILE):
    """The cached token for an audience, expired or not, for diagnosis."""
    try:
        with open(os.path.expanduser(cache_file)) as handle:
            return json.load(handle).get(audience, {}).get('access_token')
    except (OSError, json.JSONDecodeError):
        return None


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
    if getattr(args, 'cached_token', False):
        audience = args.audience or os.environ.get('CERN_API_AUDIENCE')
        if not audience:
            raise SystemExit('ERROR: --cached-token needs --audience.')
        token = cached_token_for(audience)
        if not token:
            raise SystemExit(f'ERROR: no cached token for "{audience}".')
        return token
    return None


def describe_refusal(exc, token, audience, verbose=False):
    """Explain a 401/403 from the API.

    Which layer answered matters, and the headers give it away. A web server
    rejecting a token challenges with WWW-Authenticate and serves its own HTML
    error page. An application answering for itself typically sends JSON, and
    says why in the body - so print the body, which is the most direct
    statement of the problem available.
    """
    claims = decode_claims(token)
    challenge = exc.headers.get('WWW-Authenticate') if exc.headers else None
    content_type = exc.headers.get('Content-Type', '') if exc.headers else ''
    try:
        body = exc.read().decode('utf-8', 'replace').strip()
    except Exception:
        body = ''

    lines = [f'ERROR: the API refused the token ({exc.code} {exc.reason}).']
    if challenge:
        lines.append(f'       server said: {challenge}')
    if body:
        for line in body[:500].splitlines():
            lines.append(f'       {line}')
    lines.append(f'       token sent: sub="{claims.get("sub", "?")}" '
                 f'aud="{claims.get("aud", "?")}"')

    if verbose and exc.headers:
        lines.append('       response headers:')
        lines += [f'         {k}: {v}' for k, v in exc.headers.items()]

    from_application = 'json' in content_type.lower()
    if exc.code == 403:
        lines += [
            '       403 means the token was valid but this identity is not',
            '       allowed to read this. The target application needs to grant',
            f'       "{claims.get("sub", "?")}" a role.',
        ]
    elif from_application or challenge:
        lines += [
            '       The endpoint did look at the token and turned it down, so',
            f'       check the audience first: this asked for "{audience}".',
            '       Confirm it is the application that owns this API, and that',
            '       no stale value in the config file or CERN_API_AUDIENCE is',
            '       overriding it - run with -v to see which one was used and',
            '       where it came from.',
        ]
    else:
        lines += [
            '       401 with no challenge header and no JSON body suggests the',
            '       endpoint is not accepting bearer tokens at all rather than',
            '       rejecting this one, in which case no audience will work',
            '       until its owners finish configuring it.',
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

    audience, source = audience_for(url, cfg, args.audience, with_source=True)
    if audience:
        log(f'audience "{audience}" (from {source})', args.verbose)
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

def add_params(url, params):
    """Append `key=value` pairs to a URL, url-encoding the values.

    This mirrors `curl -G --data-urlencode`, which is how the Glance
    membership API is documented: its queryString parameter carries spaces,
    quotes and comparison operators that must not reach the server raw.
    """
    if not params:
        return url
    pairs = []
    for param in params:
        if '=' not in param:
            raise SystemExit(f'ERROR: --param needs key=value, got "{param}"')
        key, value = param.split('=', 1)
        pairs.append((key, value))
    separator = '&' if urllib.parse.urlparse(url).query else '?'
    return url + separator + urllib.parse.urlencode(pairs)


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
    """Print a token's claims, without calling any API.

    Requests a fresh token by default, which is what proves the client id and
    secret still work. Pass --token/--token-file to examine a specific token
    instead - for instance the cached one that an API has just rejected, so
    that what gets introspected is exactly what the API saw.
    """
    supplied = read_supplied_token(args)
    if supplied:
        claims = decode_claims(supplied)
        print(f'examining the supplied token (audience "{claims.get("aud")}")')
        return report_token(cfg, supplied, claims.get('aud'), args)

    audience = args.audience or os.environ.get('CERN_API_AUDIENCE')
    if not audience:
        audiences = sorted(set(cfg['audiences'].values()))
        if len(audiences) != 1:
            raise SystemExit(
                'ERROR: --check needs an audience: pass --audience <client-id> '
                f'(configured audiences: {audiences or "none"}).')
        audience = audiences[0]

    token = get_token(cfg, audience, use_cache=False, verbose=True)
    print(f'OK: got a token for audience "{audience}"')
    return report_token(cfg, token, audience, args)


def report_token(cfg, token, audience, args):
    """Print a token's claims, and optionally what the SSO makes of it."""
    claims = decode_claims(token)
    print(f'  subject:   {claims.get("sub")}')
    print(f'  audience:  {claims.get("aud")}')
    print(f'  issuer:    {claims.get("iss")}')
    if claims.get('exp'):
        print(f'  valid for: {int(claims["exp"] - time.time())} s')
    for key in ('cern_roles', 'roles', 'resource_access'):
        if key in claims:
            print(f'  {key}: {json.dumps(claims[key])}')

    if args.introspect:
        result = introspect(cfg, token)
        active = result.get('active')
        print(f'\nintrospection: active={active}')
        if active:
            print('  The SSO considers this token valid. An API that still '
                  'reports\n  "introspection failed" is failing on its own '
                  'side of that call,\n  which is for its owners to look at.')
            for key in ('aud', 'sub', 'client_id', 'scope', 'exp'):
                if key in result:
                    print(f'  {key}: {json.dumps(result[key])}')
        else:
            print('  The SSO does not consider this token active, which is '
                  'what an API\n  introspecting it would see. Full response:')
            print(f'  {json.dumps(result)}')
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
    parser.add_argument('-d', '--param', action='append', metavar='KEY=VALUE',
                        help='query parameter, url-encoded like curl\'s '
                             '--data-urlencode; repeatable')
    parser.add_argument('--no-cache', action='store_true',
                        help='ignore any cached token and request a fresh one')
    parser.add_argument('--check', action='store_true',
                        help='request a token, print its claims and exit')
    parser.add_argument('--cached-token', action='store_true',
                        help='use the token already in the cache for this '
                             'audience, rather than requesting a new one')
    parser.add_argument('--introspect', action='store_true',
                        help='with --check, also ask the SSO whether the '
                             'token is active (RFC 7662)')
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

    url = add_params(args.url, args.param)
    write_output(fetch(url, cfg, args), args.outfile, args.expect_json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
