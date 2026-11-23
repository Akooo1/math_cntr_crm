from django.urls import path

from . import views

app_name = "telegram"

urlpatterns = [
    path("ota-onalarga-xabar/", views.send, name="send"),
]
