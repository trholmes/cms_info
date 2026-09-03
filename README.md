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
* **The token identifies a service account, not a person.** Its `sub` claim is `service-account-cms-info-scraper`, so being logged in on lxplus grants it nothing. The target application must have granted that account access - its owners map a role to an e-group our client belongs to. When an API refuses a token, read the code carefully: a `403` is that missing permission, while a `401` is usually about the token rather than the identity - see below.

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
    "client_secret": "the-secret-from-the-application-portal"
}
```

The secret is all this file needs. It also accepts an `audiences` block, but do not put one there for a host the script already knows: an entry in the file shadows the built-in map for that host, so a value that later turns out to be wrong keeps being used and the only symptom is a `401`. Use it for a host the script has no audience for yet, and prefer `--audience` for a one-off. `CERN_CLIENT_ID`, `CERN_CLIENT_SECRET` and `CERN_API_AUDIENCE` work as environment overrides if that suits the cron setup better - and `CERN_API_AUDIENCE` overrides every host at once, so keep it out of the cron environment.

### Checking that it works

```bash
python3 getTokenDB.py --check --audience cms-membership-api-prod
```

This requests a token and prints its claims (subject, audience, lifetime) without calling any API, which separates "my credentials are wrong" from "the API will not accept me".

### Fetching data

```bash
python3 getTokenDB.py 'https://cmsfence.cern.ch/alcm/api/analysis/xeb-report' \
    -d 'period=14' -o cadi_raw.json --expect-json
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

### The Glance (cmsfence.cern.ch) endpoints

The iCMS `tools-api` endpoints are being replaced by Glance APIs on `cmsfence.cern.ch`, which take an OIDC access token as a Bearer token.

| old iCMS endpoint | replacement | audience | state |
| --- | --- | --- | --- |
| `tools-api/restplus/org_chart/tenures` | `cmsfence.cern.ch/membership/api/appointments/search` | `cms-membership-api-prod` | **switched over** |
| `tools-api/restplus/org_chart/job_openings` | `cmsfence.cern.ch/incubator/api/job_openings` | not known yet | Glance still has configuration and development work to finish |
| `tools-api/restplus/cadi/xeb_report` | `cmsfence.cern.ch/alcm/api/analysis/xeb-report` | `cms-alcm-api-prod` | **switched over** |

Each API has its own audience, so the `audiences` map is keyed by host **and path prefix**, longest match first. Ask Glance for the audience of each endpoint as it becomes available - it is not discoverable from the outside, and a wrong one produces a token that is issued and then refused.

The appointments search takes its filter as a url-encoded `queryString` parameter, which is what `-d/--param` is for:

```bash
python3 getTokenDB.py 'https://cmsfence.cern.ch/membership/api/appointments/search' \
    -d 'queryString="startDate" <= "2026-12-31" AND "endDate" >= "2026-01-01"' \
    -o tenures_raw.json --expect-json
```

### How cleanup.py reads the appointments records

The appointments records describe the same appointments as the old tenures records but carry none of the fields the board pages were built from. The unit somebody was appointed to is only present as prose in `categoryName`, of the form `<position> of <unit> <unit type>`, e.g. `Chairperson of Collaboration Board` or `Coordinator of Physics Coordination Area`. `cleanup.py` parses that back into `position`, `domain` and `src_unit_type` with `parseCategoryName` and `appointmentToTenure`, and maps units to domains through an explicit `appointmentDomains` table rather than by matching on substrings - `Physics Performance & Datasets` would otherwise be swallowed by `Physics`.

Some pages also display `{inst_code}`, the institute's short code such as `GHENT` or `ROMA-1`. The appointments records name a member's institute and give its id but not that code, so `getDBs.sh` also fetches `institutes/search` into `institutes_raw.json` and `loadInstituteCodes` joins the two on the institute id. Which field holds the code is not documented, so it takes the first plausible one present in the records; if the institutes file is missing the pages fall back to showing the full institute name rather than nothing.

The page templates read `{position}`, `{cms_id}` and `{first_name} {last_name}` from each member, so `appointmentToTenure` fills those in: `cms_id` from `memberId`, and the names by splitting the single `memberName` the API returns. `splitMemberName` takes the first word as the first name and the rest as the surname, and handles a `"Surname, Forename"` spelling too.

Categories with no unit at all - `Team Leader`, `Country Representative`, `TRG working group convenor` - belong to no page and are left out of them. So are units that have no page, such as `Statistics Committee` and the subdetectors, funding agencies and institutes.

Two things the old endpoint provided are simply gone, and no parsing recovers them:

* **`ex_officio_rule_id`.** The Management and Executive Boards were largely composed of ex-officio members, resolved through `getPrimaryRole`. With no ex-officio information, nobody is grouped as an ex-officio member and those pages carry only what names them directly: the Management Board is left with its advisors, and the Executive Board with nothing at all. The International Committee likewise has no appointments in the new data.
* **`position_level`.** Ordering within a page now comes from `appointmentPositionLevels`, a table keyed on the parsed position - spokesperson, then chairs and coordinators, then deputies, then advisors, then members. It is a reasonable order rather than the one the database used to specify.

Also note the records include appointments that have expired, marked `status: "Inactive"`, which the old endpoint excluded; `cleanup.py` keeps only the active ones.

Each source is handled independently, so a dead endpoint no longer stops the whole script: a section that cannot rebuild its `.json` reports the reason and leaves the previous file in place. This matters while two of the four sources have no replacement - before, a missing nominations file stopped the run before tenures or the board pages were reached.

### The ALCM xeb-report records

The CADI XEB report moved to the ALCM API ([CMSGLANCE-422](https://its.cern.ch/jira/browse/CMSGLANCE-422)), on its own audience `cms-alcm-api-prod`. Two differences from the old endpoint, both handled in `cleanup.py`:

* The categories arrive wrapped as `{"period": N, "reports": {"CWR": [...], "SUB": [...], "ACCEPT": [...]}}`, so the `reports` object is unwrapped before use.
* Dates come as `2026-08-25` rather than `25/08/2026`. Both spellings are accepted and reformatted for display.

The query parameter is `period` in days, replacing the old `xeb_report_period`; `getDBs.sh` asks for 14 as before.

The records carry two fields beyond the schema in the ticket: `old_status` (the status an analysis moved from, e.g. `Ready for CWR`) and `cds_record`, the CDS record id, which gives a link target of `https://cds.cern.ch/record/<cds_record>`. There is no `url` field, which the old endpoint provided.

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
| `countries/search` | answers 500, so the route is real but wants parameters |
| `docs` | a Swagger UI page, pointing at the spec below |
| `Membership-API.v1.yaml` | the OpenAPI spec - the authoritative endpoint list |

Paging is by **`limit`**, which is the only parameter of `page`, `pageSize`, `limit`, `offset`, `rows` and `size` that has any effect - the others are silently ignored, so a request without `limit` quietly returns the first 50 of however many `numberOfResults` reports (1164 for a year of appointments). Any switched-over call needs an explicit `limit`, or it will fetch a fraction of the data and look like it worked.

Results include expired appointments: the date filter in `queryString` does not exclude them, and each record carries `status` of `Active` or `Inactive`. Filter on that.

`<resource>/search` is the convention, and responses are **wrapped**: `{"results": [...], "numberOfResults": N}` rather than the bare array the old iCMS endpoints returned. `cleanup.py` reads the top level directly, so anything switched over needs `db["results"]` as well as the field renames. `/membership/api/` itself answers 500, and `appointments`, `categories` and `working-groups` without `/search` are 404, so the search form is the way in.

A 404 means no such route, while a 500 means the route exists and the request
was incomplete - usually missing parameters - so those are worth a second look.

The spec is the thing to read rather than guessing at paths:

```bash
python3 getTokenDB.py 'https://cmsfence.cern.ch/membership/api/Membership-API.v1.yaml' \
    -o /tmp/membership-api.yaml
grep -nE '^  /|operationId:|summary:' /tmp/membership-api.yaml | head -80
```

Do not pass `--expect-json` there: the spec is YAML.

It never guesses an audience: a path with none configured is reported as such. The names are not guessable either - the obvious ones (`cms-incubator-api-prod`, `cms-cadi-api-prod`, `cms-icms-api-prod`) are not registered - so each has to be asked for as its endpoint appears.

### Reading a refusal from these APIs

`getTokenDB.py` prints the response body and the `WWW-Authenticate` header when a call is refused, and `-v` dumps every response header plus the audience it used and where that came from.

* `401 {"detail":"Authentication token introspection failed."}` - **the audience is wrong.** The API introspects the token as itself, and the SSO only introspects a token for a client named in that token's audience, so a token addressed anywhere else fails that check however valid it is. This is the error a wrong audience produces on these APIs, and it says nothing about credentials, e-groups or roles.
* `403` - the token was accepted but this identity may not read the resource, so it needs a role.
* `401` with no challenge header and no JSON body - the endpoint is not accepting bearer tokens yet, which is what an unfinished one returns. No change on the calling side helps.

An audience set in `cms_info_sso.json` silently overrides the built-in one for that host, and a stale value there is easy to miss when the only symptom is a 401, so `-v` names the source:

```
audience "cms-membership-api-prod" (from the audiences map)
```

Whether a Client ID exists at all can be checked without credentials, which saves asking about a typo:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  'https://auth.cern.ch/auth/realms/cern/protocol/openid-connect/auth?response_type=code&scope=openid&client_id=SOME-CLIENT&redirect_uri=https%3A%2F%2Fexample.cern.ch%2Fcb'
```

`400` with `Client not found` in the body means no such application; a login page means it exists.

### What is still missing

* **Job openings.** `/incubator/api/job_openings` is not in service - Glance are working on its authentication configuration - and its audience is not known. `nominations.json` keeps its last contents meanwhile.
* **Ex-officio membership.** The Management and Executive Board pages were built from the old endpoint's `ex_officio_rule_id`: those boards are composed largely of people who sit on them by virtue of another role. The appointments records carry no ex-officio information (no such field, and the only Management Board rows are its advisors), so the Management Board page shows only advisors and the Executive Board and International Committee pages are empty. Whether that composition is available elsewhere in Glance is an open question for its owners.
* **`position_level`.** Ordering within a page now comes from `appointmentPositionLevels` rather than from the database.

## Keeping the client secret safe

The secret is the only thing standing between anyone and a token for our service account, so it lives in `cms_info_sso.json` with mode 600, ignored by git. If it is ever pasted into a terminal that is shared or logged, into a ticket, or into a chat, regenerate it in the Application Portal and update that file - a leaked secret cannot be un-leaked, and rotating it is quick.
