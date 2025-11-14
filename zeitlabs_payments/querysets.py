"""zeitlabs payments queryset functions."""
from django.db.models import Prefetch, Subquery
from django.db.models.query import QuerySet
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

from zeitlabs_payments.models import Cart, CartItem, CatalogueItem, Invoice


def get_orders_queryset(  # pylint: disable= too-many-positional-arguments
    filtered_courses_qs: QuerySet = None,
    filtered_users_qs: QuerySet = None,
    sku_search: str | None = None,
    status: str | None = None,
    item_type: str | None = None,
    include_invoice: bool = False,
    include_user_details: bool = False,
) -> QuerySet:
    """
    Return serialized cart (order) data filtered by courses and users.
    """
    course_map = {}
    filtered_items_qs = CatalogueItem.objects.all()

    if filtered_courses_qs is not None:
        filtered_items_qs = filtered_items_qs.filter(
            item_ref_id__in=Subquery(filtered_courses_qs.values('id'))
        )
        course_map = {str(course.id): course for course in filtered_courses_qs}
    else:
        course_map = {str(course.id): course for course in CourseOverview.objects.all()}

    if sku_search:
        filtered_items_qs = filtered_items_qs.filter(sku=sku_search)

    if item_type:
        filtered_items_qs = filtered_items_qs.filter(type=item_type)

    filtered_carts_qs = Cart.objects.filter(items__catalogue_item__in=filtered_items_qs)

    if filtered_users_qs is not None:
        filtered_carts_qs = filtered_carts_qs.filter(user__in=filtered_users_qs)

    if status:
        filtered_carts_qs = filtered_carts_qs.filter(status=status)

    filtered_carts_qs = filtered_carts_qs.prefetch_related(
        Prefetch('items', queryset=CartItem.objects.select_related('catalogue_item'))
    )

    if include_user_details:
        filtered_carts_qs = filtered_carts_qs.select_related('user')

    if include_invoice:
        filtered_carts_qs = filtered_carts_qs.prefetch_related(
            Prefetch('invoices', queryset=Invoice.objects.only('invoice_number', 'currency', 'paid_at', 'status'))
        )

    filtered_carts_qs.courses_map = course_map
    return filtered_carts_qs
