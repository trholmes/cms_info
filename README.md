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

### Note on cmsfence.cern.ch

`https://cmsfence.cern.ch/incubator/api/...` is served by Apache `mod_auth_openidc` configured for browser login sessions (SSO client `vocms0705`), not as an OAuth2 resource server. Probing it shows that a request carrying `Authorization: Bearer <token>` is redirected to the interactive login page exactly like an anonymous one, with no `WWW-Authenticate` header — so bearer tokens are currently ignored there and `getDB.py` (cookie + Kerberos) is the way to read it. For it to accept tokens, its owners need to enable token validation on that path and grant `service-account-cms-info-scraper` a role.

`-o` writes the file atomically and `--expect-json` refuses to save a response that is not valid JSON, so a failed authentication leaves the previous good .json in place instead of overwriting it with an SSO login page.
