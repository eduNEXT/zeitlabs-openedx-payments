"""Tests for the standalone validators."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from zeitlabs_payments.validators import (
    canonical_currency,
    get_currency_exponent,
    is_supported_currency,
    is_valid_invoice_prefix,
    validate_catalogue_item_pricing,
    validate_payment_origin,
    validate_price_against_currency,
    validate_price_within_column_range,
)


@pytest.mark.parametrize(
    'prefix, usecase',
    [
        ('DEV', 'plain letters'),
        ('A', 'a single character'),
        ('X1', 'letters and digits'),
        ('123', 'digits alone, which RFC 1123 allows a label to begin with'),
        ('DEV-EU', 'an inner hyphen'),
        ('A-1-B', 'several inner hyphens'),
        ('A' * 63, 'the longest label allowed'),
    ],
)
def test_is_valid_invoice_prefix_accepts_a_capitalized_label(prefix, usecase):
    """
    Verify that a capitalized RFC 1123 label is accepted as a series name.
    """
    assert is_valid_invoice_prefix(prefix) is True, f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'prefix, usecase',
    [
        ('', 'nothing at all'),
        ('-DEV', 'a leading hyphen'),
        ('DEV-', 'a trailing hyphen, which would leave the series named by nothing'),
        ('DE_V', 'an underscore'),
        ('DE V', 'an inner space'),
        ('DEV.EU', 'a dot, which separates labels rather than belonging to one'),
        ('dev', 'lowercase, which the caller normalizes before asking'),
        ('DÉV', 'a letter outside ASCII'),
        ('A' * 64, 'one character past the longest label allowed'),
        (None, 'no value at all'),
        (123, 'a value that is not a string'),
    ],
)
def test_is_valid_invoice_prefix_refuses_anything_else(prefix, usecase):
    """
    Verify that anything outside a capitalized RFC 1123 label is refused.
    """
    assert is_valid_invoice_prefix(prefix) is False, f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'origin, usecase',
    [
        ('https://learn.example.com', 'a plain https origin'),
        ('http://localhost:18000', 'plain HTTP on an explicit port, as a devstack answers'),
        ('https://learn.example.com:8443', 'https on a non-default port'),
        ('http://127.0.0.1:8000', 'an address rather than a name'),
    ],
)
def test_validate_payment_origin_accepts_a_bare_origin(origin, usecase):
    """
    Verify that a scheme and a host with nothing after them is accepted as a payment origin.
    """
    assert validate_payment_origin(origin) is None, f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'origin, usecase',
    [
        ('', 'nothing at all'),
        (None, 'no value at all'),
        (123, 'a value that is not a string'),
        ('learn.example.com', 'a host carrying no scheme'),
        ('ftp://learn.example.com', 'a scheme no learner opens a receipt with'),
        ('javascript:alert(1)', 'a scheme that names no location at all'),
        ('https://', 'a scheme naming no host'),
        ('https://learn.example.com/', 'a trailing slash, which is a second spelling of one origin'),
        ('https://learn.example.com/payment/v1/', 'a path the receipt join would discard'),
        ('https://learn.example.com?utm=x', 'a query string'),
        ('https://learn.example.com#top', 'a fragment'),
        ('https://buyer:secret@learn.example.com', 'credentials that do not belong on a receipt'),
        ('https://learn.example.com:port', 'a port that is not a number'),
    ],
)
def test_validate_payment_origin_refuses_anything_else(origin, usecase):
    """
    Verify that anything other than a bare http or https origin is refused, naming the value it refused.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_payment_origin(origin)

    assert 'Payment origin' in str(refusal.value), f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'currency, usecase',
    [
        ('SAR', 'the canonical uppercase form'),
        ('sar', 'lowercase, which is the same currency spelled differently'),
        ('Iqd', 'mixed case'),
        ('JPY', 'a currency with no minor unit'),
    ],
)
def test_is_supported_currency_accepts_a_settleable_code(currency, usecase):
    """
    Verify that a code the plugin can settle in is accepted whatever case it arrives in.
    """
    assert is_supported_currency(currency) is True, f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'currency, usecase',
    [
        ('', 'nothing at all'),
        (None, 'no value at all'),
        (682, 'the numeric code rather than the alphabetic one'),
        ('XYZ', 'three letters that name no currency'),
        ('  SAR  ', 'padding, which marks a typo in configuration rather than a currency'),
        ('CLF', 'a unit of account, which is never payable'),
        ('XAU', 'a precious metal, which is not a currency'),
        ('MGA', 'a base-5 currency, which this plugin does not support'),
    ],
)
def test_is_supported_currency_refuses_anything_else(currency, usecase):
    """
    Verify that anything the plugin cannot settle in is refused, including codes ISO 4217 itself lists.
    """
    assert is_supported_currency(currency) is False, f'Failed usecase: {usecase}'


def test_canonical_currency_returns_the_uppercase_form():
    """
    Verify that a supported currency comes back uppercased, so callers compare and store one spelling.
    """
    assert canonical_currency('sar') == 'SAR', 'A lowercase code should be canonicalized rather than refused'
    assert canonical_currency('SAR') == 'SAR', 'A code already canonical should come back unchanged'


def test_canonical_currency_refuses_an_unsupported_currency():
    """
    Verify that an unsupported currency raises rather than being passed through uppercased.
    """
    with pytest.raises(ValidationError) as refusal:
        canonical_currency('XYZ')

    assert 'not a supported ISO 4217 currency' in str(refusal.value), 'The refusal should name what was wrong'


@pytest.mark.parametrize(
    'currency, expected, usecase',
    [
        ('JPY', 0, 'a currency with no minor unit'),
        ('KRW', 0, 'a second currency with no minor unit'),
        ('USD', 2, 'the usual two decimal places'),
        ('SAR', 2, 'the deployment currency of these tests'),
        ('IQD', 3, 'a three-decimal dinar'),
        ('KWD', 3, 'a second three-decimal dinar'),
        ('jpy', 0, 'lowercase, which names the same currency'),
    ],
)
def test_get_currency_exponent_returns_the_minor_unit(currency, expected, usecase):
    """
    Verify that a currency's exponent is the number of decimal places it may be quoted to.
    """
    assert get_currency_exponent(currency) == expected, f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'currency, usecase',
    [
        ('XYZ', 'three letters that name no currency'),
        ('CLF', 'a unit of account, which is never payable'),
        ('XAU', 'a precious metal, which is not a currency'),
        ('', 'nothing at all'),
        (None, 'no value at all'),
        (368, 'the numeric code rather than the alphabetic one'),
    ],
)
def test_get_currency_exponent_refuses_anything_unsupported(currency, usecase):
    """
    Verify that asking for the precision of a currency the plugin cannot settle in raises.
    """
    with pytest.raises(ValidationError) as refusal:
        get_currency_exponent(currency)

    assert 'not a supported ISO 4217 currency' in str(refusal.value), f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'currency, price, usecase',
    [
        ('SAR', Decimal('9.99'), 'exactly the two decimals SAR permits'),
        ('SAR', Decimal('9.9'), 'fewer decimals than permitted'),
        ('SAR', Decimal('9'), 'no decimals at all'),
        ('IQD', Decimal('9.999'), 'exactly the three decimals IQD permits'),
        ('IQD', Decimal('9.99'), 'fewer decimals than the dinar permits'),
        ('JPY', Decimal('100'), 'an integer amount in a currency with no minor unit'),
        ('JPY', Decimal('100.0'), 'a trailing zero, which quotes no minor unit'),
        ('USD', Decimal('19.95'), 'the usual two decimals'),
        ('USD', None, 'no price at all, which means not purchasable rather than zero'),
    ],
)
def test_validate_price_against_currency_accepts_a_quotable_amount(currency, price, usecase):
    """
    Verify that an amount the currency can actually be quoted in is accepted.
    """
    assert validate_price_against_currency(price, currency) is None, f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'currency, price, usecase',
    [
        ('SAR', Decimal('9.999'), 'one decimal more than SAR permits'),
        ('SAR', Decimal('0.355'), 'a fraction of a halala'),
        ('IQD', Decimal('0.0001'), 'one decimal more than the dinar permits'),
        ('JPY', Decimal('100.1'), 'a decimal in a currency that has no minor unit'),
        ('USD', Decimal('19.950'), 'a written-out third decimal, which cannot be charged'),
    ],
)
def test_validate_price_against_currency_refuses_an_unchargeable_amount(currency, price, usecase):
    """
    Verify that an amount carrying more decimals than its currency allows is refused, naming the currency.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_price_against_currency(price, currency)

    assert currency in str(refusal.value), f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'price, usecase',
    [
        (Decimal('0'), 'free, which is a price'),
        (Decimal('999999999.999'), 'the largest amount the money columns hold'),
    ],
)
def test_validate_price_within_column_range_accepts_a_storable_amount(price, usecase):
    """
    Verify that an amount the money columns can hold passes the magnitude check.
    """
    assert validate_price_within_column_range(price) is None, f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'price, usecase',
    [
        (Decimal('1000000000.000'), 'one minor unit past what the money columns hold'),
        (Decimal('1000000000000'), 'an amount far past the column width'),
    ],
)
def test_validate_price_within_column_range_refuses_an_unstorable_amount(price, usecase):
    """
    Verify that an amount too large for the money columns is refused before a database gets to truncate it.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_price_within_column_range(price)

    assert 'digits' in str(refusal.value), f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'price, usecase',
    [
        (50, 'an int, which is an ordinary way to set a price'),
        ('9.99', 'a numeric string, which is what a form submits'),
        (Decimal('9.99'), 'a Decimal, which needs no conversion'),
        (0, 'free, which is a price rather than an absent one'),
    ],
)
def test_validate_catalogue_item_pricing_accepts_a_sellable_item(price, usecase):
    """
    Verify that a price in the deployment currency is accepted however the caller spelled the amount.

    Django does not coerce a ``DecimalField`` on assignment, so an ``int`` or a ``str`` reaches validation
    untouched. Both are legal, which is also what keeps the refusal tests below honest: a validator that
    refused everything would fail here.
    """
    assert validate_catalogue_item_pricing(price, 'SAR', 'SAR') is None, f'Failed usecase: {usecase}'


def test_validate_catalogue_item_pricing_compares_currencies_case_insensitively():
    """
    Verify that the item and the deployment agree on a currency whichever case each is spelled in.
    """
    assert validate_catalogue_item_pricing(50, 'sar', 'SAR') is None, 'A lowercase item currency is the same currency'
    assert validate_catalogue_item_pricing(50, 'SAR', 'sar') is None, 'A lowercase deployment currency likewise'


def test_validate_catalogue_item_pricing_refuses_a_missing_price():
    """
    Verify that a null price is refused, because not purchasable is not the same as free.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_catalogue_item_pricing(None, 'SAR', 'SAR')

    assert 'must have a price' in str(refusal.value), 'The refusal should say a price is required'


@pytest.mark.parametrize(
    'price, usecase',
    [
        ('not-a-number', 'a string that is not a number at all'),
        ('', 'an empty string'),
        ([50], 'a value of a type that cannot express an amount'),
    ],
)
def test_validate_catalogue_item_pricing_refuses_an_unconvertible_price(price, usecase):
    """
    Verify that a price which cannot be read as a decimal fails as a validation error rather than crashing.

    Anything that is not a number has to fail as something the admin can render, not as an unhandled exception
    on the way to the database.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_catalogue_item_pricing(price, 'SAR', 'SAR')

    assert 'not a valid decimal amount' in str(refusal.value), f'Failed usecase: {usecase}'


def test_validate_catalogue_item_pricing_refuses_a_price_too_large_for_the_column():
    """
    Verify that an amount the money columns cannot hold is refused here, before any database sees it.
    """
    with pytest.raises(ValidationError):
        validate_catalogue_item_pricing(Decimal('1000000000.000'), 'SAR', 'SAR')


@pytest.mark.parametrize(
    'currency, usecase',
    [
        (None, 'no currency at all'),
        ('', 'nothing at all'),
        ('XYZ', 'three letters that name no currency'),
    ],
)
def test_validate_catalogue_item_pricing_refuses_an_unsupported_item_currency(currency, usecase):
    """
    Verify that an item priced in something the plugin cannot settle in is refused.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_catalogue_item_pricing(50, currency, 'SAR')

    assert 'not a supported ISO 4217 currency' in str(refusal.value), f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'valid_currency, usecase',
    [
        (None, 'a deployment that never configured a currency'),
        ('', 'a deployment whose currency is set to nothing'),
        ('XYZ', 'a deployment configured with three letters that name no currency'),
    ],
)
def test_validate_catalogue_item_pricing_refuses_an_unusable_deployment_currency(valid_currency, usecase):
    """
    Verify that an unusable deployment currency is refused rather than compared against.

    Comparing against it would let an item through whose currency nothing has actually checked.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_catalogue_item_pricing(50, 'SAR', valid_currency)

    assert 'deployment currency is not set' in str(refusal.value), f'Failed usecase: {usecase}'


def test_validate_catalogue_item_pricing_refuses_a_currency_the_deployment_does_not_trade_in():
    """
    Verify that an item priced in a supported currency other than the deployment's is refused.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_catalogue_item_pricing(50, 'USD', 'SAR')

    assert 'A deployment trades in one currency' in str(refusal.value), 'The refusal should say why'


def test_validate_catalogue_item_pricing_refuses_a_price_the_currency_cannot_be_quoted_in():
    """
    Verify that the precision rule is applied to an item whose currency and magnitude are both fine.
    """
    with pytest.raises(ValidationError) as refusal:
        validate_catalogue_item_pricing(Decimal('9.999'), 'SAR', 'SAR')

    assert 'decimal place' in str(refusal.value), 'The refusal should say the precision was wrong'
