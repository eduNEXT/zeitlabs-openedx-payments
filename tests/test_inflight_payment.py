"""Tests for resolving a payment still open when its learner comes back to buy the same course."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils.timezone import now

from test_utils.dummy_processor import DummyProcessor
from zeitlabs_payments.cart_handler import CART_HANDLER
from zeitlabs_payments.constants import DEFAULT_PAYMENT_SESSION_DURATION
from zeitlabs_payments.exceptions import CartStatusError
from zeitlabs_payments.inflight_payment import (
    InFlightPayment,
    Resolution,
    create_cart_resolving_inflight_payments,
    resolve_inflight_payment,
    waiting_time,
)
from zeitlabs_payments.models import AuditLog, Cart, CatalogueItem

User = get_user_model()

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures('base_data')]


def inflight_cart(status=Cart.Status.PROCESSING, gateway='dummy', gateway_order_id=None, age=timedelta(0)):
    """Return a learner's cart for a paid course, handed to the gateway the given time ago."""
    item = CatalogueItem.objects.get(sku='custom-sku-1')
    cart = Cart.objects.create(
        user=User.objects.get(id=3), status=status, gateway=gateway, gateway_order_id=gateway_order_id,
    )
    cart.items.create(catalogue_item=item, original_price=item.price, final_price=item.price)
    Cart.objects.filter(pk=cart.pk).update(updated_at=now() - age)
    cart.refresh_from_db()
    return cart


def test_a_payment_whose_order_is_known_resumes_on_its_waiting_page():
    """
    Verify that a cart whose order is known is resumed on the processor's waiting page for that order.

    The waiting page is the processor's return view, with the order id where its gateway's redirect puts it, so the
    status view settles, declines or keeps waiting on the payment exactly as on the learner's first return.
    """
    cart = inflight_cart(gateway_order_id='ORDER 1')

    resolved = resolve_inflight_payment(cart)

    assert resolved == InFlightPayment(
        Resolution.RESUME, cart, waiting_page_url=f'{DummyProcessor().get_return_url()}?orderId=ORDER+1',
    ), 'A payment whose order is known was not resumed on its waiting page'


def test_a_processor_naming_no_return_view_cannot_resume():
    """
    Verify that a processor naming no return view, or no parameter for the order id, has no waiting page to resume on.
    """
    cart = inflight_cart(gateway_order_id='ORDER-1')

    for attribute in ('RETURN_VIEW', 'GATEWAY_ORDER_ID_PARAM'):
        with patch.object(DummyProcessor, attribute, None):
            resolved = resolve_inflight_payment(cart)

        assert resolved.resolution == Resolution.IN_PROGRESS, f'A processor naming no {attribute} resumed'


def test_an_order_found_at_the_gateway_is_recorded_and_resumed():
    """
    Verify that the order of a cart that had none recorded is looked for at the gateway, recorded, and resumed.

    A gateway that opens its order only when the learner pays never named it at hand-off.
    """
    cart = inflight_cart()

    with patch.object(DummyProcessor, 'find_gateway_order_id', return_value='ORDER-9'):
        resolved = resolve_inflight_payment(cart)

    assert resolved.resolution == Resolution.RESUME, 'An order found at the gateway was not resumed'
    assert Cart.objects.get(pk=cart.pk).gateway_order_id == 'ORDER-9', 'The order found was not recorded'


def test_an_order_found_but_already_given_to_another_cart_is_not_recorded():
    """
    Verify that an order id the gateway gave another cart is not recorded here, and the cart is judged by its age.
    """
    inflight_cart(gateway_order_id='ORDER-9')
    cart = inflight_cart()

    with patch.object(DummyProcessor, 'find_gateway_order_id', return_value='ORDER-9'):
        resolved = resolve_inflight_payment(cart)

    assert Cart.objects.get(pk=cart.pk).gateway_order_id is None, 'An id belonging to another cart was recorded'
    assert resolved.resolution == Resolution.IN_PROGRESS, 'The cart was not judged by its age'


@pytest.mark.parametrize('gateway_order_id, usecase', [
    (None, 'no order recorded, and none found at the gateway'),
    ('ORDER-1', 'an order recorded, but no waiting page to resume it on'),
])
def test_a_payment_that_cannot_be_resumed_is_in_progress_while_its_session_runs(gateway_order_id, usecase):
    """
    Verify that a payment that cannot be resumed, handed off within its session, is reported in progress until then.

    The learner is asked to wait rather than pay again, since the payment may still go through.
    """
    cart = inflight_cart(gateway_order_id=gateway_order_id, age=timedelta(minutes=10))

    with patch.object(DummyProcessor, 'RETURN_VIEW', None):
        resolved = resolve_inflight_payment(cart)

    assert resolved.resolution == Resolution.IN_PROGRESS, f'Failed usecase: {usecase}'
    assert resolved.retry_after == cart.updated_at + DEFAULT_PAYMENT_SESSION_DURATION, \
        f'The time to retry is not the end of the session; usecase: {usecase}'
    assert Cart.objects.get(pk=cart.pk).status == Cart.Status.PROCESSING, f'The cart moved; usecase: {usecase}'


def test_the_processor_tells_when_its_session_ends():
    """
    Verify that a processor saying its session ended -- by time or by a status its gateway reports -- is believed.
    """
    cart = inflight_cart(age=timedelta(minutes=10))

    with patch.object(DummyProcessor, 'get_session_end', return_value=now()) as session_end:
        resolved = resolve_inflight_payment(cart)

    assert resolved.resolution == Resolution.EXPIRED, 'A cart whose session the processor says ended did not expire'
    session_end.assert_called_once_with(cart)


def test_a_session_whose_end_cannot_be_told_is_never_expired():
    """
    Verify that a payment whose session end cannot be told is in progress, with no time to retry, however old.

    Not knowing is not the same as over: expiring it could let the learner pay twice.
    """
    cart = inflight_cart(age=timedelta(days=30))

    with patch.object(DummyProcessor, 'get_session_end', return_value=None):
        resolved = resolve_inflight_payment(cart)

    assert resolved == InFlightPayment(Resolution.IN_PROGRESS, cart), 'A session of unknown end was given up on'
    assert Cart.objects.get(pk=cart.pk).status == Cart.Status.PROCESSING, 'A session of unknown end expired its cart'


def test_the_default_session_is_long():
    """
    Verify that a processor not telling its session end gives the cart a day, not minutes, before it can expire.

    Expiring too soon risks a second charge; waiting too long only delays the learner.
    """
    cart = inflight_cart(age=timedelta(hours=2))

    assert DEFAULT_PAYMENT_SESSION_DURATION == timedelta(hours=24), 'The default session is not a day'
    assert resolve_inflight_payment(cart).resolution == Resolution.IN_PROGRESS, 'A two-hour-old cart already expired'


def test_an_abandoned_payment_past_its_session_expires():
    """
    Verify that a processing cart that cannot be resumed, past its payment session, expires and says so in its trail.

    The gateway no longer takes a payment for it, so the learner is free to buy the course again.
    """
    cart = inflight_cart(age=DEFAULT_PAYMENT_SESSION_DURATION + timedelta(minutes=1))

    resolved = resolve_inflight_payment(cart)

    assert resolved.resolution == Resolution.EXPIRED, 'An abandoned payment did not expire'
    assert Cart.objects.get(pk=cart.pk).status == Cart.Status.EXPIRED, 'The cart of an abandoned payment did not expire'
    assert AuditLog.objects.filter(cart=cart, action=AuditLog.AuditActions.PAYMENT_EXPIRED).exists(), \
        'The expiry is not on the record'


def test_a_payment_the_gateway_answered_about_is_never_expired_unasked():
    """
    Verify that a cart awaiting payment, past its session and not resumable, is refused rather than expired.

    The gateway answered about it at least once, so money may have moved: only asking again can tell.
    """
    cart = inflight_cart(status=Cart.Status.PAYMENT_PENDING, age=DEFAULT_PAYMENT_SESSION_DURATION * 2)

    resolved = resolve_inflight_payment(cart)

    assert resolved.resolution == Resolution.BLOCKED, 'A payment the gateway answered about was not refused'
    assert Cart.objects.get(pk=cart.pk).status == Cart.Status.PAYMENT_PENDING, 'It was given up on unasked'


def test_a_cart_another_request_moved_while_expiring_it_is_in_progress():
    """Verify that a cart another request moved just as it was being expired is reported in progress, not expired."""
    cart = inflight_cart(age=DEFAULT_PAYMENT_SESSION_DURATION * 2)

    with patch.object(Cart, 'change_status', side_effect=CartStatusError('moved by another request')):
        resolved = resolve_inflight_payment(cart)

    assert resolved == InFlightPayment(Resolution.IN_PROGRESS, cart), 'A cart moved meanwhile was not left in progress'


def test_a_payment_to_a_processor_no_longer_registered_is_refused():
    """Verify that a cart handed to a processor no longer registered is refused, since nothing can be asked of it."""
    cart = inflight_cart(gateway='retired-gateway')

    resolved = resolve_inflight_payment(cart)

    assert resolved.resolution == Resolution.BLOCKED, 'A payment nobody can ask about went through'


def test_creating_a_cart_after_an_expired_payment_makes_the_cart():
    """
    Verify that buying a course again past an abandoned payment's session expires it and makes the new cart.
    """
    abandoned = inflight_cart(age=DEFAULT_PAYMENT_SESSION_DURATION * 2)
    item = CatalogueItem.objects.get(sku='custom-sku-1')

    cart, inflight_payment = create_cart_resolving_inflight_payments(CART_HANDLER[item.type], abandoned.user, item)

    assert inflight_payment is None, 'An expired payment was still reported open'
    assert cart is not None and cart.pk != abandoned.pk, 'No new cart was made'
    assert Cart.objects.get(pk=abandoned.pk).status == Cart.Status.EXPIRED, 'The abandoned cart did not expire'


def test_creating_a_cart_while_a_payment_is_open_makes_none():
    """Verify that buying a course again while its payment is still in progress makes no cart, and says why."""
    running = inflight_cart(age=timedelta(minutes=1))
    item = CatalogueItem.objects.get(sku='custom-sku-1')

    cart, inflight_payment = create_cart_resolving_inflight_payments(CART_HANDLER[item.type], running.user, item)

    assert cart is None, 'A second cart was made while a payment for the course was in progress'
    assert inflight_payment.resolution == Resolution.IN_PROGRESS and inflight_payment.cart == running, \
        'The payment in progress was not reported'


@pytest.mark.parametrize('seconds_ahead, wait', [
    (1, {'minutes': 1}),
    (60, {'minutes': 1}),
    (61, {'minutes': 2}),
    (-30, {'minutes': 1}),
    (59 * 60, {'minutes': 59}),
    (60 * 60, {'hours': 1}),
    (61 * 60, {'hours': 2}),
    (24 * 60 * 60, {'hours': 24}),
])
def test_waiting_time_rounds_up_in_minutes_then_hours(seconds_ahead, wait):
    """
    Verify that the time to wait is rounded up, never below one, in minutes under an hour and in hours from there.

    A learner told a day's wait in minutes would read 1440 of them.
    """
    assert waiting_time(now() + timedelta(seconds=seconds_ahead)) == wait, f'{seconds_ahead}s is not {wait}'


def test_waiting_time_of_no_moment_is_empty():
    """Verify that no moment gives no time to wait, which the page words as later."""
    assert not waiting_time(None), 'A missing moment gave a time to wait'
