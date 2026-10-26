# pajabi

Typed Python client for the Kajabi Public API. `Kajabi` is synchronous. `AsyncKajabi` is the same surface as coroutines. Both speak JSON:API.

## Commands

- Install: `uv sync`
- Test: `uv run pytest`
- Lint: `uv run ruff check`
- Types: `uv run mypy`

## Layout

- `src/pajabi/client.py` — HTTP transport, retries, `request`, `me`, `version`, `revoke_token`. Resource namespaces are attributes set in `__init__`.
- `src/pajabi/resources.py` — one sync class and one `Async` twin per namespace that is more than list and get.
- `src/pajabi/models.py` — pydantic models. Attributes are flattened onto the model. `MODEL_TYPES` maps a JSON:API `type` to a class for `included` resources.
- `src/pajabi/_bodies.py` builds JSON:API documents. `_query.py` builds query strings. `_parsing.py` reads responses. `_auth.py` holds OAuth. `_retry.py` decides retry delays. `_clock.py` is the only sleep.
- `spec/openapi.yaml` is the HTTP contract. `tests/catalog.py` lists every call. `tests/test_spec_coverage.py` requires the two sets to match.
- `README.md` is the caller-facing contract. Read it before changing auth, pagination, filters, writes, or errors.

## Decisions

### Where a new operation goes

| The operation | Put it |
| --- | --- |
| `list` and `get` only, paths `/v1/<type>` and `/v1/<type>/{id}` | `ReadOnly` on `Kajabi`, `AsyncReadOnly` on `AsyncKajabi` |
| Writes, a required argument, a nested relationship, or any other path | A sync class and an `Async` twin in `resources.py`, constructed in both clients |
| Not a resource (`me`, `version`, token, revoke) | A method on both `Kajabi` and `AsyncKajabi` |

`request()` is the public escape hatch. Methods inside the library call the helpers below.

### Which helper sends it

| Response | Helper |
| --- | --- |
| GET a collection | `_get_page` |
| GET one resource | `_get_resource` |
| GET identifiers | `_get_identifiers` |
| JSON:API body, one resource back | `_send_json` |
| JSON:API body, identifiers back | `_send_identifiers` |
| POST, no body, one resource back | `_post_resource` |
| DELETE | `_delete` |
| JSON that is not a resource document | `_request_json` |

### Model fields

Copy the OpenAPI attribute type. Every field is optional, because a sparse fieldset omits it. `extra="allow"` keeps attributes the spec does not list yet, so do not add a field only to catch unknown keys.

| Spec | Field |
| --- | --- |
| `format: date-time`, or described as an ISO 8601 date-time | `datetime \| None` |
| Other timestamp-like strings (`published_at`, `fulfilled_at`) | `str \| None` |
| Integer cents (`total_price_in_cents`) | `int \| None` |
| A JSON number the spec does not call cents (`amount` on a payout) | `float \| None` |

Ids are `str`. The `id` validator stringifies numbers. Do not introduce `Decimal`.

## Adding an operation

1. Copy the path from `spec/openapi.yaml`, placeholders included (`{id}`, `{contact_id}`, `{customer_id}`, `{offer_id}`). Open that one path. The file is about 12,000 lines.
2. Add or extend the model in `models.py` and register its JSON:API type in `MODEL_TYPES`.
3. Wire both clients. Read-only is `ReadOnly(self, "/v1/courses", Course)` and `AsyncReadOnly(self, "/v1/courses", Course)`. Anything else is a sync class plus an `Async` twin. Build `iter` with `_pages(list)` and `_apages(list)`.
4. Build bodies with `resource_document` or `identifiers_document`. Build query strings with `_Listing(...).params(filters)`, which calls `encode_query`. `None` drops a filter. A bool becomes `true` or `false`. A sequence becomes `filter[<name>][]`.
5. Add a `Case` in `tests/catalog.py`. Test ids are `"1"`. `json_body` is the document `test_requests` compares byte for byte. That test runs every case on both clients. `test_spec_coverage` fails if a spec operation has no case, or a case names a path the spec does not have.
6. A closed set of attribute keywords is a `TypedDict` plus `Unpack`, as `ContactAttributes` is. Export it from `pajabi/__init__.py` only when callers name the type.

## Code templates

A create body, and the call that sends it. The async twin awaits the same helper and calls the same body function.

```python
def note_create_body(contact_id: str, body: str) -> dict[str, Any]:
    return resource_document(
        resource_type="contact_notes",
        attributes={"body": body},
        relationships={"contact": to_one(str(contact_id), "contacts")},
    )
```

```python
return self._api._send_json(
    "POST", self._path, note_create_body(contact_id, body), ContactNote
)
```

A catalog case. `path` is the OpenAPI template, not the URL after substituting `1`.

```python
Case(
    "contact_notes.create",
    "POST",
    "/v1/contact_notes",
    "contact_notes.create",
    kwargs={"contact_id": "7", "body": "Called"},
    json_body=NOTE_CREATE,
)
```

## Do / don't

- **Do not** add a public method on only one client. **Do** add it on `Kajabi` and `AsyncKajabi`, and construct the namespace in both `__init__` methods.
- **Do not** assemble a query string or a JSON:API document inside a resource method. **Do** call `encode_query` and `resource_document`.
- **Do not** sleep with `time.sleep` or `asyncio.sleep`. **Do** call `pajabi._clock.sleep` and `pajabi._clock.asleep`. Tests replace those.
- **Do not** retry `POST` after a 5xx, a timeout, or a connection error. **Do** leave the decision in `retry_delay`. Status 429 is retried for every method. Other retries apply only to `GET`, `HEAD`, `OPTIONS`, `PUT`, `PATCH`, and `DELETE`.
- **Do not** send an absolute URL whose scheme, host, or port differs from `base_url`. **Do** resolve URLs with `_absolute`. A `links.next` on another origin raises `KajabiError` before the request. An explicit default port (`:443`) matches an omitted port.
- **Do not** close an `http_client` the caller passed in. **Do** close the client this library constructed (`_owns_http`).
- **Do not** call the live API, or read `KAJABI_CLIENT_ID` / `KAJABI_CLIENT_SECRET`, in tests. **Do** use `respx`. `tests/conftest.py` deletes those variables for every test.

## Gotchas

- Contact update is the one write that puts `relationships` beside `data`. `contact_update_body` does that because the spec does. Other writes pass relationships into `resource_document`, which nests them inside `data`. Leaving `tags` out of `contacts.update` omits the key. Passing a list, including `[]`, replaces the tags.
- `send_welcome_email` is written as `meta.send_customer_welcome_email` only when the caller passes it. Omitting it leaves Kajabi's default.
- `one_or_many` treats a `str` as one id. It does not iterate characters. An `int` is stringified. A `bool` raises `TypeError`.
- `version()` and `revoke_token()` send no bearer token. `revoke_token()` returns without a request when no token is cached, and does not fetch one in order to revoke it.
- Payout list meta is `total` and `pagination.current` / `pagination.last`. `parse_meta` maps those onto `PageMeta`. Every payout method requires `site_id`.
- `iter` sends nothing until iteration starts, follows `links.next`, and stops if a next URL repeats.

## References

- `README.md` — read when the change affects what a caller sees: auth, pagination, filters, writes, webhooks, or errors.
- `spec/openapi.yaml` — read when adding or changing an operation. Open the one path. Do not load the file whole.
