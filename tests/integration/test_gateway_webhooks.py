"""Webhooks from the gateway emulator to a merchant's endpoint that reads them with the SDK."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from polako.sdk import (
    ChargeFailed,
    ChargeSucceeded,
    DroppedExternally,
    SubscriptionCancelled,
    UnknownSubscriptionEvent,
)
from tests.factories import make_subscribe_args, sign_webhook_body
from tests.generators import generate_api_key, generate_random_decimal, generate_readable_string
from tests.integration.merchant_receiver import MerchantReceiver


async def active_subscription(server, client, **args):
    """Create a subscription through the SDK and let the customer complete the registration."""
    created = await client.create_subscription(**make_subscribe_args(**args))
    return server.activate(created.subscription_id)


@pytest.mark.asyncio
async def test_a_successful_charge_reaches_the_merchant_as_a_typed_event(gateway_server, merchant_client, merchant_receiver):
    amount = generate_random_decimal(3, 2)
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    await gateway_server.charge(subscription.id, succeeded=True, amount=amount)

    [event] = merchant_receiver.events
    assert type(event) is ChargeSucceeded
    assert event.subscription_id == subscription.id
    assert event.merchant_subscription_ref == subscription.merchant_subscription_ref
    assert event.amount == amount
    assert event.currency == subscription.currency
    assert abs(datetime.now(timezone.utc) - event.charged_at) < timedelta(minutes=1)


@pytest.mark.asyncio
async def test_the_charge_defaults_to_the_subscription_amount(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    await gateway_server.charge(subscription.id)

    assert merchant_receiver.events[0].amount == subscription.amount


@pytest.mark.asyncio
async def test_a_failed_charge_carries_the_error_class(gateway_server, merchant_client, merchant_receiver):
    error_class = generate_readable_string(10)
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    await gateway_server.charge(subscription.id, succeeded=False, error_class=error_class)

    [event] = merchant_receiver.events
    assert type(event) is ChargeFailed
    assert event.error_class == error_class
    assert event.subscription_id == subscription.id


@pytest.mark.asyncio
async def test_a_card_revoked_by_the_provider_reaches_the_merchant(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    await gateway_server.drop_externally(subscription.id)

    [event] = merchant_receiver.events
    assert type(event) is DroppedExternally
    assert event.merchant_subscription_ref == subscription.merchant_subscription_ref


@pytest.mark.asyncio
async def test_a_cancellation_in_the_dashboard_reaches_the_merchant(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    await gateway_server.cancel(subscription.id)

    [event] = merchant_receiver.events
    assert type(event) is SubscriptionCancelled
    assert event.subscription_id == subscription.id


@pytest.mark.asyncio
async def test_events_arrive_in_the_order_they_happened(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    await gateway_server.charge(subscription.id)
    await gateway_server.charge(subscription.id, succeeded=False)
    await gateway_server.cancel(subscription.id)

    assert [type(e) for e in merchant_receiver.events] == [ChargeSucceeded, ChargeFailed, SubscriptionCancelled]


@pytest.mark.asyncio
async def test_the_merchant_reads_exactly_the_bytes_the_gateway_signed(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    delivery = await gateway_server.charge(subscription.id)

    assert merchant_receiver.raw_bodies == [delivery.body]
    assert delivery.body == json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True).encode()
    assert delivery.signature == sign_webhook_body(delivery.body, merchant_receiver.api_key)


@pytest.mark.asyncio
async def test_the_webhook_is_sent_as_json_with_the_signature_header(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    delivery = await gateway_server.charge(subscription.id)

    assert delivery.url == merchant_receiver.webhook_url
    assert delivery.delivered is True
    assert [a.status for a in delivery.attempts] == [200]


@pytest.mark.asyncio
async def test_an_event_of_a_kind_the_sdk_does_not_know_does_not_break_the_endpoint(
    gateway_server, merchant_client, merchant_receiver
):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)
    name = "evt_" + generate_readable_string(6).lower()

    delivery = await gateway_server.send_webhook(subscription, {"event": name, "subscription_id": str(subscription.id)})

    [event] = merchant_receiver.events
    assert type(event) is UnknownSubscriptionEvent
    assert event.event == name
    assert delivery.delivered is True


@pytest.mark.asyncio
async def test_a_merchant_with_the_wrong_key_rejects_the_webhook_and_the_gateway_does_not_retry(
    gateway_server, merchant_client, registered_platform
):
    receiver = MerchantReceiver(api_key=generate_api_key())
    async with receiver.run():
        registered_platform.callback_url = receiver.webhook_url
        async with merchant_client as client:
            subscription = await active_subscription(gateway_server, client)

        delivery = await gateway_server.charge(subscription.id)

    assert receiver.events == []
    assert len(receiver.signature_errors) == 1
    assert [a.status for a in delivery.attempts] == [400]
    assert delivery.delivered is False


@pytest.mark.asyncio
async def test_a_merchant_who_serializes_the_json_again_fails_the_signature(
    gateway_server, merchant_client, registered_platform
):
    receiver = MerchantReceiver(api_key=registered_platform.api_key, reserialize=True)
    async with receiver.run():
        registered_platform.callback_url = receiver.webhook_url
        async with merchant_client as client:
            subscription = await active_subscription(gateway_server, client)

        await gateway_server.charge(subscription.id)

    assert receiver.events == []
    assert len(receiver.signature_errors) == 1


@pytest.mark.asyncio
async def test_a_failing_endpoint_is_retried_until_it_answers(gateway_server, merchant_client, merchant_receiver):
    merchant_receiver.fail_next(500, times=2)
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    delivery = await gateway_server.charge(subscription.id)

    assert [a.status for a in delivery.attempts] == [500, 500, 200]
    assert delivery.delivered is True
    assert len(merchant_receiver.events) == 1


@pytest.mark.asyncio
async def test_an_endpoint_that_keeps_failing_gets_three_attempts_and_no_more(
    gateway_server, merchant_client, merchant_receiver
):
    merchant_receiver.fail_next(503, times=10)
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    delivery = await gateway_server.charge(subscription.id)

    assert [a.status for a in delivery.attempts] == [503, 503, 503]
    assert delivery.delivered is False
    assert merchant_receiver.events == []


@pytest.mark.asyncio
async def test_a_client_error_from_the_endpoint_is_final(gateway_server, merchant_client, merchant_receiver):
    merchant_receiver.fail_next(404)
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    delivery = await gateway_server.charge(subscription.id)

    assert [a.status for a in delivery.attempts] == [404]
    assert delivery.delivered is False


@pytest.mark.asyncio
async def test_an_endpoint_that_is_down_is_tried_three_times(gateway_server, merchant_client, registered_platform):
    registered_platform.callback_url = "http://127.0.0.1:1/polako/subscription-webhook"
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    delivery = await gateway_server.charge(subscription.id)

    assert len(delivery.attempts) == 3
    assert all(a.status is None and a.error for a in delivery.attempts)
    assert delivery.delivered is False


@pytest.mark.asyncio
async def test_a_platform_without_a_callback_url_gets_no_webhooks(gateway_server, merchant_client, registered_platform):
    assert registered_platform.callback_url is None
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    delivery = await gateway_server.charge(subscription.id)

    assert delivery is None
    assert gateway_server.deliveries == []
    assert len(gateway_server.skipped_webhooks) == 1


@pytest.mark.asyncio
async def test_every_delivery_is_recorded(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client)

    first = await gateway_server.charge(subscription.id)
    second = await gateway_server.cancel(subscription.id)

    assert gateway_server.deliveries == [first, second]


@pytest.mark.asyncio
async def test_a_subscription_that_is_not_active_cannot_be_charged(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        created = await client.create_subscription(**make_subscribe_args())

    with pytest.raises(AssertionError):
        await gateway_server.charge(created.subscription_id)


@pytest.mark.asyncio
async def test_the_sdk_amount_keeps_the_decimal_places_over_the_wire(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        subscription = await active_subscription(gateway_server, client, amount=Decimal("990.50"))

    await gateway_server.charge(subscription.id)

    assert str(merchant_receiver.events[0].amount) == "990.50"
