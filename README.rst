openedx-zeitlabs-payments
#########################

Purpose
*******

An Open edX plugin that lets learners buy courses and course bundles inside
the LMS, with no separate ecommerce service to run. It handles the cart,
checkout, invoices and enrollment, and leaves taking the payment to a payment
processor: a separate plugin that registers itself under the
``zeitlabs_payments.v1`` entry point.

It supports the Open edX releases from Redwood to Verawood.

Installation
************

Add the plugin and at least one payment processor to your Tutor
``config.yml``:

.. code-block:: yaml

    OPENEDX_EXTRA_PIP_REQUIREMENTS:
      - git+https://github.com/zeit-labs/openedx-zeitlabs-payments.git

Then rebuild the image and run the migrations:

.. code-block:: bash

    tutor images build openedx
    tutor local launch

The plugin stays off until ``IS_ZEITLABS_PAYMENTS_ENABLED`` is ``True``, in
the LMS settings or in a site's configuration.

License
*******

The code in this repository is licensed under the AGPL v3 unless otherwise
noted. See `LICENSE.txt <LICENSE.txt>`_ for details.
