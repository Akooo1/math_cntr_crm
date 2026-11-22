from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz", views.healthz, name="healthz"),
    path("filial/", views.switch_branch, name="switch_branch"),
    path("jurnal/", views.audit_log, name="audit_log"),
]
