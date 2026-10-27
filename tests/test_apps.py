"""Tests for the apps module"""
# pylint: disable=duplicate-code
import os
from types import SimpleNamespace

from zeitlabs_payments.apps import ZeitlabsPaymentsConfig
from zeitlabs_payments.settings import common_production


def test_app_name():
    """Test that the app name is correct"""
    assert ZeitlabsPaymentsConfig.name == 'zeitlabs_payments'


def test_app_config():
    """Verify that the app is compatible with edx-platform plugins"""
    assert ZeitlabsPaymentsConfig.plugin_app == {
        'settings_config': {
            'lms.djangoapp': {
                'production': {
                    'relative_path': 'settings.common_production',
                },
            },
        },
        'url_config': {
            'lms.djangoapp': {
                'namespace': 'zeitlabs_payments',
            },
        },
    }, 'The app is not compatible with edx-platform plugins!'


def test_common_production_plugin_settings():
    """Verify that used settings contain the method plugin_settings"""
    assert hasattr(common_production, 'plugin_settings'), 'settings is missing the method plugin_settings!'


def test_plugin_settings_registers_the_mako_templates_dir():
    """Verify that plugin_settings puts the plugin's template directory on the mako search path"""
    settings = SimpleNamespace(MAKO_TEMPLATE_DIRS_BASE=['/edx/app/edxapp/edx-platform/lms/templates'])

    common_production.plugin_settings(settings)

    assert settings.MAKO_TEMPLATE_DIRS_BASE[-1] == os.path.normpath(common_production.PLUGIN_TEMPLATES_DIR), \
        'the plugin templates dir was not appended to the mako search path!'


def test_register_mako_templates_dir_mutates_the_list_in_place():
    """
    Verify that the entry lands in the list the mako engine already holds.

    The engine's ``DIRS`` is the same list object as ``MAKO_TEMPLATE_DIRS_BASE``, so replacing the list instead of
    appending to it would leave the engine with the original directories.
    """
    mako_dirs = []
    settings = SimpleNamespace(MAKO_TEMPLATE_DIRS_BASE=mako_dirs)

    common_production.register_mako_templates_dir(settings)

    assert mako_dirs == [common_production.PLUGIN_TEMPLATES_DIR], \
        'the original list object was not the one appended to!'


def test_register_mako_templates_dir_is_idempotent():
    """Verify that a second call adds no duplicate, even when the existing entry is spelled differently"""
    unnormalised = os.path.join(os.path.dirname(common_production.PLUGIN_TEMPLATES_DIR), '.', 'templates')
    settings = SimpleNamespace(MAKO_TEMPLATE_DIRS_BASE=[unnormalised])

    common_production.register_mako_templates_dir(settings)

    assert settings.MAKO_TEMPLATE_DIRS_BASE == [unnormalised], 'the templates dir was registered twice!'


def test_register_mako_templates_dir_without_the_setting():
    """Verify that a settings module with no mako engine is left untouched instead of raising"""
    settings = SimpleNamespace()

    common_production.register_mako_templates_dir(settings)

    assert not hasattr(settings, 'MAKO_TEMPLATE_DIRS_BASE'), 'the setting was created out of nothing!'
