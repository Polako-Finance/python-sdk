"""The whole chain over real HTTP: create a subscription, register the card, then webhooks and failures reach the merchant."""

import pytest

from polako.sdk import (
    ChargeFailed,
    ChargeSucceeded,
    ConflictError,
    RegistrationFailed,
    SubscriptionCancelled,
)
from tests.factories import make_subscribe_args
from tests.generators import generate_api_key, generate_readable_string
from tests.integration.merchant_receiver import MerchantReceiver


async def create(client, receiver, **args):
    """Create a subscription whose registration failures go to the merchant's endpoint."""
    return await client.create_subscription(**make_subscribe_args(error_url=receiver.error_url, **args))


@pytest.mark.asyncio
async def test_a_subscription_lives_from_creation_to_cancellation(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        created = await create(client, merchant_receiver)
    subscription = gateway_server.subscriptions[created.subscription_id]
    assert subscription.status == "pending_registration"

    registered = await gateway_server.complete_registration(created.subscription_id)
    assert registered is None
    assert subscription.status == "active"
    assert gateway_server.deliveries == []

    await gateway_server.charge(created.subscription_id)
    await gateway_server.charge(created.subscription_id)
    await gateway_server.charge(created.subscription_id, succeeded=False)
    await gateway_server.cancel(created.subscription_id)

    assert [type(e) for e in merchant_receiver.events] == [
        ChargeSucceeded,
        ChargeSucceeded,
        ChargeFailed,
        SubscriptionCancelled,
    ]
    assert {e.subscription_id for e in merchant_receiver.events} == {created.subscription_id}
    assert {e.merchant_subscription_ref for e in merchant_receiver.events} == {subscription.merchant_subscription_ref}
    assert merchant_receiver.failures == []
    assert all(d.delivered for d in gateway_server.deliveries)


@pytest.mark.asyncio
async def test_a_failed_registration_reaches_the_merchant_as_a_verified_failure(
    gateway_server, merchant_client, merchant_receiver
):
    message, provider = generate_readable_string(20), generate_readable_string(8)
    async with merchant_client as client:
        created = await create(client, merchant_receiver)

    delivery = await gateway_server.complete_registration(
        created.subscription_id, succeeded=False, error_message=message, provider_name=provider
    )

    [failure] = merchant_receiver.failures
    assert type(failure) is RegistrationFailed
    assert failure.signature_verified is True
    assert failure.subscription_id == created.subscription_id
    assert failure.merchant_subscription_ref == gateway_server.subscriptions[created.subscription_id].merchant_subscription_ref
    assert failure.error_message == message
    assert failure.provider_name == provider
    assert gateway_server.subscriptions[created.subscription_id].status == "registration_failed"
    assert delivery.delivered is True
    assert merchant_receiver.events == []


@pytest.mark.asyncio
async def test_the_notification_has_the_shape_the_documentation_describes(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        created = await create(client, merchant_receiver)

    delivery = await gateway_server.complete_registration(created.subscription_id, succeeded=False)

    assert "event" not in delivery.payload
    assert delivery.payload["success"] == 0
    assert delivery.payload["order_id"] == delivery.payload["subscription_id"] == str(created.subscription_id)
    assert delivery.url == merchant_receiver.error_url
    assert delivery.signature
    assert merchant_receiver.raw_bodies == [delivery.body]


@pytest.mark.asyncio
async def test_the_notification_goes_to_the_error_url_even_without_a_webhook_url(
    gateway_server, merchant_client, merchant_receiver, registered_platform
):
    registered_platform.callback_url = None
    async with merchant_client as client:
        created = await create(client, merchant_receiver)

    await gateway_server.complete_registration(created.subscription_id, succeeded=False)

    assert len(merchant_receiver.failures) == 1


@pytest.mark.asyncio
async def test_a_failed_notification_is_not_retried(gateway_server, merchant_client, merchant_receiver):
    merchant_receiver.fail_next(500)
    async with merchant_client as client:
        created = await create(client, merchant_receiver)

    delivery = await gateway_server.complete_registration(created.subscription_id, succeeded=False)

    assert [a.status for a in delivery.attempts] == [500]
    assert delivery.delivered is False
    assert merchant_receiver.failures == []


@pytest.mark.asyncio
async def test_a_notification_signed_with_another_key_is_rejected(gateway_server, merchant_client, registered_platform):
    receiver = MerchantReceiver(api_key=generate_api_key())
    async with receiver.run():
        async with merchant_client as client:
            created = await create(client, receiver)

        delivery = await gateway_server.complete_registration(created.subscription_id, succeeded=False)

    assert receiver.failures == []
    assert len(receiver.signature_errors) == 1
    assert [a.status for a in delivery.attempts] == [400]


@pytest.mark.asyncio
async def test_an_old_subscription_without_a_platform_is_notified_unsigned_and_rejected_by_default(
    gateway_server, merchant_client, merchant_receiver, registered_platform
):
    registered_platform.links_subscriptions = False
    async with merchant_client as client:
        created = await create(client, merchant_receiver)

    delivery = await gateway_server.complete_registration(created.subscription_id, succeeded=False)

    assert delivery.signature is None
    assert merchant_receiver.failures == []
    assert len(merchant_receiver.signature_errors) == 1
    assert [a.status for a in delivery.attempts] == [400]


@pytest.mark.asyncio
async def test_an_unsigned_notification_is_accepted_when_the_merchant_allows_it(
    gateway_server, merchant_client, registered_platform
):
    registered_platform.links_subscriptions = False
    receiver = MerchantReceiver(api_key=registered_platform.api_key, allow_unsigned=True)
    async with receiver.run():
        async with merchant_client as client:
            created = await create(client, receiver)

        delivery = await gateway_server.complete_registration(created.subscription_id, succeeded=False)

    [failure] = receiver.failures
    assert failure.signature_verified is False
    assert failure.subscription_id == created.subscription_id
    assert delivery.delivered is True


@pytest.mark.asyncio
async def test_allowing_unsigned_notifications_does_not_let_a_wrong_signature_through(gateway_server, merchant_client):
    receiver = MerchantReceiver(api_key=generate_api_key(), allow_unsigned=True)
    async with receiver.run():
        async with merchant_client as client:
            created = await create(client, receiver)

        delivery = await gateway_server.complete_registration(created.subscription_id, succeeded=False)

    assert receiver.failures == []
    assert len(receiver.signature_errors) == 1
    assert delivery.signature is not None
    assert [a.status for a in delivery.attempts] == [400]


@pytest.mark.asyncio
async def test_an_old_subscription_without_a_platform_gets_no_lifecycle_webhooks(
    gateway_server, merchant_client, merchant_receiver, registered_platform
):
    registered_platform.links_subscriptions = False
    async with merchant_client as client:
        created = await create(client, merchant_receiver)
    gateway_server.activate(created.subscription_id)

    delivery = await gateway_server.charge(created.subscription_id)

    assert delivery is None
    assert merchant_receiver.events == []
    assert len(gateway_server.skipped_webhooks) == 1


@pytest.mark.asyncio
async def test_an_error_url_that_is_the_webhook_url_is_pointed_to_the_right_function(
    gateway_server, merchant_client, merchant_receiver
):
    async with merchant_client as client:
        created = await client.create_subscription(**make_subscribe_args(error_url=merchant_receiver.webhook_url))

    delivery = await gateway_server.complete_registration(created.subscription_id, succeeded=False)

    assert merchant_receiver.events == [] and merchant_receiver.failures == []
    [error] = merchant_receiver.payload_errors
    assert "parse_registration_failed" in str(error)
    assert [a.status for a in delivery.attempts] == [422]


@pytest.mark.asyncio
async def test_a_webhook_url_that_is_the_error_url_is_pointed_to_the_right_function(
    gateway_server, merchant_client, merchant_receiver, registered_platform
):
    registered_platform.callback_url = merchant_receiver.error_url
    async with merchant_client as client:
        created = await create(client, merchant_receiver)
    gateway_server.activate(created.subscription_id)

    delivery = await gateway_server.charge(created.subscription_id)

    assert merchant_receiver.failures == []
    [error] = merchant_receiver.payload_errors
    assert "parse_subscription_webhook" in str(error)
    assert [a.status for a in delivery.attempts] == [422]


@pytest.mark.asyncio
async def test_a_customer_cannot_have_two_live_subscriptions_for_the_same_reference(
    gateway_server, merchant_client, merchant_receiver
):
    args = make_subscribe_args(error_url=merchant_receiver.error_url)
    async with merchant_client as client:
        first = await client.create_subscription(**args)
        await gateway_server.complete_registration(first.subscription_id)

        with pytest.raises(ConflictError):
            await client.create_subscription(**args)

        await gateway_server.cancel(first.subscription_id)
        again = await client.create_subscription(**args)

    assert again.subscription_id != first.subscription_id


@pytest.mark.asyncio
async def test_a_pending_subscription_does_not_block_a_new_one(gateway_server, merchant_client, merchant_receiver):
    args = make_subscribe_args(error_url=merchant_receiver.error_url)
    async with merchant_client as client:
        first = await client.create_subscription(**args)
        second = await client.create_subscription(**args)

    assert first.subscription_id != second.subscription_id


@pytest.mark.asyncio
async def test_a_different_reference_or_customer_is_not_a_duplicate(gateway_server, merchant_client, merchant_receiver):
    args = make_subscribe_args(error_url=merchant_receiver.error_url)
    async with merchant_client as client:
        first = await client.create_subscription(**args)
        await gateway_server.complete_registration(first.subscription_id)

        other_ref = await client.create_subscription(**{**args, "merchant_subscription_ref": generate_readable_string(10)})
        other_customer = await client.create_subscription(**{**args, "customer_email": "other-" + args["customer_email"]})

    assert len({first.subscription_id, other_ref.subscription_id, other_customer.subscription_id}) == 3


@pytest.mark.asyncio
async def test_a_registration_cannot_be_finished_twice(gateway_server, merchant_client, merchant_receiver):
    async with merchant_client as client:
        created = await create(client, merchant_receiver)
    await gateway_server.complete_registration(created.subscription_id)

    with pytest.raises(AssertionError):
        await gateway_server.complete_registration(created.subscription_id, succeeded=False)
