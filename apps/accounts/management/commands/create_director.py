"""First login on a fresh production database: create the Direktor account.

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web \\
        python manage.py create_director --phone "+998 90 123 45 67" --name "Ism Familiya"
"""

import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.core import phone as phones
from apps.core.roles import Role


class Command(BaseCommand):
    help = "Create a Direktor user (asks for the password)."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--password", help="Avoid on shared machines; prompts if omitted.")

    def handle(self, *args, phone, name, password=None, **options):
        try:
            number = phones.normalize(phone)
        except phones.InvalidPhone as exc:
            raise CommandError("Phone must look like +998 90 123 45 67") from exc
        User = get_user_model()
        if User.objects.filter(phone=number).exists():
            raise CommandError("A user with this phone already exists.")
        password = password or getpass.getpass("Password: ")
        user = User(phone=number, full_name=name, role=Role.DIRECTOR)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        user.set_password(password)
        user.must_change_password = False
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Director {name} ({number}) created."))
