"""Tests for the static currency constants."""

import pytest

from zeitlabs_payments.constants import ISO_4217_CURRENCY_EXPONENTS, ISO_4217_NUMERIC_TO_ALPHA
from zeitlabs_payments.validators import is_supported_currency

# Codes the exponents table leaves out on purpose, and why. They are real ISO 4217 entries, so nothing about
# the standard stops a well-meaning edit from adding one back; each would then be accepted as a currency the
# plugin could settle a payment in, which is what this list exists to prevent.
DELIBERATELY_UNSUPPORTED = [
    ('CLF', 'Unidad de Fomento, a unit of account rather than something payable'),
    ('UYW', 'Unidad Previsional, likewise a unit of account'),
    ('XAU', 'gold'),
    ('XAG', 'silver'),
    ('XPT', 'platinum'),
    ('XPD', 'palladium'),
    ('XDR', 'IMF special drawing rights'),
    ('XTS', 'the code reserved for testing'),
    ('XXX', 'the code meaning no currency at all'),
    ('XSU', 'the Sucre, a unit of account between central banks'),
    ('XBA', 'a European composite unit'),
    ('XBB', 'a European monetary unit'),
    ('XBC', 'a European unit of account'),
    ('XBD', 'a second European unit of account'),
    ('MGA', 'the ariary, a base-5 currency this plugin does not support'),
    ('MRU', 'the ouguiya, likewise base-5'),
]


def test_currency_exponents_are_well_formed():
    """
    Verify that every exponents entry is an uppercase three-letter code mapped to a minor-unit count.

    The table is the whole definition of a settleable currency, and a typo in it is something the dict will
    serve happily rather than refuse.
    """
    for alpha_code, exponent in ISO_4217_CURRENCY_EXPONENTS.items():
        assert len(alpha_code) == 3 and alpha_code.isalpha() and alpha_code.isupper(), \
            f'key {alpha_code!r} is not an uppercase three-letter code'
        assert isinstance(exponent, int) and 0 <= exponent <= 3, \
            f'{alpha_code} maps to {exponent!r}, which is not a minor-unit count between 0 and 3'


@pytest.mark.parametrize('alpha_code, usecase', DELIBERATELY_UNSUPPORTED)
def test_currency_exponents_leave_out_what_cannot_be_paid(alpha_code, usecase):
    """
    Verify that codes excluded on purpose stay excluded, so none of them becomes a settleable currency.
    """
    assert alpha_code not in ISO_4217_CURRENCY_EXPONENTS, f'Failed usecase: {usecase}'


@pytest.mark.parametrize(
    'alpha_code, usecase',
    [
        ('SAR', 'the currency these tests deploy in'),
        ('IQD', 'a three-decimal dinar'),
        ('JPY', 'a currency with no minor unit'),
        ('USD', 'the most ordinary two-decimal currency there is'),
        ('EUR', 'a second ordinary two-decimal currency'),
    ],
)
def test_currency_exponents_carry_the_currencies_the_plugin_settles_in(alpha_code, usecase):
    """
    Verify that the currencies this plugin actually trades in are present, so the exclusions above are not
    satisfied by a table that excludes everything.
    """
    assert alpha_code in ISO_4217_CURRENCY_EXPONENTS, f'Failed usecase: {usecase}'


def test_numeric_register_translates_only_to_supported_currencies():
    """
    Verify that every entry in ISO_4217_NUMERIC_TO_ALPHA lands on a currency the plugin can settle.

    A translation that ends in a canonical_currency rejection is a register inconsistency, not a feature: the
    register and the exponents table must agree, or a gateway value that translates 'successfully' dies one line
    later with a confusing error.
    """
    for numeric_code, alpha_code in ISO_4217_NUMERIC_TO_ALPHA.items():
        assert is_supported_currency(alpha_code), \
            f'{numeric_code} translates to {alpha_code}, which is not a supported currency'


def test_numeric_register_keys_and_values_are_well_formed():
    """
    Verify that the register keys are three-digit strings and the values are uppercase three-letter alpha codes. A
    malformed entry is a typo the dict will happily serve; the test is the tripwire.
    """
    for numeric_code, alpha_code in ISO_4217_NUMERIC_TO_ALPHA.items():
        assert len(numeric_code) == 3 and numeric_code.isdigit(), \
            f'key {numeric_code!r} is not a three-digit string'
        assert len(alpha_code) == 3 and alpha_code.isalpha() and alpha_code.isupper(), \
            f'value {alpha_code!r} for key {numeric_code} is not an uppercase three-letter code'


def test_numeric_register_translates_532_to_the_currency_that_replaced_the_guilder():
    """
    Verify that 532 reads as XCG rather than ANG, which it stopped meaning when the guilder was withdrawn.

    A gateway returning 532 today means the Caribbean guilder. Translating it to a withdrawn code would put a
    currency on the transaction row that the write path then refuses.
    """
    assert ISO_4217_NUMERIC_TO_ALPHA['532'] == 'XCG', '532 should translate to the currency that replaced ANG'
    assert 'ANG' not in ISO_4217_NUMERIC_TO_ALPHA.values(), 'The withdrawn guilder should be nothing to translate to'
