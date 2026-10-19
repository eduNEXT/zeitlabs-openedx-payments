"""Common Settings"""
import os
from typing import Any

PLUGIN_TEMPLATES_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
)


def register_mako_templates_dir(settings: Any) -> None:
    """
    Put this plugin's template directory on the mako search path.

    The mako engine is configured with ``APP_DIRS: False``, so it never discovers templates inside installed
    apps and ``MAKO_TEMPLATE_DIRS_BASE`` is its entire search path. Without this entry a comprehensive theme
    can only replace one of these templates outright: a themed mako template that inherits from the name it
    overrides resolves the parent against these directories, and fails.

    The list is mutated in place on purpose. The mako engine's ``DIRS`` is that same list object, already
    resolved by the time plugin settings run, so rebinding the name here would leave the engine untouched.
    The membership test keeps the entry unique because two settings modules can share the one list.
    """
    mako_dirs = getattr(settings, 'MAKO_TEMPLATE_DIRS_BASE', None)
    if mako_dirs is None:
        return

    templates_dir = os.path.normpath(PLUGIN_TEMPLATES_DIR)
    if any(os.path.normpath(str(existing)) == templates_dir for existing in mako_dirs):
        return

    mako_dirs.append(templates_dir)


def plugin_settings(settings: Any) -> None:
    """
    plugin settings
    """
    settings.ZEITLABS_PAYMENTS_SETTINGS = getattr(
        settings,
        'ZEITLABS_PAYMENTS_SETTINGS',
        {},
    )
    settings.IS_ZEITLABS_PAYMENTS_ENABLED = getattr(
        settings,
        'IS_ZEITLABS_PAYMENTS_ENABLED',
        False,
    )
    settings.OVERRIDE_ECOMMERCE_SERVICE_CHECKOUT_PAGE = (
        'zeitlabs_payments.pluggable_overrides.override_ecommerce_checkout_page'
    )
    register_mako_templates_dir(settings)
