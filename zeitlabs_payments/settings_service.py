"""
Per-site settings access for zeitlabs_payments.

The only supported way to read configuration in this plugin. Every value is fetched through
``ZeitLabsPluginSettings``, which goes to the current site's configuration first and falls back to Django settings,
so a value can be overridden per site. Reading ``django.conf.settings`` directly bypasses that and silently makes
whatever depends on it single-site.

Keep this module free of package imports. It sits at the top of the import graph so that ``models``
and ``helpers`` can all import it directly, and anything added here risks an import cycle.
"""
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


@dataclass
class ZeitLabsPluginSettings:
    """Dataclass to hold ZeitLabs Payments plugin settings."""

    @staticmethod
    def get_by_root_key(key: str, default: Any = None) -> Any:
        """Retrieve a setting by root key with a default value."""
        return configuration_helpers.get_value(
            key,
            getattr(settings, key, default),
        )

    @staticmethod
    def get_by_zeitlabs_key(key: str, default: Any) -> Any:
        """Retrieve a setting by key with a default value."""
        site_settings = ZeitLabsPluginSettings.get_by_root_key('ZEITLABS_PAYMENTS_SETTINGS') or {}
        return site_settings.get(key, default)

    invoice_prefix: str = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_zeitlabs_key('invoice_prefix', '')
    )
    organization_info: dict = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_zeitlabs_key('organization_info', {})
    )
    is_payments_enabled: bool = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_root_key('IS_ZEITLABS_PAYMENTS_ENABLED', False)
    )
    valid_currency: str = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_zeitlabs_key('valid_currency', '')
    )
    support_url: str = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_zeitlabs_key('support_url', '')
    )
    support_email: str = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_zeitlabs_key('support_email', '')
    )
    logo_url: str = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_zeitlabs_key('logo_url', '')
    )
    invoice_logo_url: str = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_zeitlabs_key('invoice_logo_url', '')
    )
    root_url: str = field(
        default_factory=lambda: ZeitLabsPluginSettings.get_by_root_key(
            'LMS_ROOT_URL',
            ZeitLabsPluginSettings.get_by_root_key(
                'ECOMMERCE_PUBLIC_URL_ROOT',
                'ZeitLabs Payments: neither LMS_ROOT_URL nor ECOMMERCE_PUBLIC_URL_ROOT is set!'
            )
        )
    )


def get_settings() -> ZeitLabsPluginSettings:
    """Retrieve ZeitLabs Payments plugin settings."""
    return ZeitLabsPluginSettings()
