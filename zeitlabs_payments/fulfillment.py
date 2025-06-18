# fulfillment.py

import logging

from common.djangoapps.course_modes.models import CourseMode
from common.djangoapps.student.models import CourseEnrollment

from zeitlabs_payments.exceptions import CartFulfillmentError
from zeitlabs_payments.models import Cart, CatalogueItem, AuditLog, CartItem

logger = logging.getLogger(__name__)


FULFILLMENT_HANDLERS = {}


def register_handler(item_type):
    """
    Decorator to register a fulfillment handler for a given catalogue item type.

    :param item_type: The type of catalogue item to register the handler for.
    :return: The class decorator function.
    """
    def wrapper(cls):
        FULFILLMENT_HANDLERS[item_type] = cls()
        return cls
    return wrapper


class BaseFulfillmentStrategy:
    """
    Base class/interface for fulfillment strategy handlers.
    Subclasses must implement the fulfill method.
    """

    def fulfill(self, cart: Cart, item: CartItem, processor_slug: str):
        """
        Fulfill the given item in the cart.

        :param cart: The Cart instance containing the item.
        :param item: The cart item to fulfill.
        :raises NotImplementedError: If the subclass does not implement this method.
        :return: None
        """
        raise NotImplementedError("Subclasses must implement fulfill()")


@register_handler(CatalogueItem.ItemType.PAID_COURSE)
class PaidCourseFulfillment(BaseFulfillmentStrategy):
    """
    Fulfillment handler for paid course catalogue items.
    """

    def fulfill(self, cart: Cart, item: CartItem, processor_slug: str) -> None:
        """
        Fulfill a paid course item by enrolling the user in the course.

        :param cart: The Cart instance.
        :param item: The cart item representing a paid course.
        :raises CartFulfillmentError: If course mode is not found or enrollment fails.
        :return: None
        """
        logger.debug(f'Processing item {item.id} in cart {cart.id}.')

        try:
            course_mode = CourseMode.objects.get(sku=item.catalogue_item.sku)
        except CourseMode.DoesNotExist as exc:
            logger.error(
                f'CourseMode not found for SKU: {item.catalogue_item.sku} - Item ID: {item.id}'
            )
            AuditLog.objects.create(
                user=cart.user,
                action='CartFulfillmentError',
                gateway=processor_slug,
                details=(
                    f'Error during cart: {cart.id} fulfillment for item: {item.id}, catalogue_item:'
                    f' {item.catalogue_item.id} due to invalid sku: {item.catalogue_item.sku} as'
                    f' CourseMode does not exist.'
                )
            )
            raise CartFulfillmentError('CourseMode not found') from exc

        try:
            CourseEnrollment.enroll(
                cart.user,
                course_mode.course.id,
                mode=course_mode.mode_slug,
            )
            AuditLog.objects.create(
                user=cart.user,
                action='UserEnrolled',
                gateway=processor_slug,
                details=(
                    f'User enrolled to the course: {course_mode.course.id} with mode: {course_mode.mode_slug} '
                    f'during cart: {cart.id} fulfillment for catalogue_item: {item.catalogue_item.id}.'
                )
            )
            logger.info(
                f'User {cart.user.id} enrolled in course {course_mode.course.id} '
                f'with mode {course_mode.mode_slug}'
            )
        except Exception as exc:
            logger.exception(
                f'Unexpected error while enrolling user {cart.user.id} in course: '
                f'{course_mode.course.id}. Item ID: {item.id}'
            )
            AuditLog.objects.create(
                user=cart.user,
                action='UserEnrolledError',
                gateway=processor_slug,
                details=(
                    f'Unable to complete user enrollment to course: {course_mode.course.id} with mode: '
                    f'{course_mode.mode_slug} during cart: {cart.id} fulfillment for '
                    f'catalogue_item: {item.catalogue_item.id}.'
                )
            )
            raise CartFulfillmentError('Unexpected enrollment error') from exc
