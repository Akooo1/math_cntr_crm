from django.urls import path

from . import views

app_name = "salaries"

urlpatterns = [
    path("maosh/", views.index, name="index"),
    path("maosh/yopish/", views.close, name="close"),
    path("maosh/oqituvchi/<int:pk>/", views.sheet, name="sheet"),
    path("maosh/oqituvchi/<int:pk>/qoshish/", views.adjustment_add, name="adjustment_add"),
    path("maosh/oqituvchi/<int:pk>/berish/", views.payout, name="payout"),
    path("maosh/oqituvchi/<int:pk>/avans/", views.advance, name="advance"),
    path("maosh/avans/<int:pk>/bekor-qilish/", views.advance_cancel, name="advance_cancel"),
    path("maosh/qoshimcha/<int:pk>/ochirish/", views.adjustment_delete, name="adjustment_delete"),
    path("maosh/berilgan/<int:pk>/bekor-qilish/", views.payout_cancel, name="payout_cancel"),
    path("maoshim/", views.mine, name="mine"),
]
