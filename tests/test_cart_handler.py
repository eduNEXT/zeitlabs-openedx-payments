"""Fullment related tests."""

import re
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from common.djangoapps.course_modes.models import CourseMode
from common.djangoapps.student.models import CourseEnrollment, CourseEnrollmentException
from django.contrib.auth import get_user_model
from django.utils.timezone import now

from test_utils.dummy_processor import DummyProcessor
from zeitlabs_payments.cart_handler import BaseCartHandler, PaidCourseCartHandler, ProgramBundleCartHandler
from zeitlabs_payments.exceptions import CartFulfillmentError, InFlightPaymentError, InvalidCartError
from zeitlabs_payments.models import AuditLog, BundleCourseItem, Cart, CatalogueItem

User = get_user_model()


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
class TestBaseCartHandler:
    """
    Tests for BaseCartHandler.
    """
    strategy = BaseCartHandler()
    cart_item = MagicMock()
    user = None
    catalogue_item = None

    def setup_method(self):
        self.strategy = BaseCartHandler()
        self.cart_item = MagicMock()

    def test_validate_add_to_cart_does_nothing(self):
        """
        Should not raise anything: default implementation is empty.
        """
        # Should just run without exception
        self.strategy.validate_add_to_cart(self.user, self.catalogue_item)

    def test_fulfill_raises_not_implemented(self):
        """
        Should always raise NotImplementedError.
        """
        with pytest.raises(NotImplementedError, match='Subclasses must implement this.'):
            self.strategy.fulfill(self.cart_item, DummyProcessor())

    def test_validate_item_and_create_cart_opens_a_cart_holding_the_item(self):
        """
        Verify that a new pending cart is opened holding the catalogue item at its catalogue price.
        """
        user = get_user_model().objects.get(id=5)
        catalogue_item = CatalogueItem.objects.get(sku='custom-sku-1')

        cart = self.strategy.validate_item_and_create_cart(user, catalogue_item)

        cart_items = list(cart.items.all())
        assert cart.status == Cart.Status.PENDING, 'A newly opened cart should be pending'
        assert cart.user == user, 'The cart should belong to the user it was opened for'
        assert len(cart_items) == 1, 'The cart should hold exactly the item it was opened for'
        assert cart_items[0].catalogue_item == catalogue_item, 'The cart should hold the requested item'
        assert cart_items[0].original_price == catalogue_item.price, \
            'The item should be priced at the catalogue price it was added at'
        assert cart_items[0].final_price == catalogue_item.price, \
            'Nothing discounts an item on the way into the cart, so both prices start equal'

    def test_validate_item_and_create_cart_cancels_a_cart_left_open(self):
        """
        Verify that opening a cart cancels the user's stale pending carts, leaving one active cart.
        """
        user = get_user_model().objects.get(id=6)
        catalogue_item = CatalogueItem.objects.get(sku='custom-sku-1')
        stale = Cart.objects.create(user=user, status=Cart.Status.PENDING)

        cart = self.strategy.validate_item_and_create_cart(user, catalogue_item)

        stale.refresh_from_db()
        assert stale.status == Cart.Status.CANCELLED, 'The cart left open should have been cancelled'
        assert Cart.objects.filter(user=user, status=Cart.Status.PENDING).count() == 1, \
            'A user should be left with exactly one pending cart'
        assert Cart.objects.get(user=user, status=Cart.Status.PENDING) == cart, \
            'The one pending cart should be the one just opened'

    def test_validate_item_and_create_cart_opens_nothing_when_validation_refuses(self):
        """
        Verify that a refusal from validate_add_to_cart leaves no cart behind.

        The validation runs before anything is written, so a subclass that refuses an item must not leave a
        pending cart the learner would then be shown.
        """
        user = get_user_model().objects.get(id=7)
        catalogue_item = CatalogueItem.objects.get(sku='custom-sku-1')

        with patch.object(BaseCartHandler, 'validate_add_to_cart', side_effect=InvalidCartError('nope')):
            with pytest.raises(InvalidCartError):
                self.strategy.validate_item_and_create_cart(user, catalogue_item)

        assert not Cart.objects.filter(user=user).exists(), 'A refused item should leave no cart behind'


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
class TestPaidCourseCartHandler:
    """
    Tests for PaidCourseCartHandler.
    """
    fulfillment = learner_user = catalog_item = course_mode = None

    def setup_method(self):
        """setup."""
        self.fulfillment = PaidCourseCartHandler()
        self.learner_user = User.objects.get(id=3)
        self.catalog_item = CatalogueItem.objects.get(sku='custom-sku-1')
        self.course_mode = CourseMode.objects.get(sku=self.catalog_item.sku)

    def test_validate_add_to_cart_success(self):
        """
        Should not raise when CourseMode exists and all course conditions pass.
        """
        self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)

    @pytest.mark.parametrize(
        'sku, expected_msg',
        [
            (
                'custom-sku-with_invlaid_ref_id',
                'Unable to add item to the cart as Course mode found with given sku but course_id'
                ' mismatch with catalogue item ref-id.'
            ),
            (
                'sku-does-not-match-to-any-course-mode',
                'Unable to add item to the cart as CourseMode not found'
            ),
        ],
    )
    def test_validate_add_to_cart_invalid_cases(self, sku, expected_msg):
        """
        Should raise InvalidCartError for invalid ref_id or invalid sku.
        """
        if 'does-not-match' in sku:
            # dynamically create the item with invalid sku
            course_item = CatalogueItem.objects.create(
                sku=sku,
                type=CatalogueItem.ItemType.PAID_COURSE,
                title='Invalid SKU course',
                item_ref_id='irrelevant',
                price=100,
                currency='SAR'
            )
        else:
            course_item = CatalogueItem.objects.get(sku=sku)

        with pytest.raises(InvalidCartError, match=expected_msg):
            self.fulfillment.validate_add_to_cart(self.learner_user, course_item)

    @pytest.mark.parametrize(
        'patch_target, return_value, expected_msg',
        [
            (
                'zeitlabs_payments.helpers.CourseEnrollment.is_enrolled',
                True,
                'Unable to add item to the cart as user: user3 does not fulfill enrollment conditions. '
                'User is already enrolled in the course.'
            ),
            (
                'zeitlabs_payments.helpers.CourseEnrollment.objects.is_course_full',
                True,
                'Unable to add item to the cart as user: user3 does not fulfill enrollment conditions. '
                'Course is Full.'
            ),
            (
                'zeitlabs_payments.helpers.CourseEnrollment.is_enrollment_closed',
                True,
                'Unable to add item to the cart as user: user3 does not fulfill enrollment conditions. '
                'Enrollment is closed.'
            ),
        ],
    )
    def test_validate_add_to_cart_enrollment_failures(self, patch_target, return_value, expected_msg):
        """
        Should raise InvalidCartError when enrollment conditions fail (user enrolled, course full, enrollment closed).
        """
        # For course_full case, make sure course_overview.max_student_enrollments_allowed is set
        if 'is_course_full' in patch_target:
            course_overview = self.course_mode.course
            course_overview.max_student_enrollments_allowed = 2
            course_overview.save()

        with patch(patch_target, return_value=return_value):
            with pytest.raises(InvalidCartError, match=expected_msg):
                self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)

    def test_validate_add_to_cart_duplicate_cart_failure(self):
        """
        Should raise InvalidCartError when there is existing cart with smae course.
        """
        existing_cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PAYMENT_PENDING)
        existing_cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price
        )
        assert existing_cart.status == Cart.Status.PAYMENT_PENDING
        with pytest.raises(InvalidCartError) as exc:
            self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)
        assert str(exc.value) == (
            f'Unable to add item to the cart: A payment for it in cart {existing_cart.id} is still being resolved.'
        )

        existing_cart.status = Cart.Status.PENDING
        existing_cart.save(allow_status_change=True)

        # should not raise exception as there is no duplicate cart exist in processing state.
        self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)

    def test_validate_add_to_cart_refuses_while_a_charged_cart_is_unreconciled(self):
        """
        Verify that a course whose earlier payment was charged but not reconciled cannot be bought again.

        The learner has paid once already; a second cart for the same course would charge them twice.
        """
        held_cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.UNRECONCILED)
        held_cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price,
        )

        with pytest.raises(InvalidCartError, match=re.escape(f'cart {held_cart.id} is still being resolved')):
            self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)

    def test_validate_add_to_cart_refuses_while_a_paid_cart_has_no_invoice(self):
        """
        Verify that a course whose earlier payment was recorded but never fulfilled cannot be bought again.

        The learner paid and was not enrolled, so the enrolment check lets them through; the paid cart has to stop
        them instead.
        """
        unfulfilled = Cart.objects.create(user=self.learner_user, status=Cart.Status.PAID)
        unfulfilled.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price,
        )

        with pytest.raises(InvalidCartError, match=re.escape(f'cart {unfulfilled.id} is still being resolved')):
            self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_success(self, mock_enroll):
        """
        Should enroll user successfully and log events.
        """
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price
        )
        assert not AuditLog.objects.filter(
            action=AuditLog.AuditActions.USER_ENROLLED,
            cart=cart,
            details=(
                'User enrolled to the course: course-v1:org1+1+1 with mode: no-id-professional '
                'during cart fulfillment for catalogue_item: 1.'
            )
        ).exists()
        self.fulfillment.fulfill(cart_item, DummyProcessor())
        mock_enroll.assert_called_once_with(
            self.learner_user,
            self.course_mode.course.id,
            mode='no-id-professional',
            check_access=True
        )
        assert AuditLog.objects.filter(
            action=AuditLog.AuditActions.USER_ENROLLED,
            cart=cart,
            details=(
                'User enrolled to the course: course-v1:org1+1+1 with mode: no-id-professional '
                'during cart fulfillment for catalogue_item: 1.'
            )
        ).exists()

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_leaves_a_learner_already_holding_the_mode_as_they_are(self, mock_enroll):
        """
        Verify that a learner who already holds the course's mode -- enrolled in it by hand while the payment was
        settling, say -- is not enrolled again, and that this is recorded, so the payment can still be fulfilled.
        """
        CourseEnrollment.objects.create(
            user=self.learner_user, course=self.course_mode.course, mode=self.course_mode.mode_slug, is_active=True,
        )
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price,
        )

        self.fulfillment.fulfill(cart_item, DummyProcessor())

        assert not mock_enroll.called, 'A learner already holding the mode was enrolled again'
        assert list(AuditLog.objects.filter(cart=cart).values_list('action', flat=True)) == [
            AuditLog.AuditActions.USER_ALREADY_ENROLLED,
        ], 'The learner already holding the mode is not on the trail'

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_enrols_a_learner_holding_another_paid_mode_as_before(self, mock_enroll):
        """
        Verify that a learner enrolled in the course in another paid mode is enrolled in the mode bought as before --
        which Open edX refuses -- rather than taken as holding it or upgraded from it.
        """
        CourseEnrollment.objects.create(
            user=self.learner_user, course=self.course_mode.course, mode='verified', is_active=True,
        )
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price,
        )

        self.fulfillment.fulfill(cart_item, DummyProcessor())

        assert mock_enroll.called, 'A learner holding another mode was taken as holding the one bought'

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_upgrades_a_learner_from_a_free_mode(self, mock_enroll):
        """
        Verify that a learner enrolled in the course in audit has that enrolment moved to the mode bought, rather than
        being enrolled again, and that the upgrade is recorded.
        """
        CourseEnrollment.objects.create(
            user=self.learner_user, course=self.course_mode.course, mode='audit', is_active=True,
        )
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price,
        )

        self.fulfillment.fulfill(cart_item, DummyProcessor())

        assert not mock_enroll.called, 'A learner upgrading was enrolled again'
        assert CourseEnrollment.objects.get(user=self.learner_user).mode == self.course_mode.mode_slug, \
            'The enrolment was not moved to the mode bought'
        assert list(AuditLog.objects.filter(cart=cart).values_list('details', flat=True)) == [
            f'User upgraded in the course: {self.course_mode.course.id} from mode: audit to mode: '
            f'{self.course_mode.mode_slug} during cart fulfillment for catalogue_item: {self.catalog_item.id}.',
        ], 'The upgrade is not on the trail'

    def test_validate_add_to_cart_allows_an_upgrade_from_a_free_mode_even_once_enrolment_closed(self):
        """
        Verify that a learner enrolled in audit can buy the course's paid mode even once the course's enrolment has
        closed and it is full, since they hold a seat already.
        """
        CourseEnrollment.objects.create(
            user=self.learner_user, course=self.course_mode.course, mode='audit', is_active=True,
        )

        with patch('zeitlabs_payments.helpers.CourseEnrollment.is_enrollment_closed', return_value=True):
            with patch('zeitlabs_payments.helpers.CourseEnrollment.objects.is_course_full', return_value=True):
                self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)

    def test_validate_add_to_cart_refuses_a_mode_past_its_deadline(self):
        """
        Verify that a course mode past its expiration date is refused, to an upgrading learner and a new one alike,
        while one whose date is still ahead is not.
        """
        self.course_mode._expiration_datetime = now() + timedelta(days=1)  # pylint: disable=protected-access
        self.course_mode.save()
        self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)

        self.course_mode._expiration_datetime = now() - timedelta(days=1)  # pylint: disable=protected-access
        self.course_mode.save()
        with pytest.raises(InvalidCartError, match=f'The {self.course_mode.mode_slug} mode closed on'):
            self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)
        CourseEnrollment.objects.create(
            user=self.learner_user, course=self.course_mode.course, mode='audit', is_active=True,
        )
        with pytest.raises(InvalidCartError, match=f'The {self.course_mode.mode_slug} mode closed on'):
            self.fulfillment.validate_add_to_cart(self.learner_user, self.catalog_item)

    def test_fulfill_course_mode_not_found(self):
        """
        Should log and raise CartFulfillmentError when CourseMode is missing.
        """
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price
        )
        self.course_mode.delete()
        with pytest.raises(CartFulfillmentError, match='CourseMode not found'):
            self.fulfillment.fulfill(cart_item, DummyProcessor())

        assert AuditLog.objects.filter(
            action=AuditLog.AuditActions.CART_FULFILLMENT_ERROR,
            cart=cart,
            details=(
                f'Error during cart fulfillment for item: {cart_item.id}, catalogue_item:'
                f' {cart_item.id} due to invalid SKU: {self.catalog_item.sku} or unsupported type.'
            )
        ).exists()

    def test_fulfill_course_mode_found_but_invlaid_ref_id(self):
        """
        Should log and raise CartFulfillmentError when ref_id does not match with course mode.
        """
        self.catalog_item.item_ref_id = 'invalid-does-not-match-with-course-mode'
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price
        )
        with pytest.raises(CartFulfillmentError, match='Course Mode found but item ref id mismatched.'):
            self.fulfillment.fulfill(cart_item, DummyProcessor())

        assert AuditLog.objects.filter(
            action=AuditLog.AuditActions.CART_FULFILLMENT_ERROR,
            cart=cart,
            details=(
                f'Error during cart fulfillment for item: {cart_item.id}, catalogue_item:'
                f' {self.catalog_item.id} due to invalid SKU: {self.catalog_item.sku} or unsupported type.'
            )
        ).exists()

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_enrollment_fails(self, mock_enroll):
        """
        Should log and raise CartFulfillmentError when enrollment fails.
        """
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.catalog_item,
            original_price=self.catalog_item.price,
            final_price=self.catalog_item.price
        )
        mock_enroll.side_effect = CourseEnrollmentException('Enrollment failed')

        with pytest.raises(CartFulfillmentError, match='Unexpected enrollment error'):
            self.fulfillment.fulfill(cart_item, DummyProcessor())

        assert AuditLog.objects.filter(
            action=AuditLog.AuditActions.USER_ENROLLED_ERROR,
            cart=cart,
            details=(
                'Unable to complete user enrollment to course: course-v1:org1+1+1 with mode: no-id-professional '
                'during cart fulfillment for catalogue_item: 1.'
            )
        ).exists()


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
class TestProgramBundleCartHandler:
    """
    Tests for ProgramBundleCartHandler.
    """

    handler = learner_user = bundle_item = empty_bundle_item = None

    def setup_method(self):
        """Setup the handler and the base-data bundle fixtures for each test."""
        self.handler = ProgramBundleCartHandler()
        self.learner_user = User.objects.get(id=3)
        self.bundle_item = CatalogueItem.objects.get(sku='BUNDLE-PRO-CERT')
        self.empty_bundle_item = CatalogueItem.objects.get(sku='BUNDLE-EMPTY')

    def test_validate_add_to_cart_success(self):
        """Verify that validation passes when the bundle has valid courses and the user meets all checks."""
        self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    def test_validate_add_to_cart_empty_bundle(self):
        """Verify that an InvalidCartError is raised when the bundle has no linked courses."""
        with pytest.raises(InvalidCartError, match='no courses linked to this bundle'):
            self.handler.validate_add_to_cart(self.learner_user, self.empty_bundle_item)

    def test_validate_add_to_cart_course_mode_not_found(self):
        """Verify that an InvalidCartError is raised when a constituent course has no matching CourseMode."""
        course_item = BundleCourseItem.objects.filter(bundle=self.bundle_item).first().course_item
        CourseMode.objects.filter(sku=course_item.sku).delete()

        with pytest.raises(
            InvalidCartError,
            match=f'Bundle course {course_item.sku}: CourseMode not found',
        ):
            self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    def test_validate_add_to_cart_course_id_mismatch(self):
        """Verify that an InvalidCartError is raised when a CourseMode course_id mismatches the item ref id."""
        link = BundleCourseItem.objects.filter(bundle=self.bundle_item).first()
        course_item = link.course_item
        original_ref = course_item.item_ref_id
        course_item.item_ref_id = 'course-v1:wrong+0+0'
        course_item.save()

        with pytest.raises(
            InvalidCartError,
            match=f'Bundle course {course_item.sku}: CourseMode course_id mismatch',
        ):
            self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

        course_item.item_ref_id = original_ref
        course_item.save()

    @pytest.mark.parametrize(
        'patch_target, return_value, expected_msg_fragment',
        [
            (
                'zeitlabs_payments.helpers.CourseEnrollment.is_enrolled',
                True,
                'does not fulfill enrollment conditions',
            ),
            (
                'zeitlabs_payments.helpers.CourseEnrollment.objects.is_course_full',
                True,
                'does not fulfill enrollment conditions',
            ),
            (
                'zeitlabs_payments.helpers.CourseEnrollment.is_enrollment_closed',
                True,
                'does not fulfill enrollment conditions',
            ),
        ],
    )
    def test_validate_add_to_cart_enrollment_failures(self, patch_target, return_value, expected_msg_fragment):
        """Verify that an InvalidCartError is raised when enrollment conditions fail for any constituent course."""
        if 'is_course_full' in patch_target:
            for link in BundleCourseItem.objects.filter(bundle=self.bundle_item).select_related('course_item'):
                course_mode = CourseMode.objects.get(sku=link.course_item.sku)
                course_mode.course.max_student_enrollments_allowed = 2
                course_mode.course.save()

        with patch(patch_target, return_value=return_value):
            with pytest.raises(InvalidCartError, match=expected_msg_fragment):
                self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    @pytest.mark.parametrize('course_cart_status', [
        Cart.Status.PROCESSING, Cart.Status.PAYMENT_PENDING, Cart.Status.PAID, Cart.Status.UNRECONCILED,
    ])
    def test_validate_add_to_cart_is_not_blocked_by_a_cart_for_one_of_its_courses(self, course_cart_status):
        """
        Verify that the learner's cart for one of the bundle's courses, whatever its status, does not block the bundle.

        Buying a course must never stop its learner buying a bundle that contains it.
        """
        course_item = BundleCourseItem.objects.filter(bundle=self.bundle_item).first().course_item
        course_cart = Cart.objects.create(user=self.learner_user, status=course_cart_status, gateway='dummy')
        course_cart.items.create(
            catalogue_item=course_item, original_price=course_item.price, final_price=course_item.price,
        )

        self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    def test_validate_add_to_cart_refuses_a_bundle_already_bought(self):
        """Verify that a bundle the learner already has a paid cart for is refused."""
        bought = Cart.objects.create(user=self.learner_user, status=Cart.Status.PAID)
        bought.items.create(
            catalogue_item=self.bundle_item, original_price=self.bundle_item.price, final_price=self.bundle_item.price,
        )

        refusal = f'Unable to add bundle to the cart: A payment for it in cart {bought.id} is still being'
        with pytest.raises(InvalidCartError, match=re.escape(refusal)):
            self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    def test_validate_add_to_cart_sends_the_learner_back_to_the_bundle_in_flight(self):
        """Verify that a bundle whose earlier payment is still in flight raises that payment, carrying its cart."""
        inflight = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING, gateway='dummy')
        inflight.items.create(
            catalogue_item=self.bundle_item, original_price=self.bundle_item.price, final_price=self.bundle_item.price,
        )

        with pytest.raises(InFlightPaymentError) as raised:
            self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

        assert raised.value.cart == inflight, 'The bundle in flight is not the cart raised'

    def test_validate_add_to_cart_overlapping_bundle_cart_allowed(self):
        """Verify that a bundle can be added when an in-flight cart holds an overlapping bundle."""
        link = BundleCourseItem.objects.filter(bundle=self.bundle_item).first()
        shared_course_item = link.course_item

        other_bundle = CatalogueItem.objects.create(
            sku='BUNDLE-OTHER',
            type=CatalogueItem.ItemType.PROGRAM_BUNDLE,
            title='Other Bundle',
            item_ref_id='program-uuid-other',
            price=60,
            currency='SAR',
        )
        BundleCourseItem.objects.create(bundle=other_bundle, course_item=shared_course_item)

        existing_cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PAYMENT_PENDING)
        existing_cart.items.create(
            catalogue_item=other_bundle,
            original_price=other_bundle.price,
            final_price=other_bundle.price,
        )

        self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

        existing_cart.delete()
        BundleCourseItem.objects.filter(bundle=other_bundle).delete()
        other_bundle.delete()

    def _hold_mode_of_first_course(self, mode=None):
        """Enrol the learner in the bundle's first course, in that course's own mode unless another is named."""
        course_mode = CourseMode.objects.get(
            sku=BundleCourseItem.objects.filter(bundle=self.bundle_item).first().course_item.sku,
        )
        CourseEnrollment.objects.create(
            user=self.learner_user, course=course_mode.course, mode=mode or course_mode.mode_slug, is_active=True,
        )
        return course_mode

    def test_validate_add_to_cart_allows_a_bundle_containing_a_course_the_learner_holds(self):
        """
        Verify that a learner who already holds one of the bundle's courses in its mode can buy the bundle.

        Buying a course must never stop its learner buying a bundle that contains it.
        """
        self._hold_mode_of_first_course()

        self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    def test_validate_add_to_cart_refuses_a_learner_holding_another_paid_mode_of_a_course(self):
        """
        Verify that a learner enrolled in one of the bundle's courses in another paid mode is still refused the bundle.
        """
        self._hold_mode_of_first_course(mode='verified')

        with pytest.raises(InvalidCartError, match='does not fulfill enrollment conditions'):
            self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    def test_validate_add_to_cart_allows_a_learner_auditing_one_of_its_courses(self):
        """Verify that a learner enrolled in audit in one of the bundle's courses can buy the bundle, as an upgrade."""
        self._hold_mode_of_first_course(mode='audit')

        self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    def test_validate_add_to_cart_skips_the_deadline_of_a_course_the_learner_holds(self):
        """
        Verify that a course the learner already holds does not stop the bundle when its mode is past its deadline,
        since nothing is granted for it, while a course past its deadline that they do not hold does.
        """
        held = self._hold_mode_of_first_course()
        held._expiration_datetime = now() - timedelta(days=1)  # pylint: disable=protected-access
        held.save()
        self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

        CourseEnrollment.objects.filter(user=self.learner_user).delete()
        with pytest.raises(InvalidCartError, match=f'The {held.mode_slug} mode closed on'):
            self.handler.validate_add_to_cart(self.learner_user, self.bundle_item)

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_counts_a_course_upgraded_before_a_failure_among_those_that_landed(self, mock_enroll):
        """
        Verify that a bundle failing part-way counts a course it upgraded among the courses that landed, since the
        upgrade's mode-change events outlive the rollback as an enrolment's do.
        """
        upgraded = self._hold_mode_of_first_course(mode='audit')
        mock_enroll.side_effect = CourseEnrollmentException('the course is full')
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item, original_price=self.bundle_item.price, final_price=self.bundle_item.price,
        )

        with pytest.raises(CartFulfillmentError) as raised:
            self.handler.fulfill(cart_item, DummyProcessor())

        assert raised.value.landed_courses == [str(upgraded.course.id)], 'The upgraded course is not among those landed'

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_leaves_a_course_the_learner_holds_and_enrols_the_rest(self, mock_enroll):
        """
        Verify that fulfilling a bundle leaves a course the learner already holds in its mode as it is, recording that,
        and enrols them in the others.
        """
        held = self._hold_mode_of_first_course()
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item, original_price=self.bundle_item.price, final_price=self.bundle_item.price,
        )

        self.handler.fulfill(cart_item, DummyProcessor())

        enrolled_in = [call.args[1] for call in mock_enroll.call_args_list]
        assert held.course.id not in enrolled_in, 'A course the learner holds was enrolled in again'
        assert len(enrolled_in) == BundleCourseItem.objects.filter(bundle=self.bundle_item).count() - 1, \
            'The courses the learner does not hold were not all enrolled in'
        assert AuditLog.objects.filter(
            cart=cart, action=AuditLog.AuditActions.USER_ALREADY_ENROLLED, details__contains=str(held.course.id),
        ).exists(), 'The course the learner holds is not on the trail'

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_success(self, mock_enroll):
        """Verify that fulfillment enrols the user in every constituent course and records each enrolment."""
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item,
            original_price=self.bundle_item.price,
            final_price=self.bundle_item.price,
        )
        AuditLog.objects.all().delete()

        self.handler.fulfill(cart_item, DummyProcessor())

        bundle_links = BundleCourseItem.objects.filter(bundle=self.bundle_item)
        assert mock_enroll.call_count == bundle_links.count()

        for link in bundle_links:
            course_mode = CourseMode.objects.get(sku=link.course_item.sku)
            mock_enroll.assert_any_call(
                self.learner_user,
                course_mode.course.id,
                mode=course_mode.mode_slug,
                check_access=True,
            )

        enrolled_logs = AuditLog.objects.filter(
            action=AuditLog.AuditActions.USER_ENROLLED,
            cart=cart,
        )
        assert enrolled_logs.count() == bundle_links.count()

    def test_fulfill_empty_bundle(self):
        """Verify that a CartFulfillmentError is raised and audited when the bundle has no linked courses."""
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.empty_bundle_item,
            original_price=self.empty_bundle_item.price,
            final_price=self.empty_bundle_item.price,
        )

        with pytest.raises(CartFulfillmentError, match='No courses linked to this bundle'):
            self.handler.fulfill(cart_item, DummyProcessor())

        assert AuditLog.objects.filter(
            action=AuditLog.AuditActions.CART_FULFILLMENT_ERROR,
            cart=cart,
        ).exists()

    def test_fulfill_course_mode_not_found(self):
        """Verify that a CartFulfillmentError is raised and audited when a constituent CourseMode is missing."""
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item,
            original_price=self.bundle_item.price,
            final_price=self.bundle_item.price,
        )
        link = BundleCourseItem.objects.filter(bundle=self.bundle_item).first()
        CourseMode.objects.filter(sku=link.course_item.sku).delete()

        with pytest.raises(CartFulfillmentError, match='CourseMode not found for bundle course'):
            self.handler.fulfill(cart_item, DummyProcessor())

        assert AuditLog.objects.filter(
            action=AuditLog.AuditActions.CART_FULFILLMENT_ERROR,
            cart=cart,
        ).exists()

    def test_fulfill_course_id_mismatch(self):
        """Verify that a CartFulfillmentError is raised and audited when a course_id mismatches the item ref id."""
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item,
            original_price=self.bundle_item.price,
            final_price=self.bundle_item.price,
        )
        link = BundleCourseItem.objects.filter(bundle=self.bundle_item).first()
        original_ref = link.course_item.item_ref_id
        link.course_item.item_ref_id = 'course-v1:wrong+0+0'
        link.course_item.save()

        with pytest.raises(CartFulfillmentError, match='item ref id mismatched'):
            self.handler.fulfill(cart_item, DummyProcessor())

        assert AuditLog.objects.filter(
            action=AuditLog.AuditActions.CART_FULFILLMENT_ERROR,
            cart=cart,
        ).exists()

        link.course_item.item_ref_id = original_ref
        link.course_item.save()

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_enrollment_error(self, mock_enroll):
        """Verify that a CartFulfillmentError is raised and audited when enrollment fails on a bundle course."""
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item,
            original_price=self.bundle_item.price,
            final_price=self.bundle_item.price,
        )
        mock_enroll.side_effect = CourseEnrollmentException('Enrollment failed')

        with pytest.raises(CartFulfillmentError, match='Enrollment error for bundle course'):
            self.handler.fulfill(cart_item, DummyProcessor())

        assert AuditLog.objects.filter(
            action=AuditLog.AuditActions.USER_ENROLLED_ERROR,
            cart=cart,
        ).exists()

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_enrollment_error_carries_landed_courses(self, mock_enroll):
        """
        Verify that a midway enrollment failure reports which member courses had already landed.

        The first member enrolls, the second fails, and the raised error carries the landed list,
        the failed course and the bundle SKU so the caller can write a record that survives the
        payment transaction's rollback.
        """
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item,
            original_price=self.bundle_item.price,
            final_price=self.bundle_item.price,
        )
        mock_enroll.side_effect = [None, CourseEnrollmentException('Enrollment failed')]

        with pytest.raises(CartFulfillmentError, match='Enrollment error for bundle course') as exc_info:
            self.handler.fulfill(cart_item, DummyProcessor())

        error = exc_info.value
        assert error.landed_courses == ['course-v1:org1+1+1'], \
            'The course enrolled before the failure is the record of what landed'
        assert error.failed_course == 'course-v1:org2+1+1', \
            'The course that failed identifies where the enrollment stopped'
        assert error.bundle_sku == 'BUNDLE-PRO-CERT', \
            'The bundle SKU ties the failure record to the item that was purchased'

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_failure_carries_the_courses_the_learner_held(self, mock_enroll):
        """
        Verify that a failure after a course the learner already held carries that course as held, not as landed: its
        own entry on the trail rolls back with the failure, so the error is the only record left of it.
        """
        held = self._hold_mode_of_first_course()
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item, original_price=self.bundle_item.price, final_price=self.bundle_item.price,
        )
        mock_enroll.side_effect = CourseEnrollmentException('Enrollment failed')

        with pytest.raises(CartFulfillmentError) as raised:
            self.handler.fulfill(cart_item, DummyProcessor())

        assert raised.value.held_courses == [str(held.course.id)], 'The course the learner held is not carried as held'
        assert raised.value.landed_courses == [], 'A course the learner held was counted as landed'

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_unexpected_error_still_carries_landed_courses(self, mock_enroll):
        """
        Verify that a midway failure of any kind, not just CourseEnrollmentException, is reported.

        The first member enrolls and the second raises an unexpected error; the raised
        CartFulfillmentError still carries the landed list, the failed course and the bundle SKU,
        so the post-rollback audit entry is written for every midway failure.
        """
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item,
            original_price=self.bundle_item.price,
            final_price=self.bundle_item.price,
        )
        mock_enroll.side_effect = [None, ValueError('Unexpected platform failure')]

        with pytest.raises(CartFulfillmentError, match='Enrollment error for bundle course') as exc_info:
            self.handler.fulfill(cart_item, DummyProcessor())

        error = exc_info.value
        assert error.landed_courses == ['course-v1:org1+1+1'], \
            'An unexpected failure must still report which members had landed'
        assert error.failed_course == 'course-v1:org2+1+1', \
            'The failed member is reported by course id like every other midway failure'
        assert error.bundle_sku == 'BUNDLE-PRO-CERT'

    @patch('zeitlabs_payments.cart_handler.CourseEnrollment.enroll')
    def test_fulfill_missing_mode_error_carries_failed_member(self, mock_enroll):
        """
        Verify that a pass-1 integrity failure reports the member that failed validation.

        No enrollment has happened yet, so the landed list is empty and the failed course is the
        member whose mode is missing.
        """
        cart = Cart.objects.create(user=self.learner_user, status=Cart.Status.PROCESSING)
        cart_item = cart.items.create(
            catalogue_item=self.bundle_item,
            original_price=self.bundle_item.price,
            final_price=self.bundle_item.price,
        )
        link = BundleCourseItem.objects.filter(bundle=self.bundle_item).first()
        CourseMode.objects.filter(sku=link.course_item.sku).delete()

        with pytest.raises(CartFulfillmentError, match='CourseMode not found for bundle course') as exc_info:
            self.handler.fulfill(cart_item, DummyProcessor())

        error = exc_info.value
        assert error.landed_courses == [], 'No enrollment ran before a pass-1 failure'
        assert error.failed_course == 'course-v1:org1+1+1', \
            'The failed member is reported by course id, not by its course mode SKU'
        assert error.bundle_sku == 'BUNDLE-PRO-CERT'
        assert not mock_enroll.called, 'Pass 1 failures never reach enrollment'
