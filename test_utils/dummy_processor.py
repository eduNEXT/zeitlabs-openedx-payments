"""Dummy Payment Processor for Tests."""

from zeitlabs_payments.providers.base import BaseProcessor


class DummyProcessor(BaseProcessor):
    """Dummy Processor for testing purposes."""

    SLUG = 'dummy'
    NAME = 'Dummy'
    CHECKOUT_TEXT = 'Pay with Dummy'

    def get_transaction_parameters_base(self, cart, request):  # pylint: disable=useless-parent-delegation
        """Fake."""
        return super().get_transaction_parameters_base(cart, request)

    def get_transaction_parameters(self, cart, request=None, use_client_side_checkout=False, **kwargs):
        """Fake."""
        return {}

    def payment_view(self, cart, request=None, use_client_side_checkout=False, **kwargs):
        """Fake."""
        return None
