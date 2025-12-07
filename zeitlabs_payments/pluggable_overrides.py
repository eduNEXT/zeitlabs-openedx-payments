"""Plauggable overrides to modify open edX default behaviour."""

from typing import Any
from urllib.parse import urlencode, urljoin

from django.urls import reverse

from zeitlabs_payments.helpers import get_settings


def override_ecommerce_checkout_page(prev_fn: Any, self: Any, *skus: Any, **kwargs: Any) -> Any:
    """
    Override EcommerceService.get_checkout_page_url to return a custom checkout page.
    """
    if get_settings().is_payments_enabled:
        query_params = {'sku': skus}
        checkout_url = urljoin(get_settings().root_url, reverse('zeitlabs_payments:checkout'))
        return f'{checkout_url}?{urlencode(query_params, doseq=True)}'

    return prev_fn(self, *skus, **kwargs)
