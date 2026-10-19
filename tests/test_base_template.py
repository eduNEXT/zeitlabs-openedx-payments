"""
Tests for the shared learner page skeleton (``zeitlabs_payments/base.html``).

The skeleton owns what every learner page used to declare for itself: the body class, the styles
include, the writing direction, and the support region that reads branding from plugin settings.
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import override_settings
from django.urls import reverse
from django.utils import translation

from zeitlabs_payments.models import Cart, Invoice, Transaction

User = get_user_model()

CHILD_TEMPLATE = (
    '{% extends "zeitlabs_payments/base.html" %}'
    '{% block page_class %}status-page{% endblock %}'
    '{% block page_content %}<p>Hello</p>{% endblock %}'
)


def _render_child():
    """Render a minimal child of the shared skeleton."""
    return Template(CHILD_TEMPLATE).render(Context({}))


def _declared_directions(markup):
    """
    Return the ``dir`` attribute values the rendered markup declares.

    The learner stylesheet names ``[dir="ltr"]``/``[dir="rtl"]`` in its selectors, so a raw substring
    count would also count stylesheet text. Only attribute declarations count here.
    """
    return re.findall(r'\sdir="(ltr|rtl)"', markup)


def test_base_renders_skeleton():
    """Verify the skeleton emits the body class, one writing direction, and the child content."""
    output = _render_child()

    assert 'zeitlabs-payment' in output, 'The shared body class must come from the skeleton.'
    assert '<p>Hello</p>' in output, 'The skeleton must render the child page content.'
    assert _declared_directions(output) == ['ltr'], \
        'The skeleton must be the only place that declares the writing direction.'


def test_base_declares_rtl_for_a_bidi_language():
    """Verify the wrapper flips to RTL under a bidi language, where the child page class is not a stylesheet hook."""
    with translation.override('ar'):
        output = _render_child()

    assert _declared_directions(output) == ['rtl'], 'An Arabic page must declare its wrapper as rtl.'


@override_settings(ZEITLABS_PAYMENTS_SETTINGS={'support_url': 'https://support.example.com'})
def test_support_region_renders_from_settings():
    """Verify the shared support region renders a configured support URL."""
    output = _render_child()

    assert 'https://support.example.com' in output, 'A configured support URL must reach the page.'
    assert 'Contact Support' in output, 'The support region must label its link.'


def test_support_region_hidden_without_settings():
    """Verify the shared support region stays out of the page when no support contact is configured."""
    output = _render_child()

    assert '<div class="help-section">' not in output, 'An unconfigured support region must not render.'


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
def test_status_page_uses_shared_skeleton(client):
    """Verify a learner status page renders through the shared skeleton."""
    response = client.get(reverse('zeitlabs_payments:payment-error', args=['ORDER-98765']))

    assert response.status_code == 200
    markup = response.content.decode()
    assert 'zeitlabs-payment' in markup, 'The status page must carry the shared body class.'
    assert _declared_directions(markup) == ['ltr'], 'The status page must declare its direction once, via the skeleton.'


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
def test_checkout_uses_shared_skeleton(client):
    """Verify the checkout page renders through the shared skeleton."""
    user = User.objects.get(id=3)
    Cart.objects.create(user=user, status=Cart.Status.PENDING)
    client.force_login(user)

    response = client.get(reverse('zeitlabs_payments:checkout'))

    assert response.status_code == 200
    markup = response.content.decode()
    assert 'zeitlabs-payment' in markup, 'Checkout must carry the shared body class.'
    assert _declared_directions(markup) == ['ltr'], 'Checkout must declare its direction once, via the skeleton.'


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
@override_settings(ZEITLABS_PAYMENTS_SETTINGS={'logo_url': 'https://cdn.example.com/logo.png'})
def test_invoice_logo_renders_from_settings(client):
    """Verify the receipt takes its logo from plugin settings rather than from a context key no view provides."""
    user = User.objects.get(id=3)
    client.force_login(user)
    cart = Cart.objects.create(user=user, status=Cart.Status.PAID, payment_origin='https://learn.example.com')
    invoice = Invoice.objects.create(
        status=Invoice.InvoiceStatus.PAID,
        cart=cart,
        invoice_number='TEST-LOGO-1',
        total=100,
        gross_total=100,
        currency='SAR',
        related_transaction=Transaction.objects.create(
            cart=cart, amount=100, gateway='payfort', gateway_transaction_id='TX-LOGO'
        ),
    )

    response = client.get(
        reverse('zeitlabs_payments:invoice', args=[invoice.invoice_number]), HTTP_HOST='learn.example.com',
    )

    assert response.status_code == 200
    assert 'https://cdn.example.com/logo.png' in response.content.decode(), \
        'A configured logo URL must reach the receipt.'


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
def test_receipt_wrapper_owns_the_direction(client):
    """
    Verify the receipt puts its direction on the wrapper, not on an inner element.

    The stylesheet targets ``.receipt-wrapper[dir]`` for RTL, so the attribute has to sit on that
    element for the receipt's explicit right-alignment to apply.
    """
    user = User.objects.get(id=3)
    client.force_login(user)
    cart = Cart.objects.create(user=user, status=Cart.Status.PAID, payment_origin='https://learn.example.com')
    invoice = Invoice.objects.create(
        status=Invoice.InvoiceStatus.PAID,
        cart=cart,
        invoice_number='TEST-RTL-1',
        total=100,
        gross_total=100,
        currency='SAR',
        related_transaction=Transaction.objects.create(
            cart=cart, amount=100, gateway='payfort', gateway_transaction_id='TX-RTL'
        ),
    )

    with translation.override('ar'):
        response = client.get(
            reverse('zeitlabs_payments:invoice', args=[invoice.invoice_number]), HTTP_HOST='learn.example.com',
        )

    assert response.status_code == 200
    assert '<div class="receipt-wrapper" dir="rtl">' in response.content.decode(), \
        'The receipt must declare rtl on the wrapper the stylesheet targets.'


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
@override_settings(ZEITLABS_PAYMENTS_SETTINGS={'support_url': 'https://support.example.com'})
def test_support_region_renders_on_a_wired_page(client):
    """Verify a wired learner page renders the shared support region from settings."""
    response = client.get(reverse('zeitlabs_payments:payment-error', args=['ORDER-98765']))

    assert response.status_code == 200
    assert 'https://support.example.com' in response.content.decode(), \
        'A configured support URL must reach a wired learner page.'


@pytest.mark.parametrize(
    'template_name,page_class',
    [
        ('zeitlabs_payments/invoice_private.html', 'status-page'),
        ('zeitlabs_payments/order_history.html', 'order-history'),
    ],
)
def test_remaining_pages_use_shared_skeleton(template_name, page_class):
    """Verify every learner page the skeleton was adopted for renders through it."""
    output = Template(f'{{% extends "{template_name}" %}}').render(Context({}))

    assert f'class="{page_class}"' in output, f'{template_name} must keep its page class.'
    assert _declared_directions(output) == ['ltr'], f'{template_name} must declare its direction once.'
    assert 'zeitlabs-payment' in output, f'{template_name} must carry the shared body class.'
