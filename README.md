# pajabi

Typed Python client for the [Kajabi Public API](https://developers.kajabi.com).

`pajabi.Kajabi` is synchronous and `pajabi.AsyncKajabi` is asynchronous. Both speak JSON:API, page through `links.next`, and keep the OAuth token up to date.

Requires Python 3.10 or newer.

## Installation

```bash
pip install pajabi
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv add pajabi
```

Runtime dependencies are `httpx` and `pydantic` 2.

From a checkout of this repository, `uv sync` installs the package and the development tools.

## Authentication

The client-credentials grant is the usual way in. `client_id` and `client_secret` fall back to `KAJABI_CLIENT_ID` and `KAJABI_CLIENT_SECRET`.

```python
import os

from pajabi import Kajabi

kajabi = Kajabi(
    client_id=os.environ["KAJABI_CLIENT_ID"],
    client_secret=os.environ["KAJABI_CLIENT_SECRET"],
)
```

The first API call fetches a token with `POST /v1/oauth/token` (`application/x-www-form-urlencoded`, `grant_type=client_credentials`). The token is cached and refreshed shortly before `expires_in` elapses, using the `refresh_token` grant. If that grant fails, the client asks for a new client-credentials token. A `401` triggers one refresh and one retry of the original request.

A token you already have is sent as-is. Pass `refresh_token` as well when Kajabi gave you one and you want the client to renew it:

```python
kajabi = Kajabi(access_token="...", refresh_token="...")
```

`kajabi.revoke_token()` calls `POST /v1/oauth/revoke` for the access token the client already holds, then forgets it. If no token has been obtained yet, the call does nothing and does not fetch one just to revoke it.

Use the client as a context manager so the connection closes:

```python
with Kajabi(client_id="...", client_secret="...") as kajabi:
    me = kajabi.me()
    print(me.name, me.email)
```

`GET /v1/version` does not send a bearer token:

```python
print(kajabi.version().version)
```

## Quickstart

```python
with Kajabi(client_id="...", client_secret="...") as kajabi:
    page = kajabi.contacts.list(site_id="123")
    for contact in page:
        print(contact.id, contact.name, contact.email)

    jane = kajabi.contacts.create(
        site_id="123",
        name="Jane",
        email="jane@example.com",
    )
    print(jane.id)
```

Resource namespaces:

`contacts`, `contact_notes`, `contact_tags`, `customers`, `courses`, `custom_fields`, `forms`, `form_submissions`, `hooks`, `payouts`, `landing_pages`, `offers`, `order_items`, `orders`, `podcasts`, `products`, `purchases`, `sites`, `transactions`, `website_pages`, `blog_posts`.

`me()` and `version()` live on the client. Listing methods are `list` and `iter`. Single resources use `get`. Writes use `create`, `update`, and `delete` where the API allows them.

## Pagination

`list` returns one `Page`. Iterating the page yields that page's items. `meta` carries `total_count`, `total_pages`, and `current_page` when Kajabi sends them. `links.next` is how you know another page exists.

```python
page = kajabi.contacts.list(site_id="123", page=1, page_size=50)
print(page.meta.total_count, page.has_next_page())
for contact in page:
    print(contact.email)

if page.has_next_page():
    page = page.next_page()
```

`iter` follows `links.next` until it is missing, and stops if a next URL repeats:

```python
for contact in kajabi.contacts.iter(site_id="123"):
    print(contact.id)
```

A list payload with no `meta` and no `links.next` is a single page. `has_next_page()` is false.

Payout lists use a different meta shape (`total`, `pagination.current`, `pagination.last`). Those values show up on `meta.total_count`, `meta.current_page`, and `meta.total_pages`. `site_id` is required:

```python
for payout in kajabi.payouts.iter(site_id="123"):
    print(payout.id, payout.amount, payout.currency)
```

## Filtering, sorting, includes, and sparse fields

Keyword arguments to `list` become `filter[<name>]`. Documented filters such as `site_id` are the same kind of argument. Ransack suffixes (`_eq`, `_cont`, `_not_eq`, `_not_cont`, `_start`, `_end`) are just part of the name.

```python
courses = kajabi.courses.list(
    site_id="1",
    title_cont="Intro",
    sort="-created_at",
    include=["modules", "lessons", "lessons.media", "offers"],
    fields={"courses": ["title", "description"]},
    page=1,
    page_size=20,
)
```

That request carries:

- `filter[site_id]=1`
- `filter[title_cont]=Intro`
- `sort=-created_at` (`-` is descending)
- `include=modules,lessons,lessons.media,offers` (`include="modules,lessons,lessons.media,offers"` works too)
- `fields[courses]=title,description`
- `page[number]=1` and `page[size]=20`

A list value is repeated as `filter[<name>][]`:

```python
kajabi.products.list(exclude_product_types=["Course", "Coaching"])
```

Booleans are sent as `true` or `false`. `None` drops the parameter.

`get` accepts `include`, `fields`, and the same filter keywords:

```python
contact = kajabi.contacts.get("123", include=["tags", "offers"])
```

Every attribute is optional, because a sparse fieldset omits whatever you did not ask for. Datetime fields are `datetime` objects. Unknown attributes are kept for forward compatibility.

Relationships are available even when you did not `include` them, as ids. When the response contains `included`, matching resources are models:

```python
tags = contact.related("tags")
for tag in tags:
    print(tag.id, getattr(tag, "name", None))

print(contact.relationship_ids("offers"))
```

`related` returns one value for a to-one relationship and a list for a to-many relationship.

## Create and update

`create` and `update` take keyword arguments and build the JSON:API document, including the `type` and the `site` relationship where the spec requires it. Contact fields are `ContactAttributes` (`name`, `email`, `phone_number`, `business_number`, `subscribed`, the `address_*` fields, `external_user_id`, and `custom_1` through `custom_3`). A key you omit is left out of the body. Pass `None` to send JSON `null`. Form submissions use `FormSubmissionAttributes`, where `name` and `email` are required.

```python
contact = kajabi.contacts.create(
    site_id="123",
    name="Jane",
    email="jane@example.com",
    subscribed=True,
)
kajabi.contacts.update(contact.id, name="Janet", tags=["5"])

note = kajabi.contact_notes.create(contact_id=contact.id, body="Called about the workshop")
kajabi.contact_notes.update(note.id, body="Called, will follow up")
kajabi.contact_notes.delete(note.id)
```

Pass `tags` to `contacts.update` only when you want to replace the contact's tags. Leaving it out leaves tags alone.

Form submissions:

```python
submission = kajabi.forms.submit(
    "123",
    name="Jane",
    email="jane@example.com",
)
```

## Relationships

Contact tags:

```python
kajabi.contacts.tags.list("123")
kajabi.contacts.tags.add("123", ["5", "6"])
kajabi.contacts.tags.remove("123", "5")
kajabi.contacts.tags.replace("123", ["6"])
```

Contact offers. The contact id is `owner_id`. `grant`, `revoke`, and `replace` also take `offer_ids`. `send_welcome_email` is sent as `meta.send_customer_welcome_email`. Omit it and Kajabi keeps its default (the welcome email is sent).

```python
kajabi.contacts.offers.list("123")
kajabi.contacts.offers.grant("123", ["9"], send_welcome_email=False)
kajabi.contacts.offers.revoke("123", "9")
kajabi.contacts.offers.replace("123", ["9", "10"])
```

Customer offers use the same methods and the same parameter names on `kajabi.customers.offers`. The welcome-email flag is sent only when you pass it.

Products on an offer, and purchase actions:

```python
kajabi.offers.products("45")
kajabi.purchases.reactivate("88")
kajabi.purchases.deactivate("88")
kajabi.purchases.cancel_subscription("88")
```

An id can be a string or an integer. One id and a list of ids are both accepted.

## Webhooks

```python
hook = kajabi.hooks.create(
    site_id="123",
    event="purchase",
    target_url="https://example.com/kajabi",
)
sample = kajabi.hooks.sample("purchase")
kajabi.hooks.delete(hook.id)
```

`event` is one of `purchase`, `form_submission`, `tag_added`, `tag_removed`, `payment_succeeded`, and `order_created`. Pass `resource_id` to limit a subscription to one resource, such as a tag id. `sample` returns Kajabi's example JSON for that event.

## Errors

Failures raise `pajabi.KajabiError`. HTTP responses use `pajabi.APIError`, which carries `status_code`, `errors` (the JSON:API error objects), and `response`. `str(error)` joins each error's title, detail, and source pointer.

| Status | Exception |
| --- | --- |
| 400 | `BadRequestError` |
| 401 | `AuthenticationError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitError` |
| 5xx | `InternalServerError` |
| connection failure | `APIConnectionError` |
| timeout | `APITimeoutError` |

```python
from pajabi import Kajabi, NotFoundError

with Kajabi(client_id="...", client_secret="...") as kajabi:
    try:
        kajabi.contacts.get("missing")
    except NotFoundError as exc:
        print(exc.status_code)
        print(exc.errors[0].detail)
        if exc.errors[0].source is not None:
            print(exc.errors[0].source.pointer)
```

## Async

`AsyncKajabi` mirrors the sync client. `list` and `get` are coroutines. `iter` is an async generator.

```python
import asyncio

from pajabi import AsyncKajabi


async def main() -> None:
    async with AsyncKajabi(client_id="...", client_secret="...") as kajabi:
        contact = await kajabi.contacts.get("123")
        print(contact.email)
        async for order in kajabi.orders.iter():
            print(order.id)
        page = await kajabi.sites.list()
        if page.has_next_page():
            page = await page.next_page()


asyncio.run(main())
```

`await kajabi.aclose()` closes a client that is not used as a context manager. `close()` is the sync equivalent.

## Configuration

```python
Kajabi(
    client_id=None,
    client_secret=None,
    access_token=None,
    refresh_token=None,
    base_url="https://api.kajabi.com",
    timeout=30.0,
    max_retries=2,
    http_client=None,
)
```

`timeout` is seconds, or an `httpx.Timeout`. `max_retries` is how many extra attempts follow the first one (the default of 2 allows three attempts).

`429` is always retried. A `Retry-After` value, seconds or an HTTP date, wins over the backoff and is capped at 60 seconds, so a huge value cannot stall the caller. `5xx`, connection errors, and timeouts are retried only for idempotent methods: `GET`, `HEAD`, `OPTIONS`, `PUT`, `PATCH`, and `DELETE`. Backoff is exponential with full jitter, capped at 20 seconds.

`request(method, path, *, params=None, json=None)` is the low-level escape hatch for a path the resource namespaces do not cover. It sends `Accept: application/vnd.api+json` and, when `json` is given, a JSON:API body. The return value is the parsed JSON, or `None` when the body is empty. It uses the same retry policy as the resource methods and sends bearer auth. An absolute URL is sent only when its scheme, host, and port match `base_url` (default ports are the same as an omitted port). Any other origin raises `KajabiError` before a request is made. `version()` and `revoke_token()` are the calls that skip bearer auth.

Pass `http_client` to use your own `httpx.Client` (or `httpx.AsyncClient` for `AsyncKajabi`). That client is left open when `pajabi` closes. A client this library creates is closed.

`base_url` defaults to `https://api.kajabi.com`. Requests are sent to that origin even if `http_client` has a different base URL.

## License

Released under the MIT License.
