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

* **The `audience` is not our client.** It is the Client ID of the application that *owns* the API being called (e.g. the iCMS tools API), and it has to be looked up per API. Get it wrong and the token is issued but rejected.
* **The token identifies a service account, not a person.** Its `sub` claim is `service-account-cms-info-scraper`. The target application must have granted that account access: its owners create a role, map it to a group, and our client subscribes to that group. A token that the API refuses with 401/403 usually means this step is missing, not that the credentials are wrong.

### Setup

Put the client secret in a file only the running account can read — never in this repository:

```bash
touch ~/private/cms_info_sso.json
chmod 600 ~/private/cms_info_sso.json
```

```json
{
    "client_id": "cms-info-scraper",
    "client_secret": "the-secret-from-the-application-portal",
    "audiences": {
        "icms.cern.ch": "the-target-api-client-id"
    }
}
```

`CERN_CLIENT_ID`, `CERN_CLIENT_SECRET` and `CERN_API_AUDIENCE` work as environment overrides if that suits the cron setup better.

### Checking that it works

```bash
./getTokenDB.py --check --audience the-target-api-client-id
```

This requests a token and prints its claims (subject, audience, lifetime) without calling any API, which separates "my credentials are wrong" from "the API will not accept me".

### Fetching data

```bash
./getTokenDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true' \
    -o tenures_raw.json --expect-json
```

Tokens are cached in `~/private/.cms_info_token_cache.json` (mode 600) and reused until they expire, so a run that fetches several URLs only asks for one token.

### Testing with a personal token instead

`getTokenDB.py` authenticates as a service account. To check whether an endpoint accepts bearer tokens *at all*, it can be handy to try with a token belonging to a real person, obtained through the device grant with the [CERN command line tools](https://auth.docs.cern.ch/applications/command-line-tools/):

```bash
auth-get-user-token -c <a-public-client> -a <target-audience> -o /tmp/token.txt
./getTokenDB.py 'https://...' --token-file /tmp/token.txt -v
```

That flow needs a human to log in through a browser and the token lasts about 20 minutes, so it is a diagnostic rather than something for the cron job. If a URL works with a personal token but not with the service account, the endpoint does accept tokens and the problem is that `service-account-cms-info-scraper` lacks permissions.

### Note on cmsfence.cern.ch

`https://cmsfence.cern.ch/incubator/api/...` is served by Apache `mod_auth_openidc`. From inside the CERN network it does read bearer tokens: a request with a token gets a `401` rather than the redirect to the interactive login that an anonymous one gets. (Probing from outside CERN is misleading, as everything is redirected to the login page there regardless.)

A `401` means the token was not accepted, which points at the audience rather than at permissions - `vocms0705` is the client the host uses for browser logins, and the API may validate a different Client ID. A `403` would be the permissions case.

Remember that the token identifies `service-account-cms-info-scraper`, not the person running the script. Being logged in on lxplus, or having access to the site in a browser, grants the token nothing. To read the endpoint with your own rights instead, use `getDB.py` (Kerberos cookie) or a personal token as described above.
