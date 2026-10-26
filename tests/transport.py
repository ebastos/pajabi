"""respx responses shaped like the Kajabi API. Nothing here touches the network."""

from __future__ import annotations

import httpx

ACCESS_TOKEN = "access-1"
REFRESH_TOKEN = "refresh-1"

PURCHASE_ACTIONS = ("reactivate", "deactivate", "cancel_subscription")
RELATION_TYPES = {
    "offers": "offers",
    "tags": "contact_tags",
    "products": "products",
}


def token_document(
    access_token: str = ACCESS_TOKEN,
    refresh_token: str = REFRESH_TOKEN,
    expires_in: int = 3600,
) -> dict[str, object]:
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "token_type": "Bearer",
    }


def resource_document(resource_id: str, resource_type: str) -> dict[str, object]:
    return {"data": {"id": resource_id, "type": resource_type, "attributes": {}}}


def dispatch(request: httpx.Request) -> httpx.Response:
    """Answer every Kajabi call the suite makes with a small valid payload."""
    path = request.url.path
    method = request.method
    if path == "/v1/oauth/token":
        return httpx.Response(200, json=token_document())
    if path == "/v1/oauth/revoke":
        return httpx.Response(200, json={})
    if path == "/v1/version":
        return httpx.Response(
            200,
            json={
                "meta": {"title": "Kajabi API", "version": "1.0"},
                "links": {"documentation": "https://developers.kajabi.com"},
                "jsonapi": {
                    "version": "1.0",
                    "specficiation": "https://jsonapi.org/format/1.0/",
                },
            },
        )
    if path == "/v1/me":
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "1",
                    "type": "users",
                    "attributes": {"name": "Ada", "email": "ada@example.com"},
                }
            },
        )
    if path.endswith("_sample"):
        return httpx.Response(200, json=[{"event": path.rsplit("/", 1)[-1]}])
    if "/relationships/" in path:
        kind = path.rsplit("/", 1)[-1]
        identifier = {"id": "9", "type": RELATION_TYPES.get(kind, kind)}
        return httpx.Response(200, json={"data": [identifier]})
    if method == "DELETE":
        return httpx.Response(204)
    parts = [part for part in path.split("/") if part]
    if method == "GET" and len(parts) == 2:
        return httpx.Response(
            200, json={"data": [], "links": {"self": f"https://api.kajabi.com{path}"}}
        )
    resource_type = parts[1] if len(parts) > 1 else "resources"
    if path.endswith("/submit"):
        resource_type = "form_submissions"
    elif any(path.endswith(f"/{action}") for action in PURCHASE_ACTIONS):
        resource_type = "purchases"
    return httpx.Response(200, json=resource_document("1", resource_type))
