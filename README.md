# cms_info
Scripts for maintaining the content on the cms_info site.

A cron job runs `getDBs.sh`, which calls all the other scripts. `getDB.py`, `getOldDB.py` and `getTokenDB.py` handle authentication to scrape data from CMS databases, depending on which SSO implementation the target uses. `getCalendar.py` reads and parses the CMS .ical file. All of these produce .json files which are filtered by `cleanup.py` into the final forms used in the website.

Actual scripts are run from this directory: `/afs/cern.ch/user/c/cmswww/cms_info`.

## Which fetch script to use

| script | authentication | use for |
| --- | --- | --- |
| `getOldDB.py` | `cern-get-sso-cookie` (old SSO) | anything still on the old SSO |
| `getDB.py` | `auth-get-sso-cookie` + Kerberos (session cookie) | web pages that only accept an SSO login session, e.g. the CINCO conference list |
| `getTokenDB.py` | OIDC API access token (client credentials) | APIs that accept `Authorization: Bearer <token>` |

## getTokenDB.py: OIDC API access

This follows [CERN's API access documentation](https://auth.docs.cern.ch/user-documentation/oidc/api-access/). Rather than logging in as a person with Kerberos, the script authenticates as a registered OIDC client (`cms-info-scraper`) and sends a bearer token to the API:

1. POST a client credentials grant to `https://auth.cern.ch/auth/realms/cern/api-access/token`, with our `client_id`, `client_secret`, and an `audience` naming the target application.
2. Send the returned access token to the API as `Authorization: Bearer <token>`.

Because no Kerberos ticket is involved, this does not depend on a valid TGT in the cron environment.

### Two things to know

* **The `audience` is the API's own Client ID.** Not ours, and - the subtle part - not the application whose e-group grants us access either. `cms-info-scraper` is a member of `glance-api-access-client`, which is what *permits* the call, but a token addressed to that is refused; the membership API wants `cms-membership-api-prod`. Permission and audience are separate things, and the audience has to be asked of each API's owners. A token for the wrong audience is issued quite happily and then rejected.
* **The token identifies a service account, not a person.** Its `sub` claim is `service-account-cms-info-scraper`. The target application must have granted that account access: its owners create a role, map it to a group, and our client subscribes to that group. A token that the API refuses with 401/403 usually means this step is missing, not that the credentials are wrong.

### Setup

Put the client secret in a file only the running account can read:

```bash
touch cms_info_sso.json
chmod 600 cms_info_sso.json
```

That file sits in the working directory, which is this git repository, so both it and the token cache are listed in `.gitignore`. Check they are still ignored before committing.

```json
{
    "client_id": "cms-info-scraper",
    "client_secret": "the-secret-from-the-application-portal",
    "audiences": {
        "cmsfence.cern.ch/membership/": "cms-membership-api-prod"
    }
}
```

`CERN_CLIENT_ID`, `CERN_CLIENT_SECRET` and `CERN_API_AUDIENCE` work as environment overrides if that suits the cron setup better.

### Checking that it works

```bash
python3 getTokenDB.py --check --audience cms-membership-api-prod
```

This requests a token and prints its claims (subject, audience, lifetime) without calling any API, which separates "my credentials are wrong" from "the API will not accept me".

### Fetching data

```bash
python3 getTokenDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true' \
    -o tenures_raw.json --expect-json
```

Tokens are cached in `.cms_info_token_cache.json` (mode 600) and reused until they expire, so a run that fetches several URLs only asks for one token.

Claims are fixed when a token is issued, so a permission that was just granted - an e-group membership, a new role - does not appear in a token obtained before it. After any access change, pass `--no-cache` once to get a fresh one. Group changes can also take a few minutes to propagate.

### Hand-testing with curl

To try a call by hand, capture the token into a shell variable rather than pasting it:

```bash
TOKEN=$(python3 getTokenDB.py --print-token --audience cms-membership-api-prod)

curl -G 'https://cmsfence.cern.ch/membership/api/appointments/search' \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Accept: application/json' \
    --data-urlencode 'queryString="startDate" <= "2026-12-31" AND "endDate" >= "2026-01-01"'
```

`--print-token` writes only the token to stdout, so `$( )` captures it cleanly. Use double quotes around `Bearer $TOKEN` or the shell will not expand it. A token is a credential for its 20 minutes: keep it in the variable rather than pasting it into tickets or mail.

### Testing with a personal token instead

`getTokenDB.py` authenticates as a service account. To check whether an endpoint accepts bearer tokens *at all*, it can be handy to try with a token belonging to a real person, obtained through the device grant with the [CERN command line tools](https://auth.docs.cern.ch/applications/command-line-tools/):

```bash
auth-get-user-token -c <a-public-client> -a <target-audience> -o /tmp/token.txt
python3 getTokenDB.py 'https://...' --token-file /tmp/token.txt -v
```

That flow needs a human to log in through a browser and the token lasts about 20 minutes, so it is a diagnostic rather than something for the cron job. If a URL works with a personal token but not with the service account, the endpoint does accept tokens and the problem is that `service-account-cms-info-scraper` lacks permissions.

### The Glance (cmsfence.cern.ch) endpoints

The iCMS `tools-api` endpoints are being replaced by Glance APIs on `cmsfence.cern.ch`, which take an OIDC access token as a Bearer token.

| old iCMS endpoint | replacement | audience | state |
| --- | --- | --- | --- |
| `tools-api/restplus/org_chart/tenures` | `cmsfence.cern.ch/membership/api/appointments/search` | `cms-membership-api-prod` | working |
| `tools-api/restplus/org_chart/job_openings` | `cmsfence.cern.ch/incubator/api/job_openings` | not known yet | Glance still has configuration and development work to finish |
| `tools-api/restplus/cadi/xeb_report` | not yet announced | - | - |

Each API has its own audience, so the `audiences` map is keyed by host **and path prefix**, longest match first. Ask Glance for the audience of each endpoint as it becomes available - it is not discoverable from the outside, and a wrong one produces a token that is issued and then refused.

The appointments search takes its filter as a url-encoded `queryString` parameter, which is what `-d/--param` is for:

```bash
python3 getTokenDB.py 'https://cmsfence.cern.ch/membership/api/appointments/search' \
    -d 'queryString="startDate" <= "2026-12-31" AND "endDate" >= "2026-01-01"' \
    -o tenures_raw.json --expect-json
```

Until an endpoint is ready, its `getDB.py` line in `getDBs.sh` stays as it is. The replacements return different fields from the endpoints they replace, so `cleanup.py` needs adjusting for each one as it is switched over: the appointments records carry `categoryName`, `memberName` and `startDateString` rather than `domain`, `position_level` and `src_unit_type`, and the job openings records rename `status` to `job_open_position_status`.

### Finding out what else is available

`probeGlance.py` tries a list of candidate Glance URLs and reports which answer, which refuse us and which do not exist. It is a migration aid rather than part of the nightly run, useful for checking what Glance has switched on as they work through the remaining endpoints:

```bash
python3 probeGlance.py                  # the built-in candidate list
python3 probeGlance.py URL [URL ...]    # specific URLs
```

What it has found on the membership API so far, all on the `cms-membership-api-prod` audience:

| endpoint | notes |
| --- | --- |
| `appointments/search` | the tenures replacement |
| `members/search` | people |
| `institutes/search` | institutes |
| `docs` | answers 200 - read it for the real endpoint list |

`<resource>/search` is the convention, and responses are **wrapped**: `{"results": [...], "numberOfResults": N}` rather than the bare array the old iCMS endpoints returned. `cleanup.py` reads the top level directly, so anything switched over needs `db["results"]` as well as the field renames. `/membership/api/` itself answers 500, and `appointments`, `categories` and `working-groups` without `/search` are 404, so the search form is the way in.

To read one by hand:

```bash
python3 getTokenDB.py 'https://cmsfence.cern.ch/membership/api/docs' | head -60
```

It never guesses an audience: a path with none configured is reported as such. Audience names are not guessable, and the ones that look obvious are not registered - checking `cms-incubator-api-prod`, `cms-cadi-api-prod`, `cms-icms-api-prod`, `cms-conferences-api-prod` and `cms-orgchart-api-prod` against the SSO found none of them to exist, while `cms-membership-api-prod` and a `cms-membership-api-dev` twin do. So each audience has to be asked for as its endpoint appears.

Whether a Client ID exists at all can be checked without any credentials, which saves asking about a typo:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  'https://auth.cern.ch/auth/realms/cern/protocol/openid-connect/auth?response_type=code&scope=openid&client_id=SOME-CLIENT&redirect_uri=https%3A%2F%2Fexample.cern.ch%2Fcb'
```

`400` with `Client not found` in the body means no such application; a login page means it exists.

### Reading a refusal from these APIs

`getTokenDB.py` prints the `WWW-Authenticate` header and the response body, and `-v` dumps every response header and reports which audience was used and where it came from.

* `401 {"detail":"Authentication token introspection failed."}` - **the audience is wrong.** The API introspects the token as itself, and the SSO only introspects a token for a client named in its audience, so a token addressed elsewhere fails that check no matter how valid it is. This is the error a wrong audience produces here, and it took a while to recognise: it says nothing about credentials, e-groups or roles.
* `401` with a challenge header - the web server rejected the token, again usually the audience.
* `403` - the token was accepted but this identity may not read the resource, so it needs a role.
* `401` with no challenge header and no JSON body - the endpoint is not accepting bearer tokens at all, which is what `/incubator/api/` returns while unfinished.

Introspecting from the calling side (`--check --introspect`) is a weak test for the same reason: as `cms-info-scraper` we can only introspect tokens addressed to `cms-info-scraper`, so a `false` result is expected and means little.

Note also that the token identifies `service-account-cms-info-scraper`, not the person running the script, so being logged in on lxplus grants it nothing.

## Keeping the client secret safe

The secret is the only thing standing between anyone and a token for our service account, so it lives in `cms_info_sso.json` with mode 600, ignored by git. If it is ever pasted into a terminal that is shared or logged, into a ticket, or into a chat, regenerate it in the Application Portal and update that file - a leaked secret cannot be un-leaked, and rotating it is quick.
