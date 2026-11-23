from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("keldim/", views.check_in, name="check_in"),
    path("xodimlar-davomati/", views.board, name="board"),
    path("xodimlar-davomati/qolda/", views.manual, name="manual"),
]
