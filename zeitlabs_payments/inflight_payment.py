"""What becomes of a payment still in flight when its learner comes back to buy the same item."""
import logging
import math
from datetime import datetime
from enum import Enum
from typing import Any, NamedTuple, Optional
from urllib.parse import urlencode

from django.db import IntegrityError
from django.utils.timezone import now

from zeitlabs_payments.exceptions import CartStatusError, InFlightPaymentError
from zeitlabs_payments.models import AuditLog, Cart, CatalogueItem
from zeitlabs_payments.providers.registry import get_processor

logger = logging.getLogger(__name__)


class Resolution(Enum):
    """The ways a payment still open can be resolved."""

    # Its order is known and its processor waits on it: the learner goes back to that waiting page.
    RESUME = 'resume'
    # Its order cannot be asked about, and its payment session may still be running: the learner waits it out.
    IN_PROGRESS = 'in_progress'
    # Its order cannot be asked about and its payment session lapsed: the cart expired, and a new one may be made.
    EXPIRED = 'expired'
    # Nothing can be asked or concluded about it: the learner is refused, as before in-flight payments were resolved.
    BLOCKED = 'blocked'


class InFlightPayment(NamedTuple):
    """How an in-flight payment is resolved, and what the learner is sent to or told."""

    resolution: Resolution
    cart: Cart
    # The waiting page to resume on, for RESUME.
    waiting_page_url: Optional[str] = None
    # When the payment session runs out, for IN_PROGRESS; None when it is not known.
    retry_after: Optional[datetime] = None


def resolve_inflight_payment(cart: Cart) -> InFlightPayment:
    """
    Decide what becomes of a cart whose payment is open, now that its learner wants to buy the same item again.

    The order the gateway holds for the cart is looked for first, and the learner sent back to its waiting page, where
    the status view settles, declines or keeps waiting on it as on their first return. A cart whose order cannot be
    asked about is judged by its age instead: while its payment session may still be running the learner is asked to
    wait, so as not to pay twice; once it has lapsed the cart is expired and the learner may buy the item again.

    :param cart: The in-flight cart: processing, or awaiting payment, with its gateway recorded.
    """
    try:
        processor = get_processor(cart.gateway)
    except ValueError:
        logger.error(f'Cart {cart.id} was handed to {cart.gateway!r}, which is no longer registered.')
        return InFlightPayment(Resolution.BLOCKED, cart)

    if not cart.gateway_order_id:
        gateway_order_id = processor.find_gateway_order_id(cart)
        if gateway_order_id:
            try:
                cart.record_gateway_order(cart.gateway, gateway_order_id)
            except (CartStatusError, IntegrityError) as exc:
                logger.warning(f'Order {gateway_order_id} found for cart {cart.id} but not recorded: {exc}')

    if cart.gateway_order_id:
        waiting_page_url = _waiting_page_url(processor, cart.gateway_order_id)
        if waiting_page_url:
            return InFlightPayment(Resolution.RESUME, cart, waiting_page_url=waiting_page_url)

    session_end = processor.get_session_end(cart)
    if session_end is None or now() < session_end:
        return InFlightPayment(Resolution.IN_PROGRESS, cart, retry_after=session_end)

    if cart.status != Cart.Status.PROCESSING:
        # The gateway answered about it at least once, so money may have moved: never given up on unasked.
        return InFlightPayment(Resolution.BLOCKED, cart)
    try:
        cart.change_status(Cart.Status.EXPIRED, processor=processor, action=AuditLog.AuditActions.PAYMENT_EXPIRED)
    except CartStatusError as exc:
        logger.info(f'Cart {cart.id} was not expired, another request moved it first: {exc}')
        return InFlightPayment(Resolution.IN_PROGRESS, cart)
    return InFlightPayment(Resolution.EXPIRED, cart)


def _waiting_page_url(processor: Any, gateway_order_id: str) -> Optional[str]:
    """
    Return the processor's waiting page for the order -- its return view, reached as its gateway's redirect reaches it.

    None when the processor names no return view or no parameter for the order id, since then there is no page to
    send the learner back to.
    """
    if not (processor.RETURN_VIEW and processor.GATEWAY_ORDER_ID_PARAM):
        return None
    return f'{processor.get_return_url()}?{urlencode({processor.GATEWAY_ORDER_ID_PARAM: gateway_order_id})}'


def create_cart_resolving_inflight_payments(
    handler: Any, user: Any, catalogue_item: CatalogueItem,
) -> tuple[Optional[Cart], Optional[InFlightPayment]]:
    """
    Create a cart holding the item, first resolving any payment for the same item that is still open.

    Each in-flight cart found is resolved in turn. One that expires leaves the way clear, and creating the cart is tried
    again; any other resolution is returned for the caller to act on, and no cart is made.

    :param handler: The cart handler for the item's type.
    :param user: The learner buying the item.
    :param catalogue_item: The item to buy.
    :return: The new cart and None, or None and the in-flight payment the learner has to be told about.
    :raises InvalidCartError: When the item cannot be added for any other reason.
    """
    while True:
        try:
            return handler.validate_item_and_create_cart(user, catalogue_item), None
        except InFlightPaymentError as exc:
            inflight_payment = resolve_inflight_payment(exc.cart)
            if inflight_payment.resolution != Resolution.EXPIRED:
                return None, inflight_payment


def waiting_time(moment: Optional[datetime]) -> dict:
    """
    Return how long from now until the moment, as the page words it: whole hours, or whole minutes under an hour.

    Rounded up and never below one, so the learner is not told to try again before they may. Empty when there is no
    moment, which the page words as later.
    """
    if moment is None:
        return {}
    minutes = max(1, math.ceil((moment - now()).total_seconds() / 60))
    if minutes < 60:
        return {'minutes': minutes}
    return {'hours': math.ceil(minutes / 60)}
