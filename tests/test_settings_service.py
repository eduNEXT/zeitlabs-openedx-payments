"""Tests for the per-site settings access layer."""

import dataclasses
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings

from zeitlabs_payments.settings_service import ZeitLabsPluginSettings, get_settings

# Patched in place of the edx-platform site-configuration lookup. The shipped mock answers every question with
# the default it was handed, which is the fallback path; reaching for a real site override needs this instead.
SITE_CONFIGURATION_LOOKUP = 'zeitlabs_payments.settings_service.configuration_helpers.get_value'


def test_root_key_prefers_the_site_configuration_over_django_settings():
    """
    Verify that a value configured for the current site wins over the same value in Django settings.

    This is the whole reason configuration goes through this layer: a deployment serving several sites has to
    be able to answer differently per site, and reading django.conf.settings directly cannot.
    """
    with patch(SITE_CONFIGURATION_LOOKUP, return_value='site-answer') as lookup:
        assert ZeitLabsPluginSettings.get_by_root_key('LMS_ROOT_URL') == 'site-answer', \
            'The site configuration should answer first'

    assert lookup.call_args.args[0] == 'LMS_ROOT_URL', 'The site configuration should be asked for the key requested'


@override_settings(IS_ZEITLABS_PAYMENTS_ENABLED=True)
def test_root_key_falls_back_to_django_settings():
    """
    Verify that a key the site does not override is answered from Django settings.
    """
    assert ZeitLabsPluginSettings.get_by_root_key('IS_ZEITLABS_PAYMENTS_ENABLED') is True, \
        'A key absent from the site configuration should fall back to Django settings'


def test_root_key_falls_back_to_the_default_when_nothing_is_configured():
    """
    Verify that a key configured in neither place is answered with the default the caller supplied.
    """
    assert ZeitLabsPluginSettings.get_by_root_key('NO_SUCH_SETTING', 'fallback') == 'fallback', \
        'An unconfigured key should be answered with the default'
    assert ZeitLabsPluginSettings.get_by_root_key('NO_SUCH_SETTING') is None, \
        'An unconfigured key with no default should be answered with None'


def test_zeitlabs_key_reads_within_the_plugin_settings_block():
    """
    Verify that a plugin setting is read out of the ZEITLABS_PAYMENTS_SETTINGS block rather than the root.
    """
    assert ZeitLabsPluginSettings.get_by_zeitlabs_key('valid_currency', 'USD') == 'SAR', \
        'The configured value should win over the default'


@pytest.mark.parametrize(
    'block, usecase',
    [
        ({}, 'a deployment that configured the block but not this key'),
        (None, 'a deployment whose block is explicitly empty'),
    ],
)
def test_zeitlabs_key_falls_back_to_the_default(block, usecase):
    """
    Verify that a missing plugin setting is answered with the default, including when the block itself is gone.
    """
    with override_settings(ZEITLABS_PAYMENTS_SETTINGS=block):
        assert ZeitLabsPluginSettings.get_by_zeitlabs_key('valid_currency', 'USD') == 'USD', \
            f'Failed usecase: {usecase}'


@override_settings(
    ZEITLABS_PAYMENTS_SETTINGS={
        'invoice_prefix': 'INV',
        'organization_info': {'name': 'Example Org', 'vat_no': '445566', 'cr_no': '7788'},
        'valid_currency': 'USD',
        'support_url': 'https://support.example.com',
        'support_email': 'support@example.com',
        'logo_url': 'https://cdn.example.com/logo.png',
        'invoice_logo_url': 'https://cdn.example.com/invoice-logo.png',
    },
    IS_ZEITLABS_PAYMENTS_ENABLED=True,
    LMS_ROOT_URL='https://learn.example.com',
)
def test_get_settings_reads_every_field_from_configuration():
    """
    Verify that every dataclass field is populated from configuration rather than from its own default.

    The fields are compared against the dataclass itself, so a new setting fails here until it is listed with a
    configured value. Each value configured differs from its field's default, or the comparison could not tell the
    two apart.
    """
    expected = {
        'invoice_prefix': 'INV',
        'organization_info': {'name': 'Example Org', 'vat_no': '445566', 'cr_no': '7788'},
        'valid_currency': 'USD',
        'support_url': 'https://support.example.com',
        'support_email': 'support@example.com',
        'logo_url': 'https://cdn.example.com/logo.png',
        'invoice_logo_url': 'https://cdn.example.com/invoice-logo.png',
        'is_payments_enabled': True,
        'root_url': 'https://learn.example.com',
    }

    plugin_settings = get_settings()

    assert {field.name for field in dataclasses.fields(plugin_settings)} == set(expected), \
        'A new setting field must be listed here with a configured value that differs from its default'
    for name, value in expected.items():
        assert getattr(plugin_settings, name) == value, f'{name} should come from configuration, not its default'


@override_settings(LMS_ROOT_URL='https://learn.example.com')
def test_root_url_prefers_the_lms_root():
    """
    Verify that the LMS root is the address receipts and redirects are built against when it is set.
    """
    assert get_settings().root_url == 'https://learn.example.com', 'LMS_ROOT_URL should win when it is set'


def test_root_url_falls_back_to_the_ecommerce_root():
    """
    Verify that a deployment with no LMS root falls back to the ecommerce one rather than to nothing.
    """
    assert get_settings().root_url == 'test.com', 'ECOMMERCE_PUBLIC_URL_ROOT should answer when LMS_ROOT_URL is unset'


def test_root_url_says_so_loudly_when_neither_root_is_configured():
    """
    Verify that a deployment with no root configured gets a value that names the problem.

    The value is used to build absolute URLs, so a silent empty string would produce receipts addressed at
    nowhere. Something unmistakable in the URL is what gets the setting configured.

    Both roots are removed rather than set to None, because the fallback is ``getattr`` with a default: it
    answers for a setting that is absent, not for one configured to nothing.
    """
    with patch('zeitlabs_payments.settings_service.settings', SimpleNamespace()):
        root_url = get_settings().root_url

    assert 'neither LMS_ROOT_URL nor ECOMMERCE_PUBLIC_URL_ROOT is set' in root_url, \
        'An unconfigured deployment should get a value that names what is missing'
