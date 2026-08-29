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
        "icms.cern.ch": "the-target-api-client-id"
    }
}
```

`CERN_CLIENT_ID`, `CERN_CLIENT_SECRET` and `CERN_API_AUDIENCE` work as environment overrides if that suits the cron setup better.

### Checking that it works

```bash
python3 getTokenDB.py --check --audience the-target-api-client-id
```

This requests a token and prints its claims (subject, audience, lifetime) without calling any API, which separates "my credentials are wrong" from "the API will not accept me".

### Fetching data

```bash
python3 getTokenDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true' \
    -o tenures_raw.json --expect-json
```

Tokens are cached in `.cms_info_token_cache.json` (mode 600) and reused until they expire, so a run that fetches several URLs only asks for one token.

Claims are fixed when a token is issued, so a permission that was just granted - an e-group membership, a new role - does not appear in a token obtained before it. After any access change, pass `--no-cache` once to get a fresh one. Group changes can also take a few minutes to propagate.

### Testing with a personal token instead

`getTokenDB.py` authenticates as a service account. To check whether an endpoint accepts bearer tokens *at all*, it can be handy to try with a token belonging to a real person, obtained through the device grant with the [CERN command line tools](https://auth.docs.cern.ch/applications/command-line-tools/):

```bash
auth-get-user-token -c <a-public-client> -a <target-audience> -o /tmp/token.txt
python3 getTokenDB.py 'https://...' --token-file /tmp/token.txt -v
```

That flow needs a human to log in through a browser and the token lasts about 20 minutes, so it is a diagnostic rather than something for the cron job. If a URL works with a personal token but not with the service account, the endpoint does accept tokens and the problem is that `service-account-cms-info-scraper` lacks permissions.

### The Glance (cmsfence.cern.ch) endpoints

The iCMS `tools-api` endpoints are being replaced by Glance APIs on `cmsfence.cern.ch`, which take an OIDC access token as a Bearer token. The audience for all of them is `glance-api-access-client`, and `cms-info-scraper` is in the matching e-group.

| old iCMS endpoint | replacement | state |
| --- | --- | --- |
| `tools-api/restplus/org_chart/tenures` | `cmsfence.cern.ch/membership/api/appointments/search` | reachable, but refuses our tokens - it validates by introspection, see below |
| `tools-api/restplus/org_chart/job_openings` | `cmsfence.cern.ch/incubator/api/job_openings` | not yet - Glance still has configuration and development work to finish |
| `tools-api/restplus/cadi/xeb_report` | not yet announced | - |

The appointments search takes its filter as a url-encoded `queryString` parameter, which is what `-d/--param` is for:

```bash
python3 getTokenDB.py 'https://cmsfence.cern.ch/membership/api/appointments/search' \
    -d 'queryString="startDate" <= "2026-12-31" AND "endDate" >= "2026-01-01"' \
    -o tenures_raw.json --expect-json
```

Until an endpoint is ready, its `getDB.py` line in `getDBs.sh` stays as it is.

Note that the replacements do not return the same fields as the endpoints they replace, so `cleanup.py` needs adjusting for each one as it is switched over. The appointments records are shaped quite differently from the old tenures records - `categoryName` and `memberName` rather than `domain`, `position_level` and `src_unit_type` - and the job openings records rename `status` to `job_open_position_status`.

### Reading a refusal from these APIs

Read the status code together with the `WWW-Authenticate` header, which is where `mod_auth_openidc` states its reason (the HTML body says nothing useful). `getTokenDB.py` prints it, and `-v` dumps every response header:

* `401` **with** a challenge header - token validation failed, usually a wrong audience.
* `403` - the token was accepted but this identity may not read the resource, so it needs a role.
* `401` with a **JSON body** - the Glance application itself turned the token down, and the body says why. `X-Powered-By: PHP`, `Content-Type: application/json` and `Vary: Authorization` mark this case: the endpoint reads tokens fine, so the complaint is about this particular token.
* `"Authentication token introspection failed"` in that body - Glance validates tokens by introspecting them against the SSO rather than by checking their signature, and that call comes back negative. This is the membership API's current state, and the cause has been pinned down:

  ```bash
  python3 getTokenDB.py --check --audience glance-api-access-client --introspect
  ```

  **CERN's api-access tokens do not introspect as active.** A token freshly issued by `https://auth.cern.ch/auth/realms/cern/api-access/token`, with 20 minutes of validity left and addressed to the very client asking about it, comes back `{"active": false}`. The introspection request itself returns HTTP 200 rather than `401 invalid_client`, so the client is authenticated at that endpoint and the answer is genuinely about the token. Those tokens carry `refresh_expires_in: 0` and no lasting session for an introspection lookup to find.

  Watch for a confound when reading this: the SSO only introspects a token for a client named in that token's `aud`, and answers `active: false` to anybody else, so asking as `cms-info-scraper` about a token for `glance-api-access-client` is false whatever the token's state. `--introspect` handles that by also introspecting a token addressed to us, and reports which audience that control actually received.

  The consequence is that an API validating these tokens by introspection can never accept them, however the caller behaves. CERN's [Securing APIs](https://auth.docs.cern.ch/user-documentation/oidc/securing-apis/) guide accordingly tells API owners to verify the signature against `https://auth.cern.ch/auth/realms/cern/protocol/openid-connect/certs` and check the `aud` claim, and does not mention introspection. Resolving this needs the API to validate by signature, or a different way of obtaining a token that is introspectable.

## Keeping the client secret safe

The secret is the only thing standing between anyone and a token for our service account, so it lives in `cms_info_sso.json` with mode 600, ignored by git. If it is ever pasted into a terminal that is shared or logged, into a ticket, or into a chat, regenerate it in the Application Portal and update that file - a leaked secret cannot be un-leaked, and rotating it is quick.
