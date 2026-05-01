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

Recommended readable fields:

- `CallerID`: `CallerID`, `client_id`
- `bot_configurations`: `client_id`, `system_prompt`, `examples`, `skills_name`,
  `first_step`
- `clients`: `id`, `add_info`, `company_website`, `company_extra`
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

Client-specific fixed greetings are read from `bot_configurations.first_step`
by default. If the Directus API key differs from the UI label, set
`DIRECTUS_INITIAL_GREETING_FIELD` to the real field key.

## Robot write-through cache

The LiveKit robot uses write-through cache behavior:

1. Read `client_prompt_cache` by `caller_id` and `active = true`.
2. If found, render fresh `<current_datetime>` and start the call.
3. If not found, build the prompt live from source collections.
4. After a successful live build, upsert only `client_prompt_cache`.
5. If the cache write fails, continue the call with the live prompt and log a
   warning.

The robot does not write to `CallerID`, `bot_configurations`, `clients`,
`clients_prompt`, `webparsing`, or `transfer_number`.

## Flow

Create a Directus Flow that rebuilds only `client_prompt_cache`. This Flow is a
future freshness improvement; the robot can already create a cache row on the
first cache miss.

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
