from django.urls import path

from . import views

app_name = "students"

urlpatterns = [
    path("oquvchilar/", views.student_list, name="list"),
    path("oquvchilar/yangi/", views.student_create, name="create"),
    path("oquvchilar/dublikat/", views.duplicate_check, name="duplicate_check"),
    path("oquvchilar/<int:pk>/", views.student_detail, name="detail"),
    path("oquvchilar/<int:pk>/tahrirlash/", views.student_edit, name="edit"),
    path("oquvchilar/<int:pk>/guruhga-qoshish/", views.enroll, name="enroll"),
    path("qatnashish/<int:pk>/otkazish/", views.move, name="move"),
    path("qatnashish/<int:pk>/muzlatish/", views.freeze, name="freeze"),
    path("qatnashish/<int:pk>/davom-ettirish/", views.unfreeze, name="unfreeze"),
    path("qatnashish/<int:pk>/chiqish/", views.leave, name="leave"),
    path("guruhlar/", views.group_list, name="groups"),
    path("guruhlar/yangi/", views.group_create, name="group_create"),
    path("guruhlar/<int:pk>/", views.group_detail, name="group"),
    path("guruhlar/<int:pk>/tahrirlash/", views.group_edit, name="group_edit"),
    path("darslar/<int:pk>/bekor-qilish/", views.lesson_cancel, name="lesson_cancel"),
    path("darslar/<int:pk>/tiklash/", views.lesson_restore, name="lesson_restore"),
    path("davomat/", views.attendance_day, name="attendance"),
    path("davomat/<int:pk>/", views.attendance_lesson, name="attendance_lesson"),
    path("davomat/<int:pk>/belgilash/", views.attendance_mark, name="attendance_mark"),
    path("import/", views.import_page, name="import"),
    path("import/namuna/<slug:kind>/", views.import_template, name="import_template"),
    path("import/<int:pk>/", views.import_batch, name="import_batch"),
    path("import/<int:pk>/tasdiqlash/", views.import_commit, name="import_commit"),
]
