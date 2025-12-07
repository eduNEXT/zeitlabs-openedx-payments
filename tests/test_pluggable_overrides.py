"""Test for plauggable overrides."""

from unittest.mock import Mock

from django.test import override_settings

from zeitlabs_payments.pluggable_overrides import override_ecommerce_checkout_page


def test_override_checkout_page_when_enabled_and_LMS_ROOT_URL_is_set(monkeypatch):
    """
    Test that custom checkout page is returned with LMS_ROOT_URL
    when its value is set in config
    """
    monkeypatch.setattr(
        'zeitlabs_payments.pluggable_overrides.get_settings',
        lambda: Mock(is_payment_enabled=True, root_url='http://testserver'),
    )

    skus = ['ABC123']
    result = override_ecommerce_checkout_page(lambda *a, **kw: 'should_not_be_called', None, *skus)
    assert result == 'http://testserver/checkout/v1/checkout/?sku=ABC123'


@override_settings(
    ECOMMERCE_PUBLIC_URL_ROOT='http://ecommerce.com',
)
def test_override_checkout_page_when_enabled_and_LMS_ROOT_URL_is_not_set(monkeypatch):
    """
    Test that custom checkout page is returned with Ecommerce_PUBLIC_URL_ROOT
    when LMS_ROOT_URL value is not set in config
    """
    def fake_get_value(key, default=None):
        if key == 'IS_ZEITLABS_PAYMENTS_ENABLED':
            return True
        return default

    monkeypatch.setattr('openedx.core.djangoapps.site_configuration.helpers.get_value', fake_get_value)
    skus = ['ABC123']
    result = override_ecommerce_checkout_page(lambda *a, **kw: 'should_not_be_called', None, *skus)
    assert result == 'http://ecommerce.com/checkout/v1/checkout/?sku=ABC123'


def test_override_checkout_page_when_disabled(monkeypatch):
    """
    Test that default fuction is called when plugin is disabled in config settings
    """
    monkeypatch.setattr('openedx.core.djangoapps.site_configuration.helpers.get_value', lambda key, default=None: False)
    skus = ['does-not-matter']
    result = override_ecommerce_checkout_page(
        lambda *a, **kw: 'fallback-url',
        None,
        *skus,
    )
    assert result == 'fallback-url'


def test_override_checkout_page_when_not_set(monkeypatch):
    """
    Test that default function is called when plugin is not set in config settings
    """
    monkeypatch.setattr('openedx.core.djangoapps.site_configuration.helpers.get_value', lambda key, default=None: None)
    skus = ['does-not-matter']
    result = override_ecommerce_checkout_page(lambda *a, **kw: 'fallback-url', None, *skus)
    assert result == 'fallback-url'
