"""Tests for card-number redaction."""

import logging

import pytest

from zeitlabs_payments.redaction import mask_unmasked_card_numbers


def test_masks_unmasked_pan_in_plain_text(caplog):
    """Verify that a Luhn-valid card number in plain text is replaced by the masked form and a
    warning is logged."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('paid with 4111111111111111')
    assert result == 'paid with 411111****1111'
    assert 'Unmasked card number found and redacted' in caplog.text, \
        'The redaction must be logged for audit visibility'


def test_masks_unmasked_pan_multiple_times_in_plain_text(caplog):
    """Verify that a Luhn-valid card number in plain text is replaced by the masked form and a
    warning is logged, even if it appears multiple times."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('paid with 4111111111111111. Another time 5555555555554444 is mentioned')
    assert result == 'paid with 411111****1111. Another time 555555****4444 is mentioned'
    assert 'Unmasked card number found and redacted' in caplog.text, \
        'The redaction must be logged for audit visibility'


def test_masks_pan_with_space_groups(caplog):
    """Verify that a card number grouped with spaces is detected and masked."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('paid with 4111 1111 1111 1111')
    assert result == 'paid with 411111****1111'


def test_masks_pan_with_dash_groups(caplog):
    """Verify that a card number grouped with dashes is detected and masked."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('paid with 5555-5555-5555-4444')
    assert result == 'paid with 555555****4444'


def test_leaves_gateway_masked_block_untouched(caplog):
    """Verify that the masked block the gateways already send passes through unchanged."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('paid with 422245****7895')
    assert result == 'paid with 422245****7895'
    assert caplog.text == '', 'No redaction may fire on an already-masked value'


def test_leaves_luhn_invalid_number_untouched(caplog):
    """Verify that a 16-digit string that fails the Luhn checksum is not a card number and stays."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('order 4111111111111112')
    assert result == 'order 4111111111111112'
    assert caplog.text == '', 'No redaction may fire on a Luhn-invalid number'


def test_leaves_short_digit_runs_untouched(caplog):
    """Verify that order ids and timestamps are far below the 13-digit minimum and stay."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('order 173155 at 202710')
    assert result == 'order 173155 at 202710'
    assert caplog.text == ''


def test_leaves_decimal_amounts_untouched(caplog):
    """Verify that a decimal amount is never a candidate: the dot is not a digit separator."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('amount 999999999999.000 charged')
    assert result == 'amount 999999999999.000 charged'
    assert caplog.text == ''


def test_masks_pan_nested_in_dict_and_list(caplog):
    """Verify that a card number nested anywhere inside a raw gateway response is caught."""
    payload = {
        'result': {'description': 'charged 378282246310005'},
        'items': ['pan 6011111111111117', 42, None],
    }
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers(payload)
    assert result['result']['description'] == 'charged 378282****0005'
    assert result['items'][0] == 'pan 601111****1117'
    assert result['items'][1] == '42'
    assert result['items'][2] == 'None'


def test_stringifies_non_string_values_and_scans_them(caplog):
    """Verify that numbers, booleans and None are stringified and scanned, never passed through."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers({'amount': 113850, 'paid': True, 'note': None})
    assert result == {'amount': '113850', 'paid': 'True', 'note': 'None'}, \
        'Every persisted value must be serializable and examined'
    assert caplog.text == ''


@pytest.mark.parametrize('pan, expected', [
    ('4111111111111111', '411111****1111'),  # Visa test number
    ('5555555555554444', '555555****4444'),  # Mastercard test number
    ('378282246310005', '378282****0005'),   # Amex test number (15 digits)
    ('6011111111111117', '601111****1117'),  # Discover test number
])
def test_masks_standard_test_pans(pan, expected):
    """Verify that every standard test card number is detected and masked correctly."""
    assert mask_unmasked_card_numbers(pan) == expected


def test_leaves_non_card_mii_number_untouched(caplog):
    """Verify that a Luhn-valid 16-digit run without a card-brand prefix is not a card number."""
    with caplog.at_level(logging.WARNING):
        result = mask_unmasked_card_numbers('ref 9000000000000001 issued')
    assert result == 'ref 9000000000000001 issued'
    assert caplog.text == '', 'No redaction may fire on a run without a card-brand prefix'
