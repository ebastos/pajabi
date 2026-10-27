"""Forms and webhook subscriptions."""

from __future__ import annotations

from typing import Any

from typing_extensions import Required, TypedDict, Unpack

from pajabi._bodies import resource_document, to_one
from pajabi.errors import KajabiError
from pajabi.models import Form, FormSubmission, Hook
from pajabi.resources._common import AsyncAPI, AsyncReadOnly, ReadOnly, SyncAPI, item_path


class FormSubmissionAttributes(TypedDict, total=False):
    """Fields accepted by ``forms.submit``. ``name`` and ``email`` are required."""

    name: Required[str]
    email: Required[str]
    phone_number: str | None
    business_number: str | None
    address_line_1: str | None
    address_line_2: str | None
    address_city: str | None
    address_state: str | None
    address_country: str | None
    address_zip: str | None
    custom_1: str | None
    custom_2: str | None
    custom_3: str | None


def form_submit_body(attributes: FormSubmissionAttributes) -> dict[str, Any]:
    return resource_document(resource_type="form_submissions", attributes=attributes)


class Forms(ReadOnly[Form]):
    """Forms and form submission."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/forms", Form)

    def submit(
        self, form_id: str, **attributes: Unpack[FormSubmissionAttributes]
    ) -> FormSubmission:
        """Submit a form. ``name`` and ``email`` are required by Kajabi.

        Fields are :class:`FormSubmissionAttributes`. Kajabi returns
        ``mobile_phone_number`` and does not accept it on submit.
        """
        return self._api._send_json(
            "POST",
            f"{item_path(self._path, form_id)}/submit",
            form_submit_body(attributes),
            FormSubmission,
        )


class AsyncForms(AsyncReadOnly[Form]):
    """Async twin of :class:`Forms`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/forms", Form)

    async def submit(
        self, form_id: str, **attributes: Unpack[FormSubmissionAttributes]
    ) -> FormSubmission:
        """Submit a form. See :meth:`Forms.submit`."""
        return await self._api._send_json(
            "POST",
            f"{item_path(self._path, form_id)}/submit",
            form_submit_body(attributes),
            FormSubmission,
        )


SAMPLE_EVENTS = (
    "tag_added",
    "tag_removed",
    "form_submission",
    "purchase",
    "payment_succeeded",
    "order_created",
)


def hook_create_body(
    *,
    site_id: str,
    event: str,
    target_url: str,
    resource_id: int | None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {"event": event, "target_url": target_url}
    if resource_id is not None:
        attributes["resource_id"] = resource_id
    return resource_document(
        resource_type="hooks",
        attributes=attributes,
        relationships={"site": to_one(str(site_id), "sites")},
    )


def _sample_path(event: str) -> str:
    if event not in SAMPLE_EVENTS:
        known = ", ".join(SAMPLE_EVENTS)
        raise KajabiError(f"Unknown webhook sample {event!r}. Expected one of: {known}.")
    return f"/v1/hooks/{event}_sample"


class Hooks(ReadOnly[Hook]):
    """Webhook subscriptions."""

    def __init__(self, api: SyncAPI) -> None:
        super().__init__(api, "/v1/hooks", Hook)

    def create(
        self,
        *,
        site_id: str,
        event: str,
        target_url: str,
        resource_id: int | None = None,
    ) -> Hook:
        """Subscribe ``target_url`` to ``event`` on a site.

        Omit ``resource_id`` (or pass ``None``) to receive every event of that
        type. Pass an integer id to limit the subscription to one resource.
        """
        return self._api._send_json(
            "POST",
            self._path,
            hook_create_body(
                site_id=site_id,
                event=event,
                target_url=target_url,
                resource_id=resource_id,
            ),
            Hook,
        )

    def delete(self, hook_id: str) -> None:
        """Delete a webhook subscription."""
        self._api._delete(item_path(self._path, hook_id))

    def sample(self, event: str) -> Any:
        """Return Kajabi's sample payload for a webhook event.

        ``event`` is one of ``tag_added``, ``tag_removed``, ``form_submission``,
        ``purchase``, ``payment_succeeded``, or ``order_created``.
        """
        return self._api._request_json("GET", _sample_path(event))


class AsyncHooks(AsyncReadOnly[Hook]):
    """Async twin of :class:`Hooks`."""

    def __init__(self, api: AsyncAPI) -> None:
        super().__init__(api, "/v1/hooks", Hook)

    async def create(
        self,
        *,
        site_id: str,
        event: str,
        target_url: str,
        resource_id: int | None = None,
    ) -> Hook:
        return await self._api._send_json(
            "POST",
            self._path,
            hook_create_body(
                site_id=site_id,
                event=event,
                target_url=target_url,
                resource_id=resource_id,
            ),
            Hook,
        )

    async def delete(self, hook_id: str) -> None:
        await self._api._delete(item_path(self._path, hook_id))

    async def sample(self, event: str) -> Any:
        return await self._api._request_json("GET", _sample_path(event))
