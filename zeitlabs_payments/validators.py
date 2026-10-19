"""Catalogue, currency and invoice-series validators. Keep free of package imports beyond ``constants``."""
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator

from zeitlabs_payments.constants import (
    _INVOICE_PREFIX_MAX_LENGTH,
    _INVOICE_PREFIX_RE,
    _PAYMENT_ORIGIN_SCHEMES,
    ISO_4217_CURRENCY_EXPONENTS,
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
)


def is_valid_invoice_prefix(prefix: Any) -> bool:
    """
    Return whether ``prefix`` can name a series of invoice numbers.

    The rule is an RFC 1123 host label in its capitalized form: uppercase letters, digits and inner hyphens,
    beginning and ending with a letter or digit, at most 63 characters. That alphabet survives everywhere an
    invoice number travels -- a receipt URL, a filename, a gateway's order reference -- without quoting or case
    folding changing what it says.

    The normalized form is what gets asked about: ``generate_invoice_number`` strips and uppercases the
    configured value first, so padding and casing are corrected rather than refused, while anything outside the
    alphabet is refused. Missing, empty and non-string values need no separate test: none of them matches.
    """
    return (
        isinstance(prefix, str) and
        len(prefix) <= _INVOICE_PREFIX_MAX_LENGTH and
        _INVOICE_PREFIX_RE.fullmatch(prefix) is not None
    )


def is_supported_currency(currency: Any) -> bool:
    """
    Return whether ``currency`` names a currency this plugin can settle in.

    This is the whole definition of a valid currency, and everywhere that asks the question asks it here. A code
    counts when its uppercase form is a key of ``ISO_4217_CURRENCY_EXPONENTS``; uppercase is the canonical form, so
    matching is case-insensitive. Nothing else is forgiven. In particular a padded code is **not** repaired on the
    caller's behalf -- ``'  SAR  '`` is a bad configuration entry, and silently accepting it hides the typo
    instead of reporting it. Missing, empty, blank and non-string values need no separate test: none of them is a
    key.
    """
    return isinstance(currency, str) and currency.upper() in ISO_4217_CURRENCY_EXPONENTS


def canonical_currency(currency: Any) -> str:
    """
    Return the canonical uppercase form of ``currency``, raising if it is not supported.

    Callers get back a plain ``str`` they can compare and store, so the canonical form is produced once here
    rather than by an ``.upper()`` repeated at every call site.
    """
    if not is_supported_currency(currency):
        raise ValidationError(
            f'Currency {currency!r} is not a supported ISO 4217 currency.'
        )
    return currency.upper()


def get_currency_exponent(currency: Any) -> int:
    """
    Return the ISO 4217 minor-unit exponent (decimal places) for a currency code.

    Raises ``ValidationError`` for anything that is not a supported currency.
    """
    return ISO_4217_CURRENCY_EXPONENTS[canonical_currency(currency)]


def validate_price_against_currency(price: Decimal, currency: Any) -> None:
    """
    Reject a price whose precision exceeds what the currency allows (C2, M25).

    SAR permits two decimal places (e.g. ``9.99``); IQD permits three
    (e.g. ``9.999``); JPY permits zero. A price with more decimals than the
    currency allows cannot be charged without rounding, which would
    introduce a discrepancy between the catalog price and the settled
    transaction amount, so it is refused here -- at the gateway it is too
    late, and the learner has already been sent there.

    A null price (M22: ``None`` means *not purchasable*, not zero) is
    accepted as-is; the catalogue already encodes that distinction.
    """
    if price is None:
        return
    exponent = get_currency_exponent(currency)
    if price == price.to_integral_value():
        decimals_used = 0
    else:
        _, _, exp = price.as_tuple()
        decimals_used = -int(exp) if isinstance(exp, int) else 0
    if decimals_used > exponent:
        raise ValidationError(
            f'Price {price} carries {decimals_used} decimal place(s) but '
            f'currency {currency} permits at most {exponent}.'
        )


def validate_price_within_column_range(price: Decimal) -> None:
    """
    Reject a price too large for the money columns to hold.

    Precision is about decimal places and this is about magnitude; a price can satisfy its currency and still not
    fit. The refusal has to happen before the value reaches the database, because what happens there is not one
    behaviour: MySQL and SQLite disagree about whether an oversized decimal is an error or something to truncate,
    and a truncated amount is a wrong amount nobody was told about.
    """
    DecimalValidator(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)(price)


def _as_decimal(price: Any) -> Decimal:
    """
    Return ``price`` as a ``Decimal``, converting from whatever was assigned to the field.

    Django does not coerce a ``DecimalField`` on assignment, so an amount reaching validation may still be an
    ``int``, a ``str`` or a ``float`` -- ``CatalogueItem(price=50)`` is ordinary and legal.

    Conversion goes through ``str`` rather than the value itself, because ``Decimal(0.1)`` copies the binary error
    faithfully and yields ``0.1000000000000000055511151231257827021181583404541015625``, while
    ``Decimal(str(0.1))`` is exactly ``0.1``: ``str`` renders the shortest decimal that round-trips the float,
    which is the number whoever entered it meant. A float carrying more decimals than its currency allows still
    arrives with them and is refused by the precision check, rather than being quietly rounded into looking
    correct.
    """
    if isinstance(price, Decimal):
        return price
    try:
        return Decimal(str(price))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValidationError(f'Price {price!r} is not a valid decimal amount.') from exc


def validate_catalogue_item_pricing(price: Any, currency: Any, valid_currency: Any) -> None:
    """
    Validate a sellable catalogue item's price and currency.

    A catalogue item is the thing the platform sells, so it must carry an amount and the unit that amount is in.
    Four rules, in the order a reviewer would apply them:

    1. **A price is required.** A null price means *not purchasable*, which is not the same as free -- zero is a
       valid price. An item without one cannot be saved as sellable, and the guard is here rather than at
       add-to-cart so the null never reaches a cart at all.
    2. **The currency must be one the plugin can settle in**, which also covers it being present at all.
    3. **It must equal the deployment currency.** A deployment trades in one currency, and ``valid_currency`` is
       what decides it; the item's own column is a checked copy, kept because the public price API publishes it.
       Validated on save rather than raised at checkout, where it is too late to do anything about it. The
       comparison is case-insensitive, because uppercase is the canonical form rather than a second currency.
    4. **The price must fit that currency's precision.**

    ``valid_currency`` is supplied by the caller -- see the module docstring. An unusable one is refused here
    rather than compared against, so a deployment that never configured it cannot save a catalogue item whose
    currency nothing has actually checked.
    """
    if price is None:
        raise ValidationError('A sellable catalogue item must have a price.')

    price = _as_decimal(price)
    validate_price_within_column_range(price)

    item_currency = canonical_currency(currency)

    if not is_supported_currency(valid_currency):
        raise ValidationError(
            'The deployment currency is not set to a supported currency, so the currency of this item cannot '
            "be validated. Set 'valid_currency' in ZEITLABS_PAYMENTS_SETTINGS to a supported ISO 4217 code "
            f'(currently {valid_currency!r}).'
        )

    if item_currency != valid_currency.upper():
        raise ValidationError(
            f'Currency {currency!r} does not match the deployment currency '
            f'{valid_currency!r}. A deployment trades in one currency.'
        )

    validate_price_against_currency(price, item_currency)


def validate_payment_origin(origin: Any) -> None:
    """
    Reject anything that is not a bare web origin: an http or https scheme, a host, and nothing after it.

    A cart records the origin it was paid on, and its receipt's QR code is built by joining a path onto that value. A
    stored path, query or fragment would be thrown away by the join, so the column would say one address while the QR
    encoded another. Credentials are refused because a receipt is not a place to print them, and a malformed port is
    refused because it yields a URL no phone can follow.

    Nothing is repaired on the caller's behalf. A trailing slash is a second spelling of one origin, and accepting both
    would let a single host sit in the column under two values that no longer compare equal.

    :param origin: The value bound for ``Cart.payment_origin``.
    :raises ValidationError: If ``origin`` is not a bare http/https origin.
    """
    if not isinstance(origin, str) or not origin:
        raise ValidationError(f'Payment origin {origin!r} must be a non-empty string.')

    parts = urlsplit(origin)

    if parts.scheme not in _PAYMENT_ORIGIN_SCHEMES:
        raise ValidationError(
            f'Payment origin {origin!r} must name an http or https scheme, not {parts.scheme!r}.'
        )

    try:
        parts.port
    except ValueError as exc:
        raise ValidationError(f'Payment origin {origin!r} does not name a valid port.') from exc

    if not parts.hostname:
        raise ValidationError(f'Payment origin {origin!r} names no host.')

    if parts.username or parts.password:
        raise ValidationError(f'Payment origin {origin!r} must not carry credentials.')

    if parts.path == '/':
        raise ValidationError(
            f'Payment origin {origin!r} must not end with a trailing slash.'
        )

    if parts.path or parts.query or parts.fragment:
        raise ValidationError(
            f'Payment origin {origin!r} must be a scheme and a host with nothing after it.'
        )
