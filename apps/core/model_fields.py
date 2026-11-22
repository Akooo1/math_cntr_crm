from django.db import models


class MoneyField(models.BigIntegerField):
    """Whole so'm. A distinct class so the audit viewer and exports know to format money."""

    is_money = True
