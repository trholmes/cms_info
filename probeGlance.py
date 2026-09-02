#!/usr/bin/env python3
"""Probe Glance endpoints to see which ones we can read.

A migration aid, not part of the nightly run: as Glance replaces the old iCMS
tools-api endpoints one by one, this says which candidate URLs answer, which
refuse us, and which do not exist, so the switch-over can follow along. Delete
it once the migration is finished.

    python3 probeGlance.py                  # the built-in candidate list
    python3 probeGlance.py URL [URL ...]    # specific URLs
    python3 probeGlance.py --audience X ... # override the audience

Audiences come from getTokenDB.py's map, so an endpoint whose audience is not
known yet reports "no audience configured" rather than being guessed at. The
audience of a Glance API is its own Client ID and has to be asked for - the
names are not guessable, and a token for the wrong one is issued and then
refused.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import getTokenDB  # noqa: E402

# Candidates worth trying. The membership API is the one known to work, so its
# neighbours are the best guesses for the data the site still reads from iCMS.
CANDIDATES = [
    # tenures - this one is confirmed working
    ('tenures (known good)',
     'https://cmsfence.cern.ch/membership/api/appointments/search'),
    # is there anything self-describing to read?
    ('api root', 'https://cmsfence.cern.ch/membership/api/'),
    ('openapi', 'https://cmsfence.cern.ch/membership/api/openapi.json'),
    ('swagger', 'https://cmsfence.cern.ch/membership/api/swagger.json'),
    ('docs', 'https://cmsfence.cern.ch/membership/api/docs'),
    # other membership resources that might carry board/role structure
    ('appointments', 'https://cmsfence.cern.ch/membership/api/appointments'),
    ('categories', 'https://cmsfence.cern.ch/membership/api/categories'),
    ('categories/search',
     'https://cmsfence.cern.ch/membership/api/categories/search'),
    ('members/search',
     'https://cmsfence.cern.ch/membership/api/members/search'),
    ('institutes/search',
     'https://cmsfence.cern.ch/membership/api/institutes/search'),
    ('working-groups',
     'https://cmsfence.cern.ch/membership/api/working-groups'),
    # nominations, which Glance say is not in service yet
    ('job openings',
     'https://cmsfence.cern.ch/incubator/api/job_openings'),
]


def verdict(status, content_type, body):
    """A one-word reading of a response, plus a note."""
    if status == 200:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return 'HTML?', f'200 but not JSON ({content_type})'
        if isinstance(data, list):
            return 'WORKS', f'{len(data)} records'
        if isinstance(data, dict):
            keys = ', '.join(list(data)[:4])
            return 'WORKS', f'object, keys: {keys}'
        return 'WORKS', '200'
    if status == 404:
        return 'absent', 'no such endpoint'
    if status in (401, 403):
        try:
            errors = json.loads(body).get('errors', [])
            detail = errors[0].get('detail') or errors[0].get('title')
        except Exception:
            detail = None
        return 'refused', detail or f'{status}'
    if status in (301, 302, 303, 307, 308):
        return 'redirect', 'not token-aware, sends us to a login'
    return str(status), (body or '')[:60].replace('\n', ' ')


def probe(label, url, cfg, args):
    audience = getTokenDB.audience_for(url, cfg, args.audience)
    if not audience:
        return label, url, 'unknown', 'no audience configured for this path'
    try:
        token = getTokenDB.get_token(cfg, audience)
    except SystemExit as exc:
        return label, url, 'no token', str(exc).splitlines()[0]

    try:
        body = getTokenDB.fetch_with_token(url, token)
        return (label, url) + verdict(200, 'application/json', body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')
        return (label, url) + verdict(
            exc.code, exc.headers.get('Content-Type', ''), body)
    except urllib.error.URLError as exc:
        return label, url, 'error', str(exc.reason)[:60]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('urls', nargs='*', help='URLs to probe')
    parser.add_argument('--audience', help='use this audience for every URL')
    parser.add_argument('--config', default=getTokenDB.DEFAULT_CONFIG_FILE)
    args = parser.parse_args(argv)

    cfg = getTokenDB.load_config(args.config)
    targets = ([(u, u) for u in args.urls] if args.urls
               else [(l, u) for l, u in CANDIDATES])

    rows = []
    for label, url in targets:
        rows.append(probe(label, url, cfg, args))
        print('.', end='', file=sys.stderr, flush=True)
    print('', file=sys.stderr)

    width = max(len(r[0]) for r in rows)
    for label, url, state, note in rows:
        print(f'{label:<{width}}  {state:<9} {note}')
        print(f'{"":<{width}}  {urllib.parse.urlparse(url).path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
