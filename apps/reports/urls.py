from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("hisobotlar/", views.index, name="index"),
    path("hisobotlar/<slug:key>/", views.report, name="report"),
    path("hisobotlar/<slug:key>/excel/", views.report_excel, name="excel"),
]
