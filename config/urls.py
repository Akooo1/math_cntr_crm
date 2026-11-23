from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("sozlamalar/", include("apps.settings.urls")),
    path("", include("apps.crm.urls")),
    path("", include("apps.students.urls")),
    path("", include("apps.billing.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.salaries.urls")),
    path("", include("apps.staff.urls")),
]

handler400 = "apps.core.views.bad_request"
handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
