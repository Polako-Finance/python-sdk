"""Reading and managing subscriptions over real HTTP: list, detail, pause, resume, cancel.

The merchant's code calls the SDK, the SDK calls the emulator on a socket, and a cancelled subscription is announced to
the merchant's webhook endpoint, exactly as in the flow of creating one.
"""

import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from polako.sdk import (
    ChargeAttemptStatus,
    ConflictError,
    ForbiddenError,
    HttpClientError,
    NotFoundError,
    PolakoClient,
    RateLimitedError,
    ServerError,
    SubscriptionCancelled,
    SubscriptionStatus,
    UnauthorizedError,
)
from tests.factories import make_credentials, make_subscribe_args
from tests.generators import generate_api_key, generate_random_decimal, generate_readable_string


async def create(client, receiver=None, **args):
    """Create a subscription with random valid arguments."""
    if receiver is not None:
        args.setdefault("error_url", receiver.error_url)
    return await client.create_subscription(**make_subscribe_args(**args))


async def create_active(gateway_server, client, receiver=None, **args):
    """Create a subscription and let the customer finish the card registration; return its ID."""
    created = await create(client, receiver, **args)
    gateway_server.activate(created.subscription_id)
    return created.subscription_id


def lower_token(length: int = 10) -> str:
    return generate_readable_string(length).lower()


# ---------------------------------------------------------------------------
# One subscription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_subscription_is_read_as_it_was_created(gateway_server, merchant_client):
    args = make_subscribe_args()
    async with merchant_client as client:
        created = await client.create_subscription(**args)

        detail = await client.get_subscription(created.subscription_id)

    assert detail.id == created.subscription_id
    assert detail.status is SubscriptionStatus.PENDING_REGISTRATION
    assert detail.customer.email == args["customer_email"]
    assert detail.merchant_subscription_ref == args["merchant_subscription_ref"]
    assert (detail.amount, detail.currency) == (args["amount"], args["currency"])
    assert detail.billing_interval is args["billing_interval"]
    assert detail.saved_card is None
    assert detail.charge_history == () and detail.events == ()
    assert detail.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_after_the_card_registration_the_subscription_is_active_with_a_card_and_a_next_charge(
    gateway_server, merchant_client
):
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client)

        detail = await client.get_subscription(subscription_id)

    assert detail.status is SubscriptionStatus.ACTIVE
    assert detail.saved_card is not None and detail.saved_card.masked_pan
    assert detail.next_charge_at is not None and detail.next_charge_at > detail.created_at
    assert [event.event_type for event in detail.events] == ["created"]


@pytest.mark.asyncio
async def test_the_charge_history_and_the_journal_follow_what_happened(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client, merchant_receiver)
        await gateway_server.charge(subscription_id)
        await gateway_server.charge(subscription_id)
        await gateway_server.charge(subscription_id, succeeded=False, error_class="insufficient_funds")

        detail = await client.get_subscription(subscription_id)

    assert detail.status is SubscriptionStatus.PAST_DUE
    assert [charge.status for charge in detail.charge_history] == [
        ChargeAttemptStatus.FAILED,
        ChargeAttemptStatus.SUCCEEDED,
        ChargeAttemptStatus.SUCCEEDED,
    ]
    assert detail.charge_history[0].error_class == "insufficient_funds"
    assert all(charge.payment_session_id is not None for charge in detail.charge_history)
    assert detail.failed_charge_count == 1 and detail.last_failed_charge_at is not None
    assert detail.last_charged_at is not None
    assert [event.event_type for event in detail.events] == [
        "created",
        "charge_succeeded",
        "charge_succeeded",
        "charge_failed",
        "past_due",
    ]


# ---------------------------------------------------------------------------
# A list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_list_is_paged_newest_first_and_says_how_many_there_are(gateway_server, merchant_client):
    async with merchant_client as client:
        ids = [(await create(client)).subscription_id for _ in range(5)]

        first = await client.list_subscriptions(limit=2)
        second = await client.list_subscriptions(limit=2, offset=2)
        last = await client.list_subscriptions(limit=2, offset=4)

    newest_first = list(reversed(ids))
    assert [item.id for item in first.items] == newest_first[:2]
    assert [item.id for item in second.items] == newest_first[2:4]
    assert [item.id for item in last.items] == newest_first[4:]
    assert (first.total, second.total, last.total) == (5, 5, 5)
    assert (first.limit, first.offset, second.offset, last.offset) == (2, 0, 2, 4)


@pytest.mark.asyncio
async def test_a_company_with_no_subscriptions_gets_an_empty_page(gateway_server, merchant_client):
    async with merchant_client as client:
        page = await client.list_subscriptions()

    assert page.items == () and page.total == 0


@pytest.mark.asyncio
async def test_the_list_filters_by_status_and_by_interval(gateway_server, merchant_client):
    async with merchant_client as client:
        active = await create_active(gateway_server, client, billing_interval="monthly")
        pending = (await create(client, billing_interval="weekly")).subscription_id
        paused = await create_active(gateway_server, client, billing_interval="weekly")
        await client.pause_subscription(paused)

        only_active = await client.list_subscriptions(status="active")
        live = await client.list_subscriptions(status=[SubscriptionStatus.ACTIVE, SubscriptionStatus.PAUSED])
        weekly = await client.list_subscriptions(billing_interval="weekly")
        weekly_paused = await client.list_subscriptions(billing_interval="weekly", status="paused")

    assert {item.id for item in only_active.items} == {active}
    assert {item.id for item in live.items} == {active, paused}
    assert {item.id for item in weekly.items} == {pending, paused}
    assert {item.id for item in weekly_paused.items} == {paused}


@pytest.mark.asyncio
async def test_the_list_searches_by_email_reference_and_id(gateway_server, merchant_client):
    email_token, ref_token = lower_token(), lower_token()
    async with merchant_client as client:
        by_email = (await create(client, customer_email=f"{email_token}@example.com")).subscription_id
        by_ref = (await create(client, merchant_subscription_ref=f"plan-{ref_token}")).subscription_id
        other = (await create(client)).subscription_id

        found_by_email = await client.list_subscriptions(search=email_token.upper())
        found_by_ref = await client.list_subscriptions(search=ref_token)
        found_by_id = await client.list_subscriptions(search=str(other))

    assert [item.id for item in found_by_email.items] == [by_email]
    assert [item.id for item in found_by_ref.items] == [by_ref]
    assert [item.id for item in found_by_id.items] == [other]


@pytest.mark.asyncio
async def test_the_list_filters_by_the_day_a_subscription_was_created(gateway_server, merchant_client):
    today = datetime.now(timezone.utc).date()
    async with merchant_client as client:
        created = (await create(client)).subscription_id

        from_today = await client.list_subscriptions(created_from=today)
        until_today = await client.list_subscriptions(created_to=today)
        before = await client.list_subscriptions(created_to=today - timedelta(days=1))
        after = await client.list_subscriptions(created_from=today + timedelta(days=1))
        in_the_last_hour = await client.list_subscriptions(created_from=datetime.now(timezone.utc) - timedelta(hours=1))

    assert [item.id for item in from_today.items] == [created]
    assert [item.id for item in until_today.items] == [created]
    assert [item.id for item in in_the_last_hour.items] == [created]
    assert before.items == () and after.items == ()


@pytest.mark.asyncio
async def test_the_list_sorts_by_the_chosen_field(gateway_server, merchant_client):
    amounts = sorted({generate_random_decimal(3, 2) for _ in range(4)})
    async with merchant_client as client:
        for amount in random.sample(amounts, len(amounts)):
            await create(client, amount=amount)

        ascending = await client.list_subscriptions(sort_by="amount", sort_order="asc")
        descending = await client.list_subscriptions(sort_by="amount", sort_order="desc")

    assert [item.amount for item in ascending.items] == amounts
    assert [item.amount for item in descending.items] == list(reversed(amounts))


# ---------------------------------------------------------------------------
# Whose subscriptions they are
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_company_sees_none_of_it_and_can_touch_none_of_it(gateway_server, merchant_client):
    outsider = gateway_server.add_platform()
    outsider_client = PolakoClient(test_env=True, company_id=outsider.company_id, api_key=outsider.api_key)
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client)

    async with outsider_client as other:
        assert (await other.list_subscriptions()).items == ()
        with pytest.raises(ForbiddenError):
            await other.get_subscription(subscription_id)
        for change in (other.pause_subscription, other.resume_subscription, other.cancel_subscription):
            with pytest.raises(ForbiddenError):
                await change(subscription_id)

    assert gateway_server.subscriptions[subscription_id].status == "active"


@pytest.mark.asyncio
async def test_a_key_cannot_reach_into_another_companys_path(gateway_server, merchant_client, registered_platform):
    outsider = gateway_server.add_platform()
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client)
    wrong_company = PolakoClient(test_env=True, company_id=registered_platform.company_id, api_key=outsider.api_key)

    async with wrong_company as client:
        with pytest.raises(ForbiddenError):
            await client.list_subscriptions()
        with pytest.raises(ForbiddenError):
            await client.cancel_subscription(subscription_id)

    assert gateway_server.subscriptions[subscription_id].status == "active"


@pytest.mark.asyncio
async def test_an_unknown_key_is_unauthorised_and_an_unknown_subscription_is_not_found(
    gateway_server, merchant_client, registered_platform
):
    stranger = PolakoClient(test_env=True, company_id=registered_platform.company_id, api_key=generate_api_key())

    async with stranger as client:
        with pytest.raises(UnauthorizedError):
            await client.list_subscriptions()
    async with merchant_client as client:
        for call in (
            client.get_subscription,
            client.pause_subscription,
            client.resume_subscription,
            client.cancel_subscription,
        ):
            with pytest.raises(NotFoundError):
                await call(uuid4())


# ---------------------------------------------------------------------------
# Pause, resume, cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_subscription_is_paused_resumed_and_cancelled_and_the_merchant_hears_of_the_cancellation(
    gateway_server, merchant_client, merchant_receiver
):
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client, merchant_receiver)

        await client.pause_subscription(subscription_id)
        assert (await client.get_subscription(subscription_id)).status is SubscriptionStatus.PAUSED
        assert [item.id for item in (await client.list_subscriptions(status="paused")).items] == [subscription_id]

        await client.resume_subscription(subscription_id)
        assert (await client.get_subscription(subscription_id)).status is SubscriptionStatus.ACTIVE

        await client.cancel_subscription(subscription_id)
        detail = await client.get_subscription(subscription_id)

    assert detail.status is SubscriptionStatus.CANCELLED
    assert [event.event_type for event in detail.events] == ["created", "paused", "resumed", "cancelled"]
    [event] = merchant_receiver.events
    assert type(event) is SubscriptionCancelled and event.subscription_id == subscription_id
    assert merchant_receiver.failures == []


@pytest.mark.asyncio
async def test_a_cancelled_subscription_accepts_no_change_and_the_reason_is_in_the_error(gateway_server, merchant_client):
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client)
        await client.cancel_subscription(subscription_id)

        for change in (client.pause_subscription, client.resume_subscription, client.cancel_subscription):
            with pytest.raises(ConflictError) as caught:
                await change(subscription_id)
            assert caught.value.status_code == 409 and caught.value.response_body


@pytest.mark.asyncio
async def test_each_change_is_allowed_only_from_the_right_status(gateway_server, merchant_client):
    async with merchant_client as client:
        pending = (await create(client)).subscription_id
        active = await create_active(gateway_server, client)
        paused = await create_active(gateway_server, client)
        await client.pause_subscription(paused)
        past_due = await create_active(gateway_server, client)
        await gateway_server.charge(past_due, succeeded=False)

        for change, subscription_id in [
            (client.pause_subscription, pending),
            (client.resume_subscription, pending),
            (client.cancel_subscription, pending),
            (client.resume_subscription, active),
            (client.pause_subscription, paused),
            (client.pause_subscription, past_due),
            (client.resume_subscription, past_due),
        ]:
            with pytest.raises(ConflictError):
                await change(subscription_id)

        await client.cancel_subscription(paused)
        await client.cancel_subscription(past_due)

    assert gateway_server.subscriptions[paused].status == "cancelled"
    assert gateway_server.subscriptions[past_due].status == "cancelled"


@pytest.mark.asyncio
async def test_changes_are_refused_while_subscriptions_are_switched_off_but_reading_still_works(
    gateway_server, merchant_client
):
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client)
        gateway_server.subscriptions_enabled = False

        for change in (client.pause_subscription, client.resume_subscription, client.cancel_subscription):
            with pytest.raises(ConflictError):
                await change(subscription_id)
        detail = await client.get_subscription(subscription_id)
        page = await client.list_subscriptions()

    assert detail.status is SubscriptionStatus.ACTIVE
    assert [item.id for item in page.items] == [subscription_id]


# ---------------------------------------------------------------------------
# What goes over the wire, and failures on the way
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_management_calls_carry_only_the_api_key(gateway_server, merchant_client, registered_platform):
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client)
        before = len(gateway_server.received_requests)
        await client.get_subscription(subscription_id)
        await client.list_subscriptions()
        await client.pause_subscription(subscription_id)

    sent = gateway_server.received_requests[before:]
    assert [request.method for request in sent] == ["GET", "GET", "PATCH"]
    for request in sent:
        assert request.headers["company_api_key"] == registered_platform.api_key
        assert "Idempotency-Key" not in request.headers
        assert request.body == b""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_call",
    [
        lambda client, subscription_id: client.get_subscription(subscription_id),
        lambda client, subscription_id: client.list_subscriptions(),
        lambda client, subscription_id: client.pause_subscription(subscription_id),
    ],
    ids=["get", "list", "pause"],
)
async def test_an_outage_is_raised_at_once_and_never_repeated(gateway_server, merchant_client, make_call):
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client)
        before = len(gateway_server.received_requests)
        gateway_server.fail_next(503, times=3)

        with pytest.raises(ServerError):
            await make_call(client, subscription_id)

    assert len(gateway_server.received_requests) - before == 1
    assert gateway_server.subscriptions[subscription_id].status == "active"


@pytest.mark.asyncio
async def test_a_dropped_connection_is_a_client_error_and_the_change_may_have_gone_through(gateway_server, merchant_client):
    async with merchant_client as client:
        subscription_id = await create_active(gateway_server, client)
        gateway_server.drop_connection_next()

        with pytest.raises(HttpClientError):
            await client.cancel_subscription(subscription_id)
        # nothing reached the service, so reading the subscription tells the truth before any repeat
        assert (await client.get_subscription(subscription_id)).status is SubscriptionStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_rate_limit_is_raised_with_the_wait_the_server_asked_for(gateway_server, merchant_client):
    wait = 7
    async with merchant_client as client:
        gateway_server.fail_next(429, retry_after=wait)

        with pytest.raises(RateLimitedError) as caught:
            await client.list_subscriptions()

    assert caught.value.retry_after == wait


@pytest.mark.asyncio
async def test_a_client_without_credentials_never_reaches_the_service(gateway_server):
    client = PolakoClient(test_env=True, company_id=make_credentials().company_id)

    with pytest.raises(ValueError, match="api_key"):
        async with client:
            await client.list_subscriptions()

    assert gateway_server.received_requests == []
