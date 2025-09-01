"""Plauggable overrides to modify open edX default behaviour."""

from typing import Any
from urllib.parse import urlencode, urljoin

from django.conf import settings
from django.urls import reverse
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


def override_ecommerce_checkout_page(prev_fn: Any, self: Any, *skus: Any, **kwargs: Any) -> Any:
    """
    Override EcommerceService.get_checkout_page_url to return a custom checkout page.
    """
    if configuration_helpers.get_value('IS_ZEITLABS_PAYMENTS_ENABLED', settings.IS_ZEITLABS_PAYMENTS_ENABLED):
        query_params = {'sku': skus}
        root_url = configuration_helpers.get_value('LMS_ROOT_URL', settings.ECOMMERCE_PUBLIC_URL_ROOT)
        checkout_url = urljoin(root_url, reverse('zeitlabs_payments:checkout'))
        return f'{checkout_url}?{urlencode(query_params, doseq=True)}'

    return prev_fn(self, *skus, **kwargs)
