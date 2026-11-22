from django.urls import path

from . import views

app_name = "crm"

urlpatterns = [
    path("lidlar/", views.board, name="board"),
    path("lidlar/yangi/", views.lead_create, name="lead_create"),
    path("lidlar/dublikat/", views.duplicate_check, name="duplicate_check"),
    path("lidlar/<int:pk>/", views.lead_detail, name="lead"),
    path("lidlar/<int:pk>/tahrirlash/", views.lead_edit, name="lead_edit"),
    path("lidlar/<int:pk>/bosqich/", views.move, name="move"),
    path("lidlar/<int:pk>/izoh/", views.add_activity, name="add_activity"),
    path("lidlar/<int:pk>/rad-etish/", views.refuse, name="refuse"),
    path("lidlar/<int:pk>/qayta-ochish/", views.reopen, name="reopen"),
    path("lidlar/<int:pk>/vazifa/", views.task_create, name="task_create"),
    path("lidlar/<int:pk>/sinov-darsi/", views.trial_book, name="trial_book"),
    path("lidlar/<int:pk>/oquvchi/", views.convert, name="convert"),
    path("vazifalar/", views.tasks, name="tasks"),
    path("vazifalar/<int:pk>/bajarildi/", views.task_done, name="task_done"),
    path("sinov-darslari/", views.trials, name="trials"),
    path("sinov-darslari/<int:pk>/holat/", views.trial_status, name="trial_status"),
]
