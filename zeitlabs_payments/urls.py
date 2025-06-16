"""
URLs for zeitlabs_payments.
"""
from django.urls import re_path

from zeitlabs_payments import views
from zeitlabs_payments.providers.payfort import views as payfort_views

app_name = 'zeitlabs_payments'


urlpatterns: list = [
    re_path(
        r'^checkout/v1/checkout/$',
        views.CheckoutView.as_view(),
        name='checkout'
    ),
    re_path(
        r'^payment/v1/initiate/(?P<provider>[\w-]+)/(?P<cart_id>[0-9a-f-]+)/$',
        views.InitiatePaymentView.as_view(),
        name='initiate-payment'
    ),
    re_path(
        r'^payment/v1/error/(.+)/$',
        views.PaymentErrorView.as_view(),
        name='payment-error'
    ),
    re_path(
        r'^payment/v1/sucess/(.+)/$',
        views.PaymentSuccessView.as_view(),
        name='payment-success'
    ),

    re_path(r'^api/cart/v1/cart/$', views.CartView.as_view(), name='cart-add'),

    re_path(
        r'^payment/v1/payfort/return/$',
        payfort_views.PayFortReturnView.as_view(),
        name='payfort-return'
    ),
    re_path(
        r'^payment/v1/payfort/feedback/$',
        payfort_views.PayfortFeedbackView.as_view(),
        name='payfort-feedback'
    ),
    re_path(
        r'^payment/v1/payfort/status/$',
        payfort_views.PayFortStatusView.as_view(),
        name='payfort-status'
    ),
]
