# Directus prompt cache for LiveKit

This runbook describes the Directus-side setup for LiveKit prompt assembly.
Do not use an admin token in LiveKit Cloud.

## Service role

Create a Directus role named `Livekit`.

Grant read permissions to the collections used for prompt assembly:

- `CallerID`
- `bot_configurations`
- `clients`
- `clients_prompt`
- `webparsing`
- `transfer_number`
- `client_prompt_cache`

Additionally, grant `create` and `update` only on `client_prompt_cache`. This
lets the robot save the current assembled template after a cache miss. Do not
grant write permissions to source client collections. Do not grant delete.

It is normal for the `Livekit` service role to need new read fields as the robot
starts using new prompt inputs. Keep this explicit and least-privilege: add only
the collection/action/fields the runtime reads or writes, update this runbook,
and verify with the same service token that Cloud uses. Never put an admin token
in LiveKit Cloud just to avoid permission updates.

Recommended readable fields:

- `CallerID`: `CallerID`, `client_id`
- `bot_configurations`: `client_id`, `system_prompt`, `examples`, `skills_name`
- `clients`: `id`, `add_info`, `company_website`, `company_extra`, `first_step`
- `clients_prompt`: `name`, `text`
- `webparsing`: `url`, `text`
- `transfer_number`: `client_id`, `disc`, `direction`
- `client_prompt_cache` read: `id`, `caller_id`, `client_id`,
  `prompt_template`, `timezone`, `source_hash`, `active`, `last_error`,
  `date_updated`
- `client_prompt_cache` create/update: `caller_id`, `client_id`,
  `prompt_template`, `timezone`, `source_hash`, `active`, `last_error`,
  `date_updated`

Create a service user for the role and use a static token. Store the token in
LiveKit Cloud as `DIRECTUS_TOKEN`.

The current prompt permissions migration is:

```text
agents/main-bot/schema/directus_prompt_permissions.sql
```

Run it on the VPS Directus database after creating any missing business columns:

```bash
sudo -u postgres psql -d voicebot -f agents/main-bot/schema/directus_prompt_permissions.sql
```

This migration updates Directus role/policy metadata for `Livekit`. It does not
create business columns such as `clients.first_step`; those belong in a separate
schema migration because adding columns changes the source data model.

After applying permission changes, verify with the `Livekit` token, not an admin
token. The visible fields should include `clients.first_step` and legacy
`bot_configurations.first_step_text`:

```bash
curl -sS "$DIRECTUS_URL/items/clients?limit=1&fields=id,first_step" \
  -H "Authorization: Bearer $DIRECTUS_TOKEN"

curl -sS "$DIRECTUS_URL/items/bot_configurations?limit=1&fields=client_id,first_step_text" \
  -H "Authorization: Bearer $DIRECTUS_TOKEN"
```

If Directus still reports `FORBIDDEN` or `field does not exist`, distinguish the
two causes by checking the real DB schema with an admin/Postgres connection. The
runtime service token usually cannot read `directus_fields`, so `/fields/...`
is not a reliable structure check for the `Livekit` role.

## Runtime env

Set these LiveKit Cloud secrets:

```env
DIRECTUS_URL=https://directus.example.com
DIRECTUS_TOKEN=<Livekit role static token>
DIRECTUS_REQUEST_TIMEOUT_SEC=2.0
DIRECTUS_PROMPT_CACHE_TTL_SEC=300
DIRECTUS_DEFAULT_TIMEZONE=Europe/Kaliningrad
DIRECTUS_COLLECTION_CALLER_ID=CallerID
DIRECTUS_COLLECTION_BOT_CONFIGURATIONS=bot_configurations
DIRECTUS_COLLECTION_CLIENTS=clients
DIRECTUS_COLLECTION_CLIENTS_PROMPT=clients_prompt
DIRECTUS_COLLECTION_WEBPARSING=webparsing
DIRECTUS_COLLECTION_TRANSFER_NUMBER=transfer_number
DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE=client_prompt_cache
DIRECTUS_INITIAL_GREETING_FIELD=first_step
```

If a collection API key differs from the display name in the Directus UI, set
the matching `DIRECTUS_COLLECTION_*` override.

## Cache collection

Create a separate collection named `client_prompt_cache`.

Fields:

- `caller_id`: string, unique
- `client_id`: integer or relation id
- `prompt_template`: text
- `timezone`: string, default `Europe/Kaliningrad`
- `source_hash`: string, nullable
- `active`: boolean, default `true`
- `last_error`: text, nullable
- `date_updated`: Directus date-updated metadata field

The cached value must be a template, not a fully rendered prompt. Use
`{{CURRENT_DATETIME_BLOCK}}` where the robot should inject fresh local company
date and time on each call.

Client-specific fixed greetings are read from `clients.first_step` by default.
If the cell is empty, the robot uses its default greeting. If the Directus API
key differs from the UI label, set `DIRECTUS_INITIAL_GREETING_FIELD` to the real
field key.

`DIRECTUS_PROMPT_CACHE_TTL_SEC` controls both the short in-process cache and
the maximum age of a stored `client_prompt_cache` row. With the default `300`,
the robot can use a saved row for up to five minutes; after that it rebuilds
from source collections and writes a fresh cache row.

## Robot write-through cache

The LiveKit robot uses write-through cache behavior:

1. Read `client_prompt_cache` by `caller_id` and `active = true`.
2. If found and `date_updated` is not older than
   `DIRECTUS_PROMPT_CACHE_TTL_SEC`, render fresh `<current_datetime>` and start
   the call.
3. If not found or stale, build the prompt live from source collections.
4. After a successful live build, upsert only `client_prompt_cache`.
5. If the cache write fails, continue the call with the live prompt and log a
   warning.

The robot does not write to `CallerID`, `bot_configurations`, `clients`,
`clients_prompt`, `webparsing`, or `transfer_number`.

## Flow

Create a Directus Flow that rebuilds only `client_prompt_cache`. This Flow is
optional but useful when prompt edits must be reflected immediately; without it,
the robot refreshes stale rows on the next lookup after the cache TTL expires.

Recommended triggers:

- `CallerID` item create/update/delete
- `bot_configurations` item create/update/delete
- `clients` item update
- `clients_prompt` item update
- `webparsing` item create/update/delete
- `transfer_number` item create/update/delete

Recommended behavior:

- For client-specific changes, rebuild cache rows for caller ids with the same
  `client_id`.
- For `clients_prompt.name = global_rules`, rebuild all active caller ids.
- For a skills prompt change, rebuild caller ids whose bot configuration uses
  that `skills_name`.
- On success, update only `client_prompt_cache.prompt_template`, `timezone`,
  `source_hash`, `active`, and clear `last_error`.
- On failure, write only `client_prompt_cache.last_error`.

The robot can still build the prompt live if `client_prompt_cache` is missing,
and falls back to `src/prompt.txt` if Directus is unavailable.

## Schema And Permission Changes

When runtime code starts using a new Directus table or column, update the source
schema and Directus permissions together:

1. Add the DB table/column in a focused SQL migration if it does not already
   exist.
2. Add Directus collection/field metadata when the table/column should be
   visible in Directus UI.
3. Grant the `Livekit` role only the required action and fields through
   `directus_permissions`.
4. Add or update tests that cover the new field in prompt/settings resolution.
5. Verify with the service token and sync/redeploy only after the runtime can
   read the field without admin privileges.

New access for `Livekit` is expected maintenance, not a security exception. The
boundary is least privilege: read access to source data the agent needs,
write access only to runtime-owned cache/log tables, and no delete/admin rights.
