from django.urls import path

from . import views

app_name = "settings"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:slug>/", views.section_list, name="section_list"),
    path("<slug:slug>/yangi/", views.section_create, name="section_create"),
    path("<slug:slug>/<int:pk>/", views.section_edit, name="section_edit"),
    path("<slug:slug>/<int:pk>/holat/", views.section_toggle, name="section_toggle"),
    path("<slug:slug>/<int:pk>/<slug:action>/", views.section_action, name="section_action"),
]
