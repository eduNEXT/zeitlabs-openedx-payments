"""Tests for the presentation-layer template tags and filters."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.utils import translation

from zeitlabs_payments.models import Invoice
from zeitlabs_payments.templatetags.zeitlab_payment_tags import format_price


def _render_filter(value, filter_name, filter_arg=None):
    """Render ``value`` through a single template filter expression."""
    expression = filter_name if filter_arg is None else f'{filter_name}:"{filter_arg}"'
    template_string = f'{{% load zeitlab_payment_tags %}}{{{{ value|{expression} }}}}'
    return Template(template_string).render(Context({'value': value}))


def _render_qr_tag(receipt_url):
    """Render the QR tag for a receipt URL, as the invoice template does."""
    tpl = Template('{% load zeitlab_payment_tags %}{% generate_invoice_qr_code receipt_url %}')
    return tpl.render(Context({'receipt_url': receipt_url}))


def test_generate_invoice_qr_code_tag():
    """Verify that the QR tag renders an inline SVG for the receipt URL it is given."""
    rendered = _render_qr_tag('https://example.com/payment/v1/invoice/12345/')

    assert rendered.startswith('<svg '), 'The rendered QR code must be an inline SVG.'
    assert 'id="qr-path"' in rendered, 'The SVG must contain the QR path element.'


@patch('zeitlabs_payments.helpers.qrcode.QRCode')
def test_generate_invoice_qr_code_encodes_exactly_the_stored_url(mock_qr_code):
    """
    Verify that the QR encodes exactly the receipt URL it is handed, unmodified.

    The invoice settles that URL against the domain it recorded, and a printed receipt cannot be reissued, so
    anything that rebuilt or adjusted the URL here would print an address the paper copy does not carry.
    """
    receipt_url = 'https://example.com/payment/v1/invoice/12345/'
    mock_qr_code.return_value.make_image.return_value.to_string.return_value = '<svg/>'

    _render_qr_tag(receipt_url)

    mock_qr_code.return_value.add_data.assert_called_once_with(receipt_url)


@pytest.mark.parametrize('receipt_url', [None, ''])
def test_generate_invoice_qr_code_renders_nothing_without_a_url(receipt_url):
    """
    Verify that an invoice with no receipt URL renders no QR code instead of raising.

    Invoices issued before the domain was recorded have none, and their receipts still have to open.
    """
    rendered = _render_qr_tag(receipt_url)

    assert rendered == '', f'A missing receipt URL must render nothing, not {rendered!r}.'


def test_invoice_url_filter():
    """Verify that the invoice_url filter returns the receipt URL path via reverse()."""
    rendered = _render_filter('INV-001', 'invoice_url')

    assert '/payment/v1/invoice/INV-001/' in rendered, 'The filter must render the invoice URL path.'


@pytest.mark.parametrize(
    'status_value,expected_label',
    [
        (Invoice.InvoiceStatus.PAID, 'Paid'),
        ('payment_pending', 'payment_pending'),
        ('unknown_status', 'unknown_status'),
    ],
)
def test_payment_status_display_filter(status_value, expected_label):
    """
    Verify that the payment_status_display filter labels an invoice status, and leaves any other value as it is.

    Order history lists invoices, so a cart-only status such as payment_pending is not one of the values it labels.
    """
    rendered = _render_filter(status_value, 'payment_status_display')

    assert expected_label in rendered, f'{status_value!r} must render its human-readable label.'


def test_currency_symbol_filter_with_valid_code():
    """Verify that the currency_symbol filter converts an ISO code to a symbol."""
    rendered = _render_filter('USD', 'currency_symbol')

    assert rendered.strip() != '', 'A valid ISO code must render some non-empty symbol.'


def test_currency_symbol_filter_with_empty_code():
    """Verify that the currency_symbol filter returns an empty string for empty input."""
    rendered = _render_filter('', 'currency_symbol')

    assert rendered.strip() == '', 'An empty code must render an empty symbol.'


@patch(
    'zeitlabs_payments.templatetags.zeitlab_payment_tags.get_language',
    return_value='xx-bogus',
)
def test_currency_symbol_filter_falls_back_on_unparseable_locale(_mock_lang):
    """Verify that currency_symbol falls back to the language prefix when Babel cannot parse the locale."""
    rendered = _render_filter('USD', 'currency_symbol')

    assert rendered.strip() != '', 'The filter must not crash on an unparseable locale.'


@patch(
    'zeitlabs_payments.templatetags.zeitlab_payment_tags.get_currency_symbol',
    side_effect=Exception('boom'),
)
def test_currency_symbol_filter_returns_code_on_symbol_lookup_failure(_mock_symbol):
    """Verify that currency_symbol returns the raw ISO code when get_currency_symbol raises."""
    rendered = _render_filter('XYZ', 'currency_symbol')

    assert rendered.strip() == 'XYZ', 'A failed symbol lookup must fall back to the raw code.'


@pytest.mark.parametrize(
    'amount,currency,expected',
    [
        (Decimal('99.000'), 'SAR', '99.00'),
        (Decimal('99.00'), 'SAR', '99.00'),
        (Decimal('99.000'), 'IQD', '99.000'),
        (Decimal('99'), 'JPY', '99'),
        (Decimal('1234.50'), 'USD', '1234.50'),
        (Decimal('0.00'), 'SAR', '0.00'),
    ],
)
def test_format_price_renders_exactly_the_currency_exponent(amount, currency, expected):
    """Verify that format_price renders exactly the currency exponent of decimal places."""
    rendered = _render_filter(amount, 'format_price', currency)

    assert rendered == expected, f'{amount} in {currency} must render as {expected}, not {rendered!r}.'


def test_format_price_renders_a_pre_upgrade_receipt_figure_unchanged():
    """Verify that an amount stored before the money-column widening still renders with two decimals."""
    rendered = format_price(Decimal('99.00'), 'SAR')

    assert rendered == '99.00', (
        'A receipt issued with two decimals must render the identical figure, never 99.000.'
    )


def test_format_price_keeps_western_digits_under_an_arabic_locale():
    """Verify that format_price renders western digits regardless of the active locale."""
    with translation.override('ar'):
        rendered = format_price(Decimal('99.00'), 'SAR')

    assert rendered == '99.00', 'Displayed money must use western digits even under an Arabic locale.'


def test_format_price_rounds_half_up_when_the_value_has_more_precision_than_the_currency():
    """Verify that format_price applies half-up rounding when a value exceeds its currency exponent."""
    rendered = format_price(Decimal('99.995'), 'SAR')

    assert rendered == '100.00', 'A three-decimal value in a two-decimal currency must round half up.'


def test_format_price_rejects_an_unsupported_currency():
    """Verify that format_price refuses a currency that is not in the ISO 4217 table."""
    with pytest.raises(ValidationError):
        format_price(Decimal('99.00'), 'ZZZ')
