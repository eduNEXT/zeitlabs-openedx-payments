"""Payfort Views"""

import logging
from typing import Any

from django.db import transaction
from django.contrib.sites.models import Site
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from zeitlabs_payments.exceptions import InavlidCartError, GatewayError
from zeitlabs_payments.models import Cart, AuditLog, Transaction
from zeitlabs_payments.providers.payfort.exceptions import PayFortException
from zeitlabs_payments.providers.payfort.helpers import SUCCESS_STATUS, verify_response_format
from zeitlabs_payments.providers.payfort.processor import PayFort

logger = logging.getLogger(__name__)


class PayFortBaseView(View):
    """Payfort Base View."""

    @property
    def payment_processor(self) -> PayFort:
        return PayFort()

    @property
    def cart(self) -> Cart | None:
        """Retrieve the cart from the database."""
        if not self.request or not self.request.POST.get('merchant_reference'):
            return None

        reference = self.request.POST.get('merchant_reference')
        try:
            _, cart_id = reference.split('-', 1)
            return self.payment_processor.get_cart(cart_id)
        except (ValueError, InavlidCartError):
            logger.error(f'Payfort Error! merchant_reference: {reference} is invalid. Unable to get cart.')
            return None

    @property
    def site(self) -> Site | None:
        """Retrieve the site from the database."""
        if not self.request or not self.request.POST.get('merchant_reference'):
            return None

        reference = self.request.POST.get('merchant_reference')
        try:
            site_id, _ = reference.split('-', 1)
            return self.payment_processor.get_site(site_id)
        except (ValueError, GatewayError):
            logger.error(f'Payfort Error! merchant_reference: {reference} is invalid. Unable to extract site.')
            return None

    def record_audit_log(self, action: str, details: str | dict, user: get_user_model = None) -> None:
        """Record audit log"""
        AuditLog.objects.create(
            user=user,
            action=action,
            gateway=self.payment_processor.SLUG,
            details=details
        )


@method_decorator(csrf_exempt, name='dispatch')
class PayFortReturnView(PayFortBaseView):
    """
    Payfort redirection view after payment.
    """

    template_name = 'zeitlabs_payments/wait_feedback.html'
    MAX_ATTEMPTS = 24
    WAIT_TIME = 5000

    def post(self, request):
        """Handle the POST request from PayFort after processing payment page."""
        data = request.POST.dict()
        if data.get('status') == SUCCESS_STATUS:
            try:
                verify_response_format(data)
            except PayFortException:
                render(request, 'zeitlabs_payments/payment_error.html')

            data['ecommerce_transaction_id'] = data['fort_id']
            data['ecommerce_status_url'] = reverse('zeitlabs_payments:payfort-status')
            data['ecommerce_error_url'] = reverse(
                'zeitlabs_payments:payment-error',
                args=[data['fort_id']]
            )
            data['ecommerce_success_url'] = reverse(
                'zeitlabs_payments:payment-success',
                args=[data['fort_id']]
            )
            data['ecommerce_max_attempts'] = self.MAX_ATTEMPTS
            data['ecommerce_wait_time'] = self.WAIT_TIME
            return render(request=request, template_name=self.template_name, context=data)

        logger.error(
            f"Payfort payment failed! merchant_reference: {data['merchant_reference']}. "
            f"response_code: {data['response_code']}"
        )
        return render(request, 'zeitlabs_payments/payment_error.html')


@method_decorator(csrf_exempt, name='dispatch')
class PayfortFeedbackView(PayFortBaseView):
    """
    Callback endpoint for PayFort to notify about payment status.
    """

    def post(self, request: Any) -> None:
        """Handle the POST request from PayFort for payment status or feedback."""
        data = request.POST
        self.record_audit_log(action='ReceivedPayfortFeedback', details=data)
        if data.get('status') == SUCCESS_STATUS:
            verify_response_format(data)
            if self.cart.status != Cart.Status.PROCESSING:
                self.record_audit_log(
                    action='SuccessResponseForInvalidCart',
                    details=(
                        f'Inavlid cart state found during success feedback processing. Cart: {self.cart.id}'
                        f'is in state: {self.cart.status} isntead of {Cart.Status.PROCESSING}.'
                    ),
                    user=self.cart.user)
                return HttpResponse(status=200)
            self.record_audit_log(
                action='SuccessResponse',
                details=f'Success response is receieved for cart: {self.cart.id} and site: {self.site.id}.',
                user=self.cart.user
            )
            try:
                with transaction.atomic():
                    logger.info('Starting transaction record creation for PayFort callback.')
                    self.payment_processor.handle_payment(
                        cart=self.cart,
                        user=request.user if request.user.is_authenticated else None,
                        transaction_status=data['response_message'],
                        transaction_id=data['fort_id'],
                        method=data['payment_option'],
                        amount=data['amount'],
                        currency=data['currency'],
                        reason=data['acquirer_response_message'],
                        response=data
                    )
                self.payment_processor.fulfill_cart(self.cart)
                logger.info(f"Transaction for cart {self.cart.id} and fullfillment handled successfully.")
            except Exception as e:
                self.record_audit_log(
                    action='TransactionRolledBack',
                    details=(
                        f'Transaction: {data.get("fort_id")} for cart: {self.cart.id} and site: '
                        f'{self.site.id} rolled back.'
                    ),
                    user=self.cart.user
                )
                logger.error(f"Transaction failed and was rolled back: {str(e)}")
        else:
            logger.warning(f'PayFort payment is not successful. Status: {data.get("status")}, Data: {data}')
        return HttpResponse(status=200)


@method_decorator(csrf_exempt, name='dispatch')
class PayFortStatusView(PayFortBaseView):
    """View to check transaction and payment status."""

    def post(self, request):
        """Verify transaction status."""
        if not self.cart:
            return HttpResponse(status=404)

        transaction_id = request.POST.get('transaction_id')
        if not transaction_id:
            logger.error("Payfort Error! Transaction id is required to verify payment status.")
            return HttpResponse(status=404)

        if not Transaction.objects.filter(
            cart=self.cart,
            type=Transaction.TransactionType.PAYMENT,
            status='Success',
            gateway=self.payment_processor.SLUG,
            gateway_transaction_id=transaction_id,
        ).exists():
            return HttpResponse(status=204)

        return HttpResponse(status={
            Cart.Status.PAID: 200,
            Cart.Status.PROCESSING: 204,
        }.get(self.cart.status, 404))
