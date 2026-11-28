from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("tolovlar/", views.payment_list, name="payments"),
    path("tolovlar/yangi/", views.payment_create, name="payment_create"),
    path("tolovlar/qidirish/", views.student_search, name="student_search"),
    path("tolovlar/<int:pk>/", views.payment_detail, name="payment"),
    path("tolovlar/<int:pk>/chek/", views.receipt, name="receipt"),
    path("tolovlar/<int:pk>/bekor-qilish/", views.payment_reverse, name="reverse"),
    path("hisob/<int:pk>/pul-qaytarish/", views.refund, name="refund"),
    path("hisob/<int:pk>/chegirma/", views.discount_assign, name="discount_assign"),
    path("hisob/<int:pk>/qoshimcha/", views.manual_charge, name="manual_charge"),
    path("chegirmalar/<int:pk>/tugatish/", views.discount_end, name="discount_end"),
    path("hisoblangan/<int:pk>/tuzatish/", views.charge_correct, name="charge_correct"),
    path("bolib-tolash-reja/<int:pk>/", views.plan_edit, name="plan_edit"),
    path("qarzdorlar/", views.debtors, name="debtors"),
    path("kassa/", views.cash_report, name="cash"),
    path("kassa/yopish/", views.cash_close, name="cash_close"),
    path("kassa/qayta-ochish/", views.cash_reopen, name="cash_reopen"),
]
