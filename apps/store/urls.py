from django.urls import path

from . import views

app_name = "store"

urlpatterns = [
    path("savdo/", views.sell, name="sell"),
    path("savdo/jurnal/", views.journal, name="journal"),
    path("savdo/<int:pk>/", views.sale_detail, name="sale"),
    path("savdo/<int:pk>/bekor-qilish/", views.sale_reverse, name="reverse"),
    path("ombor/", views.stock, name="stock"),
    path("ombor/kirim/", views.receive, name="receive"),
    path("ombor/tuzatish/", views.correct, name="correct"),
    path("ombor/mahsulot/<int:pk>/", views.product_history, name="product"),
    path("kitob-berish/<int:student_id>/", views.give_book, name="give_book"),
    path("guruhga-kitob/", views.give_group, name="give_group"),
]
