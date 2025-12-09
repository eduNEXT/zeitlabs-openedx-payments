""""test for zeitlabs payments querysets."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Prefetch
from django.utils import timezone
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

from zeitlabs_payments.models import Cart, CartItem, CatalogueItem, Invoice
from zeitlabs_payments.querysets import get_orders_queryset

User = get_user_model()


@pytest.mark.django_db
def test_get_orders_queryset_filters_and_prefetches_correctly(
    base_data
):  # pylint: disable=unused-argument
    """Test get_orders_queryset returns expected carts filtered by item type, sku, and status."""
    user = User.objects.get(id=3)
    item1 = CatalogueItem.objects.create(
        sku='COURSE-123',
        type=CatalogueItem.ItemType.PAID_COURSE,
        title='Paid Course',
        item_ref_id='course-v1:TestX+TST101',
        price=100,
        currency='SAR',
    )
    item2 = CatalogueItem.objects.create(
        sku='COURSE-999',
        type='other_type',
        title='Other Course',
        item_ref_id='course-v1:TestX+OTH101',
        price=200,
        currency='SAR',
    )
    paid_cart_item1 = Cart.objects.create(user=user, status=Cart.Status.PAID)
    CartItem.objects.create(cart=paid_cart_item1, catalogue_item=item1, final_price=100, original_price=100)
    Invoice.objects.create(
        cart=paid_cart_item1,
        invoice_number='INV001',
        currency='SAR',
        paid_at=None,
        status='paid',
        gross_total=100,
        total=100
    )
    pending_cart_item1 = Cart.objects.create(user=user, status=Cart.Status.PENDING)
    CartItem.objects.create(cart=pending_cart_item1, catalogue_item=item1, final_price=100, original_price=100)
    pending_cart_item2 = Cart.objects.create(user=user, status=Cart.Status.PENDING)
    CartItem.objects.create(cart=pending_cart_item2, catalogue_item=item2, final_price=200, original_price=200)

    # without any filtration, all carts should return
    queryset = get_orders_queryset(
        filtered_courses_qs=None,
        sku_search=None,
        status=None,
        item_type=None,
        include_invoice=False,
        include_user_details=False,
    )
    assert queryset.count() == 3

    # only carts with particular sku should return
    queryset = get_orders_queryset(
        filtered_courses_qs=None,
        sku_search=item2.sku,
        status=None,
        item_type=None,
        include_invoice=False,
        include_user_details=False,
    )
    assert queryset.count() == 1
    assert queryset[0].id == pending_cart_item2.id

    # only carts with pending status should return
    queryset = get_orders_queryset(
        filtered_courses_qs=None,
        sku_search=None,
        status='pending',
        item_type=None,
        include_invoice=False,
        include_user_details=False,
    )
    returned_cart_ids = [cart.id for cart in queryset]
    assert queryset.count() == 2
    assert pending_cart_item1.id in returned_cart_ids
    assert pending_cart_item2.id in returned_cart_ids

    # only carts containing paid_course items should return
    queryset = get_orders_queryset(
        filtered_courses_qs=None,
        sku_search=None,
        status=None,
        item_type=CatalogueItem.ItemType.PAID_COURSE,
        include_invoice=False,
        include_user_details=False,
    )
    returned_cart_ids = [cart.id for cart in queryset]
    assert queryset.count() == 2
    assert paid_cart_item1.id in returned_cart_ids
    assert pending_cart_item1.id in returned_cart_ids
    # include_invoice is False so invoices should not be prefetched.
    assert not any(
        isinstance(p, Prefetch) and p.prefetch_through == 'invoices'
        for p in queryset._prefetch_related_lookups  # pylint: disable=protected-access
    )
    assert not queryset.query.select_related

    # prefetch invoices and user when inlcude_invoice and include_user_details is set
    queryset = get_orders_queryset(
        filtered_courses_qs=None,
        sku_search=None,
        status=None,
        item_type=CatalogueItem.ItemType.PAID_COURSE,
        include_invoice=True,
        include_user_details=True,
    )
    assert queryset.count() == 2
    assert hasattr(queryset, '_prefetch_related_lookups')
    assert any(
        isinstance(p, Prefetch) and p.prefetch_through == 'invoices'
        for p in queryset._prefetch_related_lookups  # pylint: disable=protected-access
    )
    assert len(queryset.courses_map) == CourseOverview.objects.count()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'usecase, course_filter, user_filter, expected_ids',
    [
        ('no_filters_returns_all', None, None, 'ALL'),
        ('filter_by_course_returns_linked', 'course-v1:org1+1+1', None, 'COURSE_1'),
        ('filter_by_user_returns_user_carts', None, 'USER_1', 'USER_1'),
        ('filter_by_both_returns_intersection', 'course-v1:org1+1+1', 'USER_1', 'USER1_COURSE1'),
        ('empty_course_returns_none', 'course-v1:no_cart_exist+with_this+course', None, []),
        ('empty_user_returns_none', None, 'NONE', []),
    ],
)
def test_get_orders_queryset_with_accessible_courses_and_users(
    base_data, usecase, course_filter, user_filter, expected_ids
):  # pylint: disable=unused-argument
    """Compact test for get_orders_queryset with different filters."""
    def make_cart(user, course_idx, status):
        cart = Cart.objects.create(user=user, status=status)
        cart.items.create(
            catalogue_item=items[course_idx],
            original_price=items[course_idx].price,
            final_price=items[course_idx].price
        )
        return cart

    user1, user2 = User.objects.get(id=3), User.objects.get(id=4)
    items = CatalogueItem.objects.filter(item_ref_id__in=['course-v1:org1+1+1', 'course-v1:org2+1+1'])
    u1_c1 = make_cart(user1, 0, Cart.Status.PENDING)
    u1_c2 = make_cart(user1, 1, Cart.Status.PAID)
    u2_c1 = make_cart(user2, 0, Cart.Status.PAID)
    u2_c2 = make_cart(user2, 1, Cart.Status.PAID)
    filtered_courses = CourseOverview.objects.filter(id=course_filter) if course_filter else None
    filtered_users = (
        User.objects.filter(id=user1.id) if user_filter == 'USER_1'
        else User.objects.none() if user_filter == 'NONE'
        else None
    )

    qs = get_orders_queryset(
        filtered_courses_qs=filtered_courses,
        filtered_users_qs=filtered_users,
        sku_search=None,
        status=None,
        item_type=CatalogueItem.ItemType.PAID_COURSE,
        include_invoice=False,
        include_user_details=False,
    )
    expected_map = {
        'ALL': [u1_c1.id, u1_c2.id, u2_c1.id, u2_c2.id],
        'COURSE_1': [u1_c1.id, u2_c1.id],
        'USER_1': [u1_c1.id, u1_c2.id],
        'USER1_COURSE1': [u1_c1.id],
        'NONE': [],
    }
    expected = expected_map[expected_ids] if isinstance(expected_ids, str) else expected_ids
    actual = [c.id for c in qs]
    assert sorted(actual) == sorted(expected), f'Failed - {usecase}: expected {expected}, got {actual}'


@pytest.mark.django_db
def test_get_orders_queryset_date_filters():
    """Test get_orders_queryset filters correctly by date_from and date_to."""
    user = User.objects.get(id=3)
    item = CatalogueItem.objects.create(
        sku='COURSE-DATE',
        type=CatalogueItem.ItemType.PAID_COURSE,
        title='Date Course',
        item_ref_id='course-v1:TestX+DATE101',
        price=100,
        currency='SAR',
    )
    cart1 = Cart.objects.create(user=user, status=Cart.Status.PAID)
    CartItem.objects.create(cart=cart1, catalogue_item=item, final_price=100, original_price=100)
    cart2 = Cart.objects.create(user=user, status=Cart.Status.PAID)
    CartItem.objects.create(cart=cart2, catalogue_item=item, final_price=100, original_price=100)
    cart3 = Cart.objects.create(user=user, status=Cart.Status.PAID)
    CartItem.objects.create(cart=cart3, catalogue_item=item, final_price=100, original_price=100)

    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    cart1.created_at = two_days_ago
    cart1.save()
    cart2.created_at = yesterday
    cart2.save()
    cart3.created_at = today
    cart3.save()

    # Filter carts from yesterday onwards
    qs = get_orders_queryset(
        filtered_courses_qs=None,
        filtered_users_qs=None,
        date_from=yesterday,
        date_to=None,
    )
    returned_ids = [c.id for c in qs]
    assert cart2.id in returned_ids
    assert cart3.id in returned_ids
    assert cart1.id not in returned_ids

    # Filter carts up to yesterday
    qs = get_orders_queryset(
        filtered_courses_qs=None,
        filtered_users_qs=None,
        date_from=None,
        date_to=yesterday,
    )
    returned_ids = [c.id for c in qs]
    assert cart1.id in returned_ids
    assert cart2.id in returned_ids
    assert cart3.id not in returned_ids

    # Filter carts between two_days_ago and yesterday
    qs = get_orders_queryset(
        filtered_courses_qs=None,
        filtered_users_qs=None,
        date_from=two_days_ago,
        date_to=yesterday,
    )
    returned_ids = [c.id for c in qs]
    assert cart1.id in returned_ids
    assert cart2.id in returned_ids
    assert cart3.id not in returned_ids
