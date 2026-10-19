"""Tests for the plugin's exception types."""

import inspect

import pytest

from zeitlabs_payments import exceptions
from zeitlabs_payments.exceptions import (
    CartFulfillmentError,
    CartStatusError,
    ConfigurationError,
    CurrencyMismatchError,
    DuplicateCartError,
    DuplicateTransactionError,
    GatewayError,
    InFlightPaymentError,
    InvalidCartError,
    InvoiceError,
    ResolutionError,
)

ALL_ERRORS = [
    CartFulfillmentError,
    CartStatusError,
    ConfigurationError,
    CurrencyMismatchError,
    DuplicateCartError,
    DuplicateTransactionError,
    GatewayError,
    InvalidCartError,
    InvoiceError,
    InFlightPaymentError,
    ResolutionError,
]


@pytest.mark.parametrize('error_class', ALL_ERRORS, ids=lambda cls: cls.__name__)
def test_every_error_is_raisable_and_carries_its_message(error_class):
    """
    Verify that each error can be raised and reports the message it was given.
    """
    with pytest.raises(error_class) as refusal:
        raise error_class('something went wrong')

    assert str(refusal.value) == 'something went wrong', 'The message given should be the message reported'


@pytest.mark.parametrize('error_class', ALL_ERRORS, ids=lambda cls: cls.__name__)
def test_no_error_catches_another(error_class):
    """
    Verify that the errors are siblings rather than a hierarchy, so catching one never swallows another.

    Several of these are handled at the same call site with different responses. An accidental subclass
    relationship would route one of them into the other's handler, silently.
    """
    others = [other for other in ALL_ERRORS if other is not error_class]

    assert issubclass(error_class, Exception), f'{error_class.__name__} should be an ordinary exception'
    for other in others:
        assert not issubclass(error_class, other), \
            f'{error_class.__name__} is a subclass of {other.__name__}, so handling {other.__name__} catches it too'


def test_every_exception_in_the_module_is_covered_here():
    """
    Verify that ALL_ERRORS holds every exception the module declares, so a new one cannot skip the tests above.

    The message and sibling tests are only as complete as the list they check. An exception missing from it
    could subclass another unnoticed and be routed into that one's handler.
    """
    declared = {
        obj for _, obj in inspect.getmembers(exceptions, inspect.isclass)
        if issubclass(obj, Exception) and obj is not Exception
    }

    assert declared == set(ALL_ERRORS), \
        'A new exception must join ALL_ERRORS so it gets the message and sibling-contract tests'


def test_inflight_payment_error_carries_the_inflight_cart():
    """
    Verify that the error naming an in-flight payment carries its cart, which the caller resolves.
    """
    cart = object()

    error = InFlightPaymentError('a payment is still open', cart=cart)

    assert error.cart is cart, 'The error does not carry the cart whose payment is open'


def test_cart_fulfillment_error_records_what_landed_before_it_failed():
    """
    Verify that a fulfillment failure carries the record the caller needs after the transaction has rolled back.

    The enrollment call has side effects a rollback cannot undo, so the courses that completed, the one that
    failed, the bundle they belong to and the courses the learner already held travel on the error itself, out past
    the rolled-back transaction.
    """
    error = CartFulfillmentError(
        'enrolment failed',
        landed_courses=['course-v1:org1+1+1'],
        failed_course='course-v1:org2+1+1',
        bundle_sku='BUNDLE-PRO-CERT',
        held_courses=['course-v1:org3+1+1'],
    )

    assert str(error) == 'enrolment failed', 'The message should survive the extra arguments'
    assert error.landed_courses == ['course-v1:org1+1+1'], 'The error should name the courses that had landed'
    assert error.failed_course == 'course-v1:org2+1+1', 'The error should name the course that failed'
    assert error.bundle_sku == 'BUNDLE-PRO-CERT', 'The error should name the bundle the failure belongs to'
    assert error.held_courses == ['course-v1:org3+1+1'], 'The error should name the courses the learner already held'


def test_cart_fulfillment_error_defaults_to_an_empty_record():
    """
    Verify that a failure raised without a record still offers a list to iterate rather than None.

    Callers write an audit entry from ``landed_courses`` whether or not anything landed; a None there would
    turn a fulfillment failure into a TypeError in the handler that reports it.
    """
    error = CartFulfillmentError('enrolment failed')

    assert error.landed_courses == [], 'No courses landed should read as an empty list, not as None'
    assert error.failed_course is None, 'No failing course named should read as None'
    assert error.bundle_sku is None, 'No bundle named should read as None'
    assert error.held_courses == [], 'No courses held should read as an empty list, not as None'
