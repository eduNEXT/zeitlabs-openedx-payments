"""
Custom Django template tags and filters for openedx-zeitlabs-payments.

Everything in this module is presentation-layer formatting: the receipt QR code, currency
symbols, invoice URLs, payment-status labels and displayed money precision. Models and
serialisers must not grow display formatting; templates use these helpers instead.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from babel.core import Locale
from babel.numbers import get_currency_symbol
from django import template
from django.urls import reverse
from django.utils.translation import get_language

from zeitlabs_payments.helpers import generate_invoice_qr_code as generate_qr_code
from zeitlabs_payments.models import Invoice
from zeitlabs_payments.settings_service import ZeitLabsPluginSettings, get_settings
from zeitlabs_payments.validators import get_currency_exponent

register = template.Library()


@register.simple_tag
def get_zeitlabs_settings() -> ZeitLabsPluginSettings:
    """Expose plugin settings (branding, support contacts) to templates."""
    return get_settings()


@register.simple_tag
def generate_invoice_qr_code(receipt_url: Optional[str]) -> str:
    """
    Generate a QR code in SVG format for the checkout receipt page.

    The URL is settled against the domain the invoice recorded when it was issued, so a printed copy can be
    verified against the live page and every later render of that invoice prints the same host. An invoice
    issued before the domain was recorded has no URL and renders without a QR.

    :param receipt_url: The invoice's absolute receipt URL, or None when it has none.
    :returns: A QR code in SVG format, rendered as a safe HTML string, or an empty string.
    """
    return generate_qr_code(receipt_url)


@register.filter
def currency_symbol(code: str) -> str:
    """
    Render a currency symbol based on the current active Django language.

    Example: ``"sar"`` -> ``"ر.س."`` when the current language is Arabic.
    """
    if not code:
        return ''

    code = str(code).upper()

    lang = get_language() or 'en'
    babel_locale = lang.replace('-', '_')

    try:
        Locale.parse(babel_locale)
    except Exception:  # pylint: disable=broad-except
        babel_locale = lang.split('-')[0] or 'en'

    try:
        return get_currency_symbol(code, locale=babel_locale)
    except Exception:  # pylint: disable=broad-except
        return code


@register.filter
def invoice_url(invoice_number: str) -> str:
    """Return the URL path for the given invoice number."""
    return reverse('zeitlabs_payments:invoice', args=[invoice_number])


@register.filter
def payment_status_display(status_value: str) -> str:
    """
    Return the human-readable label for an invoice's status, or the value itself when it names none.

    Order history lists invoices, so the status it labels is the invoice's. A cart status shares some of the values
    but not all of them, and is not what this labels.
    """
    return dict(Invoice.InvoiceStatus.choices).get(status_value, status_value)


@register.filter
def format_price(amount: Any, currency: str) -> str:
    """
    Render a money amount for display with exactly the currency's exponent of decimal places.

    The displayed precision is decided here, explicitly, from the currency -- never inherited
    from the storage column. A widened money column must not leak its third decimal into a
    receipt that was issued with two.
    """
    exponent = get_currency_exponent(currency)
    quantized = Decimal(str(amount)).quantize(Decimal(1).scaleb(-exponent), rounding=ROUND_HALF_UP)
    return format(quantized, f'.{exponent}f')
