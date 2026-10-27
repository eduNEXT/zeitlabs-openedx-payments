"""What an invoice says about the learner it is issued to and the organization issuing it."""
import json
from typing import Any, Callable

from edx_django_utils.plugins import pluggable_override
from openedx.core.djangoapps.user_api.models import UserRetirementRequest

from zeitlabs_payments.exceptions import InvoiceError
from zeitlabs_payments.settings_service import get_settings
from zeitlabs_payments.toggles import SHOW_LIVE_INVOICE_INFO


@pluggable_override('OVERRIDE_ZEITLABS_PAYMENTS_LEARNER_INFO')
def get_learner_info(user: Any, site: Any) -> dict:  # pylint: disable=unused-argument
    """
    Return what an invoice says about the learner it is issued to.

    Asked once, when the invoice is issued, and stored on it. The default names the learner by the name they registered
    with -- the Open edX profile name -- then by the account's first and last name. Where a deployment takes the name
    from instead, such as an identity provider's data, is its own plugin's to say: it names its replacement in the
    ``OVERRIDE_ZEITLABS_PAYMENTS_LEARNER_INFO`` setting, and the replacement is called with this function as its first
    argument, ``prev_fn``.

    :param user: The learner the invoice is issued to.
    :param site: The site the payment was made on.
    :return: ``name``, None when there is none. A replacement may add keys of its own, which a themed invoice
        template can print.
    """
    profile = getattr(user, 'profile', None)
    name = (getattr(profile, 'name', '') or user.get_full_name()).strip()
    return {'name': name or None}


@pluggable_override('OVERRIDE_ZEITLABS_PAYMENTS_ORGANIZATION_INFO')
def get_organization_info(site: Any) -> dict:  # pylint: disable=unused-argument
    """
    Return what an invoice says about the organization issuing it.

    Asked once, when the invoice is issued, and stored on it. The default answers with the ``organization_info``
    setting of the site being served: at issuance the site the payment was made on, and when an invoice is shown the
    site it was issued on, since its pages answer on no other. It hands out a copy, so a replacement building on it
    cannot change the setting itself. A deployment that takes the organization from elsewhere replaces this function
    from its own plugin through the ``OVERRIDE_ZEITLABS_PAYMENTS_ORGANIZATION_INFO`` setting, as for
    ``get_learner_info``.

    :param site: The site the payment was made on.
    :return: ``name``, ``vat_no`` and ``cr_no``, which the invoice prints when present. Other keys are stored with
        them, for a themed invoice template to print.
    """
    return dict(get_settings().organization_info)


@pluggable_override('OVERRIDE_ZEITLABS_PAYMENTS_RETIRE_LEARNER_INFO')
def retire_learner_info(info: dict, invoice: Any) -> dict:  # pylint: disable=unused-argument
    """
    Return the learner info an invoice shows once its learner has asked for their account to be retired.

    Open edX erases a retired learner's personal data from its own records, and knows nothing of what this plugin
    stored, so each time such a learner's invoice is shown, the learner info stored on it is passed through here first.
    What is stored is never changed. The default hides the name and keeps the rest. A deployment that must show the name
    on an issued invoice for as long as the law has it kept replaces this function through the
    ``OVERRIDE_ZEITLABS_PAYMENTS_RETIRE_LEARNER_INFO`` setting; the invoice is passed so the replacement can go by its
    age.

    :param info: The learner info stored on the invoice.
    :param invoice: The invoice being shown.
    :return: The learner info to show instead.
    """
    return {**info, 'name': None}


def collect_info(info_function: Callable[..., dict], *args: Any) -> dict:
    """
    Return what an info function answers, refusing an answer an invoice cannot store.

    Nothing the function raises is caught, whether the invoice is being issued or shown: an invoice never carries info
    that is damaged or missing for a failure. An invoice is numbered, kept and never reissued, so one issued without the
    organization or the learner it names would stay that way; issuing fails instead, which leaves the payment held paid
    without an invoice and the failure logged, for the code at fault to be fixed. Showing one fails the same way, rather
    than showing it without its info -- or with the name retirement was meant to hide.

    :param info_function: ``get_learner_info``, ``get_organization_info`` or ``retire_learner_info``.
    :param args: What the function is called with.
    :raises InvoiceError: When the function answers with anything but a dict that JSON stores exactly as answered.
    """
    info = info_function(*args)
    if not isinstance(info, dict):
        raise InvoiceError(f'{info_function.__name__} answered with {type(info).__name__}, not a dict')
    try:
        stored = json.loads(json.dumps(info, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise InvoiceError(f'{info_function.__name__} answered with what cannot be stored as JSON: {exc}') from exc
    # JSON turns every key into a string and every tuple into a list without complaint, and keys that read the same as
    # strings collapse into one, so what would be stored is compared with what was answered.
    if stored != info:
        raise InvoiceError(f'{info_function.__name__} answered with what JSON would store changed: {info!r}')
    return info


def get_invoice_info_context(invoice: Any, site: Any) -> dict:
    """
    Return the learner and organization info an invoice is shown with.

    That is the info stored on the invoice when it was issued, with the learner info of a learner who has asked to be
    retired passed through ``retire_learner_info``. While the ``zeitlabs_payments.invoice.show_live_info`` switch is on,
    it is what the info functions answer now instead, retirement aside, so invoices issued before the info was stored
    still show it.

    :param invoice: The invoice being shown.
    :param site: The site serving the invoice, which the info functions are asked about while the switch is on.
    """
    if SHOW_LIVE_INVOICE_INFO.is_enabled():
        return {
            'learner_info': collect_info(get_learner_info, invoice.cart.user, site),
            'organization_info': collect_info(get_organization_info, site),
        }
    learner_info = invoice.learner_info
    if learner_info and UserRetirementRequest.has_user_requested_retirement(invoice.cart.user):
        learner_info = collect_info(retire_learner_info, learner_info, invoice)
    return {
        'learner_info': learner_info,
        'organization_info': invoice.organization_info,
    }
