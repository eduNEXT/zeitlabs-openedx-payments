"""Toggles of the payments plugin."""
from edx_toggles.toggles import WaffleSwitch

# .. toggle_name: zeitlabs_payments.invoice.show_live_info
# .. toggle_implementation: WaffleSwitch
# .. toggle_default: False
# .. toggle_description: Shows every invoice's organization and learner info as get_organization_info and
#   get_learner_info answer now, instead of as stored on the invoice when it was issued, and skips
#   retire_learner_info. It changes only what an invoice shows: the info is stored when an invoice is issued either
#   way. Meant only for instances that ran the plugin before version 1.0, whose invoices were issued without the info
#   stored on them; an instance that starts on 1.0 or later never needs it.
# .. toggle_warning: Invoices issued before the info was stored on them have none, so they show no organization or
#   learner while the switch is off. Turn it on before or at the deploy that introduces it, and off once their info has
#   been migrated.
# .. toggle_use_cases: temporary
# .. toggle_creation_date: 2026-10-15
# .. toggle_target_removal_date: 2028-01-01
SHOW_LIVE_INVOICE_INFO = WaffleSwitch('zeitlabs_payments.invoice.show_live_info', __name__)
