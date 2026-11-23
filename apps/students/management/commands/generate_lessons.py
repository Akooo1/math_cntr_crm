from django.core.management.base import BaseCommand

from apps.students.models import Group
from apps.students.services.groups import generate_lessons


class Command(BaseCommand):
    help = "Roll the lesson calendar of open-ended groups forward (idempotent; cron runs it daily)."

    def handle(self, *args, **options):
        created = 0
        for group in Group.objects.exclude(status=Group.Status.FINISHED).prefetch_related("slots"):
            created += generate_lessons(group)
        self.stdout.write(f"lessons created: {created}")
