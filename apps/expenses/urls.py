from django.urls import path

from . import views

app_name = "expenses"

urlpatterns = [
    path("xarajatlar/", views.expense_list, name="list"),
    path("xarajatlar/yangi/", views.expense_create, name="create"),
    path("xarajatlar/<int:pk>/", views.expense_detail, name="detail"),
    path("xarajatlar/<int:pk>/bekor-qilish/", views.expense_reverse, name="reverse"),
]
