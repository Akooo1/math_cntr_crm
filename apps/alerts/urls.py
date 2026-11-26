from django.urls import path

from . import views

app_name = "alerts"

urlpatterns = [
    path("ogohlantirishlar/", views.task_list, name="list"),
    path("ogohlantirishlar/<int:pk>/bajarildi/", views.done, name="done"),
    path("ogohlantirishlar/<int:pk>/qayta-ochish/", views.reopen, name="reopen"),
]
