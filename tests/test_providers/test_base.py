"""Test base processsor"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.http import HttpRequest

from test_utils.dummy_processor import DummyProcessor
from zeitlabs_payments.exceptions import (
    CartFulfillmentError,
    DuplicateTransactionError,
    GatewayError,
    InvalidCartError,
    InvoiceError,
)
from zeitlabs_payments.helpers import get_currency
from zeitlabs_payments.models import AuditLog, Cart, CatalogueItem, Invoice, InvoiceItem, Transaction, WebhookEvent
from zeitlabs_payments.providers.base import BaseProcessor

User = get_user_model()


@pytest.fixture
def base_processor():
    """processor fixture"""
    return BaseProcessor()


@pytest.fixture
def cart():
    """cart fixture"""
    item = CatalogueItem.objects.get(sku='custom-sku-1')
    user_cart = Cart.objects.create(user=User.objects.get(id=3), status=Cart.Status.PROCESSING)
    user_cart.items.create(
        catalogue_item=item,
        original_price=item.price,
        final_price=item.price
    )
    return user_cart


def test_payment_view_raises_not_implemented(base_processor):  # pylint: disable=redefined-outer-name
    request = HttpRequest()
    with pytest.raises(NotImplementedError):
        base_processor.payment_view(cart={}, request=request)


def test_get_transaction_parameters_raises_not_implemented(base_processor):  # pylint: disable=redefined-outer-name
    request = HttpRequest()
    with pytest.raises(NotImplementedError):
        base_processor.get_transaction_parameters(cart={}, request=request)


@pytest.mark.django_db
def test_get_cart_valid_and_invalid(base_processor, cart):  # pylint: disable=redefined-outer-name
    assert base_processor.get_cart(cart.id).id == cart.id

    with pytest.raises(InvalidCartError):
        base_processor.get_cart('invalid-id')

    with pytest.raises(InvalidCartError):
        base_processor.get_cart(999999)


@pytest.mark.django_db
def test_get_site_valid_and_invalid(base_processor):  # pylint: disable=redefined-outer-name
    site = Site.objects.get_current()
    assert base_processor.get_site(site.id).id == site.id

    with pytest.raises(GatewayError):
        base_processor.get_site('invalid-id')

    with pytest.raises(GatewayError):
        base_processor.get_site(999999)


@pytest.mark.django_db
def test_create_invoice_raises_for_non_paid_cart(base_processor, cart):  # pylint: disable=redefined-outer-name
    request = HttpRequest()
    with pytest.raises(InvoiceError):
        base_processor.create_invoice(cart, request)


@pytest.mark.django_db
def test_create_invoice_success(base_processor, cart):  # pylint: disable=redefined-outer-name
    request = HttpRequest()
    cart.status = Cart.Status.PAID
    invoice = base_processor.create_invoice(cart, request)

    assert invoice.cart == cart
    assert invoice.total == cart.total
    assert invoice.status == Invoice.InvoiceStatus.PAID
    assert invoice.invoice_number is not None

    assert InvoiceItem.objects.filter(invoice=invoice).count() == cart.items.count()


@pytest.mark.django_db
def test_get_transaction_parameters_base(cart):  # pylint: disable=redefined-outer-name
    request = MagicMock(spec=HttpRequest)
    request.site = Site.objects.get(domain='example.com')
    processor = DummyProcessor()
    result = processor.get_transaction_parameters_base(cart, request)
    assert result['user_email'] == 'user3@example.com'
    assert result['language'] == 'en'
    assert result['amount'] == 5000
    assert result['order_reference'] == f'{cart.id}-{request.site.id}'
    assert result['currency'] == cart.items.all()[0].catalogue_item.currency


@pytest.mark.django_db
def test_handle_payment_for_duplicate_transaction(cart):  # pylint: disable=redefined-outer-name
    processor = DummyProcessor()
    Transaction.objects.create(
        gateway_transaction_id='already-there',
        gateway='dummy',
        amount=5000,
    )
    with pytest.raises(DuplicateTransactionError):
        processor.handle_payment(cart, cart.user, 'anything', 'already-there', 'dummy', '5000', 'usd', 'any reason')


@pytest.mark.django_db
@pytest.mark.parametrize('record_event', [
    (True),
    (False),
])
def test_handle_payment_creates_transaction_and_webhook(cart, record_event):  # pylint: disable=redefined-outer-name
    processor = DummyProcessor()
    transaction_id = '1111'
    gateway_response = {'mode': 'test'}

    assert not Transaction.objects.filter(gateway='dummy', cart=cart).exists(), \
        'Transaction should not exist before test'
    assert cart.status == cart.Status.PROCESSING, \
        'Cart should be in PROCESSING state'

    processor.handle_payment(
        cart, cart.user, 'success', transaction_id, processor.SLUG, str(cart.total),
        get_currency(cart), 'transaction success', gateway_response, record_event
    )

    webhook_exists = WebhookEvent.objects.filter(
        gateway=processor.SLUG, event_type='direct-feedback', payload=gateway_response
    ).exists()
    assert webhook_exists == record_event, \
        f'WebhookEvent existence should be {record_event}'

    assert Transaction.objects.filter(
        gateway=processor.SLUG, cart=cart, gateway_transaction_id=transaction_id
    ).exists(), \
        'Transaction should exist after payment'

    cart.refresh_from_db()
    assert cart.status == cart.Status.PAID, \
        'Cart status should be PAID after successful payment'


@pytest.mark.django_db
@patch('zeitlabs_payments.providers.base.CART_HANDLER', new={})
def test_fulfill_cart_for_missing_cart_handler(cart):  # pylint: disable=redefined-outer-name
    processor = DummyProcessor()
    assert not AuditLog.objects.filter(action=AuditLog.AuditActions.CART_FULFILLMENT_ERROR, cart=cart).exists(), \
        'Audit log is not there with cart fullfillment error'

    with pytest.raises(CartFulfillmentError):
        processor.fulfill_cart(cart)

    assert AuditLog.objects.filter(
        action=AuditLog.AuditActions.CART_FULFILLMENT_ERROR, cart=cart
    ).exists(), \
        'Audit log should exist with cart fullfillment error as cart handler is missing for catalog item'
