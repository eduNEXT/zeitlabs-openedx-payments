"""Tests for the learner and organization info an invoice is issued with."""
import math

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import override_settings
from fake_models.models import UserProfile, UserRetirementRequest
from waffle.testutils import override_switch

from zeitlabs_payments.exceptions import InvoiceError
from zeitlabs_payments.invoice_info import (
    collect_info,
    get_invoice_info_context,
    get_learner_info,
    get_organization_info,
    retire_learner_info,
)
from zeitlabs_payments.models import Cart, Invoice

User = get_user_model()

STORED_LEARNER_INFO = {'name': 'Layla Haddad'}
STORED_ORGANIZATION_INFO = {'name': 'The Key Institute LLC', 'vat_no': '445566'}


def learner_info_from_an_extension(prev_fn, user, site):
    """Replace get_learner_info the way an extension plugin would, keeping what the default answers."""
    return {**prev_fn(user, site), 'name': f'{user.username} as the identity provider names them'}


def organization_info_from_an_extension(prev_fn, site):
    """Replace get_organization_info the way an extension plugin would, adding to what the default answers."""
    return {**prev_fn(site), 'cr_no': '7788'}


def retire_keeping_the_name(prev_fn, info, invoice):  # pylint: disable=unused-argument
    """Replace retire_learner_info the way a deployment that must keep the name would."""
    return info


def learner_info_from_a_broken_extension(prev_fn, user, site):
    """Replace get_learner_info the way a broken extension plugin would."""
    raise RuntimeError('the identity provider is down')


def retire_from_a_broken_extension(prev_fn, info, invoice):
    """Replace retire_learner_info the way a broken extension plugin would."""
    raise RuntimeError('the retention rules could not be read')


@pytest.fixture
def learner():
    """A learner with an account name and no profile."""
    return User.objects.create(username='learner', first_name='Omar', last_name='Saleh')


@pytest.mark.django_db
def test_learner_info_names_the_learner_by_their_profile_name(learner):  # pylint: disable=redefined-outer-name
    """Verify that the learner is named by the name they registered with, which Open edX keeps on the profile."""
    UserProfile.objects.create(user=learner, name='Omar Khalid Saleh')

    assert get_learner_info(learner, Site.objects.get_current()) == {'name': 'Omar Khalid Saleh'}, \
        'The learner is not named by their profile name'


@pytest.mark.django_db
def test_learner_info_falls_back_to_the_account_name(learner):  # pylint: disable=redefined-outer-name
    """Verify that a learner with no profile name is named by the account's first and last name."""
    UserProfile.objects.create(user=learner, name='')

    assert get_learner_info(learner, Site.objects.get_current())['name'] == 'Omar Saleh', \
        'A learner with an empty profile name is not named by the account'


@pytest.mark.django_db
def test_learner_info_has_no_name_for_a_learner_without_one():
    """Verify that a learner with no name anywhere has None for a name, which the invoice leaves out."""
    nameless = User.objects.create(username='nameless')

    assert get_learner_info(nameless, Site.objects.get_current())['name'] is None, 'A missing name is not None'


@pytest.mark.django_db
def test_organization_info_is_the_site_setting():
    """Verify that the organization info is the site's ``organization_info`` setting, as configured."""
    assert get_organization_info(Site.objects.get_current()) == {'name': 'test_org', 'vat_no': '112233'}, \
        'The organization info does not come from the settings'


@pytest.mark.django_db
@override_settings(ZEITLABS_PAYMENTS_SETTINGS={'invoice_prefix': 'TEST', 'valid_currency': 'SAR'})
def test_organization_info_is_empty_where_it_is_not_configured():
    """Verify that a site with no ``organization_info`` configured has an empty one, which the invoice leaves out."""
    info = get_organization_info(Site.objects.get_current())

    assert isinstance(info, dict) and not info, f'An unconfigured organization was given {info!r}'


@pytest.mark.django_db
def test_organization_info_cannot_change_the_setting_it_comes_from():
    """
    Verify that changing what the default answers, as a replacement building on it might, leaves the setting as it was
    for every invoice after.
    """
    answered = get_organization_info(Site.objects.get_current())
    answered['cr_no'] = '7788'

    assert get_organization_info(Site.objects.get_current()) == {'name': 'test_org', 'vat_no': '112233'}, \
        'Changing an answer changed the setting'


def test_retire_learner_info_empties_only_the_name():
    """
    Verify that retiring empties the stored name, keeps whatever else a replacement of get_learner_info stored, and
    leaves the dictionary it was given.
    """
    stored = {**STORED_LEARNER_INFO, 'student_no': 'S-1024'}

    retired = retire_learner_info(stored, None)

    assert retired == {'name': None, 'student_no': 'S-1024'}, 'Retiring did not empty only the name'
    assert stored['name'] == 'Layla Haddad', 'Retiring changed the dictionary it was given'


@pytest.mark.django_db
@pytest.mark.parametrize(
    'setting, call, expected',
    [
        (
            {'OVERRIDE_ZEITLABS_PAYMENTS_LEARNER_INFO': 'tests.test_invoice_info.learner_info_from_an_extension'},
            get_learner_info,
            {'name': 'learner as the identity provider names them'},
        ),
        (
            {
                'OVERRIDE_ZEITLABS_PAYMENTS_ORGANIZATION_INFO':
                    'tests.test_invoice_info.organization_info_from_an_extension',
            },
            lambda user, site: get_organization_info(site),
            {'name': 'test_org', 'vat_no': '112233', 'cr_no': '7788'},
        ),
        (
            {'OVERRIDE_ZEITLABS_PAYMENTS_RETIRE_LEARNER_INFO': 'tests.test_invoice_info.retire_keeping_the_name'},
            lambda user, site: retire_learner_info(STORED_LEARNER_INFO, None),
            STORED_LEARNER_INFO,
        ),
    ],
)
def test_each_function_can_be_replaced_from_another_plugin(
    setting, call, expected, learner,  # pylint: disable=redefined-outer-name
):
    """
    Verify that each info function answers as the replacement its override setting names, which is handed the
    default to build on -- how an extension plugin changes them without touching this one.
    """
    with override_settings(**setting):
        answer = call(learner, Site.objects.get_current())

    assert answer == expected, f'{list(setting)[0]} did not replace the function'


FAILING_ANSWERS = [
    pytest.param(RuntimeError('the identity provider is down'), RuntimeError, id='a function that raises'),
    pytest.param(['not', 'a', 'dict'], InvoiceError, id='an answer that is not a dict'),
    pytest.param({'name': object()}, InvoiceError, id='an answer that cannot be stored as JSON'),
    pytest.param({'score': math.nan}, InvoiceError, id='a number JSON has no way to write'),
    pytest.param({'score': math.inf}, InvoiceError, id='an infinity JSON has no way to write'),
    pytest.param({1: 'one'}, InvoiceError, id='a key JSON would turn into a string'),
    pytest.param({'nested': {2: 'two'}}, InvoiceError, id='a nested key JSON would turn into a string'),
    pytest.param({'pair': ('a', 'b')}, InvoiceError, id='a tuple JSON would turn into a list'),
]


def failing_with(answer):
    """Return an info function that raises the answer when it is an exception, and answers with it otherwise."""
    def fails(*args):
        if isinstance(answer, Exception):
            raise answer
        return answer
    return fails


def test_info_is_collected_as_the_function_answers():
    """Verify that what an info function answers is what is collected."""
    def answers(*args):
        return {'name': 'answered', 'args': list(args)}

    assert collect_info(answers, 1, 2) == {'name': 'answered', 'args': [1, 2]}, \
        'The answer was not collected as given'


@pytest.mark.parametrize('answer, raised', FAILING_ANSWERS)
def test_collect_info_refuses_a_function_that_fails(answer, raised):
    """
    Verify that issuing an invoice is refused when an info function fails -- raising, which is let through, or
    answering with what an invoice cannot store -- since the invoice could never be given its info later.
    """
    with pytest.raises(raised):
        collect_info(failing_with(answer))


@pytest.fixture
def issued_invoice(learner):  # pylint: disable=redefined-outer-name
    """An invoice issued to the learner, with their info and the organization's stored on it."""
    cart = Cart.objects.create(user=learner, status=Cart.Status.PAID)
    payment = cart.transactions.create(amount=100, gateway='dummy', gateway_transaction_id='TX-1')
    return Invoice.objects.create(
        status=Invoice.InvoiceStatus.PAID, invoice_number='TEST-100001',
        total=100, gross_total=100, cart=cart, related_transaction=payment,
        learner_info=STORED_LEARNER_INFO, organization_info=STORED_ORGANIZATION_INFO,
    )


@pytest.mark.django_db
def test_invoice_context_shows_the_stored_info(issued_invoice):  # pylint: disable=redefined-outer-name
    """Verify that an invoice is shown with the info stored on it when it was issued."""
    assert get_invoice_info_context(issued_invoice, Site.objects.get_current()) == {
        'learner_info': STORED_LEARNER_INFO,
        'organization_info': STORED_ORGANIZATION_INFO,
    }, 'The invoice is not shown with its stored info'


@pytest.mark.django_db
def test_invoice_context_shows_live_info_while_the_switch_is_on(
    issued_invoice,  # pylint: disable=redefined-outer-name
):
    """Verify that while the switch is on, an invoice is shown with what the info functions answer now instead."""
    with override_switch('zeitlabs_payments.invoice.show_live_info', active=True):
        context = get_invoice_info_context(issued_invoice, Site.objects.get_current())

    assert context == {
        'learner_info': {'name': 'Omar Saleh'},
        'organization_info': {'name': 'test_org', 'vat_no': '112233'},
    }, 'The invoice is not shown with the live info'


@pytest.mark.django_db
def test_invoice_context_hides_the_name_of_a_learner_who_asked_to_be_retired(
    issued_invoice, learner,  # pylint: disable=redefined-outer-name
):
    """
    Verify that the invoice of a learner who has asked to be retired is shown through retire_learner_info, which hides
    the name by default, while the info stored on the invoice stays as it was.
    """
    UserRetirementRequest.objects.create(user=learner)

    context = get_invoice_info_context(issued_invoice, Site.objects.get_current())

    assert context['learner_info'] == {'name': None}, \
        'The retired learner\'s name is shown'
    issued_invoice.refresh_from_db()
    assert issued_invoice.learner_info == STORED_LEARNER_INFO, 'Showing the invoice changed what is stored'


@pytest.mark.django_db
@override_settings(OVERRIDE_ZEITLABS_PAYMENTS_RETIRE_LEARNER_INFO='tests.test_invoice_info.retire_keeping_the_name')
def test_invoice_context_shows_a_retired_learner_as_the_deployment_decides(
    issued_invoice, learner,  # pylint: disable=redefined-outer-name
):
    """Verify that a deployment's replacement of retire_learner_info decides what a retired learner's invoice shows."""
    UserRetirementRequest.objects.create(user=learner)

    context = get_invoice_info_context(issued_invoice, Site.objects.get_current())

    assert context['learner_info'] == STORED_LEARNER_INFO, 'The replacement of retire_learner_info did not decide'


@pytest.mark.django_db
@override_settings(
    OVERRIDE_ZEITLABS_PAYMENTS_RETIRE_LEARNER_INFO='tests.test_invoice_info.retire_from_a_broken_extension',
)
def test_invoice_context_fails_when_retiring_the_info_fails(
    issued_invoice, learner,  # pylint: disable=redefined-outer-name
):
    """
    Verify that a retired learner's invoice is not shown at all when retire_learner_info fails, rather than shown with
    the stored name it was meant to hide.
    """
    UserRetirementRequest.objects.create(user=learner)

    with pytest.raises(RuntimeError, match='the retention rules could not be read'):
        get_invoice_info_context(issued_invoice, Site.objects.get_current())


@pytest.mark.django_db
@override_settings(
    OVERRIDE_ZEITLABS_PAYMENTS_LEARNER_INFO='tests.test_invoice_info.learner_info_from_a_broken_extension',
)
def test_invoice_context_fails_when_live_info_fails(issued_invoice):  # pylint: disable=redefined-outer-name
    """Verify that while the switch is on, an invoice is not shown at all when an info function fails."""
    with override_switch('zeitlabs_payments.invoice.show_live_info', active=True):
        with pytest.raises(RuntimeError, match='the identity provider is down'):
            get_invoice_info_context(issued_invoice, Site.objects.get_current())


@pytest.mark.django_db
def test_invoice_context_skips_retirement_while_the_switch_is_on(
    issued_invoice, learner,  # pylint: disable=redefined-outer-name
):
    """Verify that while the switch is on, the live info is shown as the functions answer, retirement aside."""
    UserRetirementRequest.objects.create(user=learner)

    with override_switch('zeitlabs_payments.invoice.show_live_info', active=True):
        context = get_invoice_info_context(issued_invoice, Site.objects.get_current())

    assert context['learner_info'] == {'name': 'Omar Saleh'}, \
        'The live info went through retire_learner_info'
