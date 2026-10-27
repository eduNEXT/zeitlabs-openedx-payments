"""
Card-number redaction for every value the plugin persists.

Kept free of package imports beyond the leaf-level ``constants`` module so both chokepoints --
``AuditLog.log`` and ``handle_payment`` -- can import it without cycles: models imports this module,
never the other way around. The detection constants (candidate regex, length bounds, accepted MII
prefixes, separator set) live in :mod:`zeitlabs_payments.constants` so the data and the matcher sit
in the same place as the rest of the package's static configuration.
"""

import logging
from typing import Any, Match

from zeitlabs_payments.constants import _CANDIDATE_RE, _CARD_BRAND_MII, _SEPARATORS_RE

logger = logging.getLogger(__name__)


def _luhn_valid(digits: str) -> bool:
    """Return whether a digit string passes the Luhn checksum used by card numbers."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        doubled = int(char)
        if index % 2 == 1:
            doubled *= 2
            if doubled > 9:
                doubled -= 9
        total += doubled
    return total % 10 == 0


def _masked_pan(digits: str) -> str:
    """Render a card number the way the gateways mask it: BIN, four stars, last four."""
    return f'{digits[:6]}****{digits[-4:]}'


def _redact_card_numbers_in_text(text: str) -> str:
    """Mask every unmasked card number found in a string; everything else is untouched."""

    def _replace(match: Match) -> str:
        candidate = match.group(0)
        digits = _SEPARATORS_RE.sub('', candidate)
        if digits[0] not in _CARD_BRAND_MII:
            return candidate
        if not _luhn_valid(digits):
            return candidate
        logger.warning('Unmasked card number found and redacted before persistence.')
        return _masked_pan(digits)

    return _CANDIDATE_RE.sub(_replace, text)


def mask_unmasked_card_numbers(value: Any) -> Any:
    """
    Return ``value`` with every unmasked card number replaced by its masked form.

    Strings are scanned for 13-19 digit runs (spaces and dashes tolerated) that pass the Luhn checksum
    and carry a card-brand prefix; a matching number is rewritten to the same shape the gateways
    already send (BIN, stars, last four). Dictionaries and lists are traversed, so a card number
    nested anywhere inside a raw gateway response is caught. Already-masked blocks the gateways
    produce (for example ``422245****7895``) contain no digit run long enough to match and pass
    through untouched. Anything that is not a string, dict or list is stringified and scanned the
    same way: the persisted value must be serializable, so nothing is allowed to pass through
    unexamined.
    """
    if isinstance(value, dict):
        return {key: mask_unmasked_card_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_unmasked_card_numbers(item) for item in value]
    if isinstance(value, str):
        return _redact_card_numbers_in_text(value)
    return _redact_card_numbers_in_text(str(value))
