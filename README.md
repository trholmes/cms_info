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
./getTokenDB.py --check --audience the-target-api-client-id
```

This requests a token and prints its claims (subject, audience, lifetime) without calling any API, which separates "my credentials are wrong" from "the API will not accept me".

### Fetching data

```bash
./getTokenDB.py 'https://icms.cern.ch/tools-api/restplus/org_chart/tenures?exclude_past=true' \
    -o tenures_raw.json --expect-json
```

Tokens are cached in `.cms_info_token_cache.json` (mode 600) and reused until they expire, so a run that fetches several URLs only asks for one token.

### Testing with a personal token instead

`getTokenDB.py` authenticates as a service account. To check whether an endpoint accepts bearer tokens *at all*, it can be handy to try with a token belonging to a real person, obtained through the device grant with the [CERN command line tools](https://auth.docs.cern.ch/applications/command-line-tools/):

```bash
auth-get-user-token -c <a-public-client> -a <target-audience> -o /tmp/token.txt
./getTokenDB.py 'https://...' --token-file /tmp/token.txt -v
```

That flow needs a human to log in through a browser and the token lasts about 20 minutes, so it is a diagnostic rather than something for the cron job. If a URL works with a personal token but not with the service account, the endpoint does accept tokens and the problem is that `service-account-cms-info-scraper` lacks permissions.

### Note on cmsfence.cern.ch

`https://cmsfence.cern.ch/incubator/api/...` is served by Apache `mod_auth_openidc`, and from inside the CERN network it does read bearer tokens: a request carrying one gets a `401` where an anonymous request gets redirected to the interactive login. (Probing from outside CERN is misleading - everything is redirected there regardless.)

The audience is `glance-api-access-client`, which is the application `cms-info-scraper` was granted access to. That grant is what makes it the right value: CERN permissions are given per target application, so the application we were let into is the one we can usefully ask tokens for. Reading a client id off the browser login redirect, as an earlier version of this file did, finds the client the *site* uses to log people in, which is a different setting and was refused with a `401`.

When the API refuses a token, read the status code together with the `WWW-Authenticate` header, which is where `mod_auth_openidc` states its actual reason (the HTML body says nothing useful). `getTokenDB.py` prints it, and with `-v` dumps every response header:

* `401` **with** a challenge header - token validation failed, usually a wrong audience. Nothing to do with roles.
* `403` - the token was accepted but this identity may not read the resource, so the target application needs to grant `service-account-cms-info-scraper` a role.
* `401` **without** a challenge header - the module challenges whenever it rejects a token itself, so a bare 401 suggests the refusal comes from the application behind Apache. The web server was satisfied with the token; the application does not recognise the identity in it.

The last of these is what `cmsfence.cern.ch` currently returns, with a token whose `aud` is `glance-api-access-client` and whose `resource_access` shows a role on that same client - so the audience and the grant are both in order. The likely reading is that Glance resolves the caller to a person and has nothing to resolve `service-account-cms-info-scraper` to. Trying the same URL with a personal token (see above) distinguishes that from an audience problem: if a personal token works, the service account needs standing inside Glance itself, which only its owners can give it.

Remember that the token identifies `service-account-cms-info-scraper`, not the person running the script. Being logged in on lxplus, or having access to the site in a browser, grants the token nothing. To read an endpoint with your own rights instead, use `getDB.py` (Kerberos cookie) or a personal token as described above.

## Keeping the client secret safe

The secret is the only thing standing between anyone and a token for our service account, so it lives in `cms_info_sso.json` with mode 600, ignored by git. If it is ever pasted into a terminal that is shared or logged, into a ticket, or into a chat, regenerate it in the Application Portal and update that file - a leaked secret cannot be un-leaked, and rotating it is quick.
