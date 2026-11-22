from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("kirish/", views.login_view, name="login"),
    path("chiqish/", views.logout_view, name="logout"),
    path("profil/", views.profile, name="profile"),
    path("profil/parol/", views.password_change, name="password_change"),
]
