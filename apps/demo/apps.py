from django.apps import AppConfig


class DemoConfig(AppConfig):
    """Demo data for local runs and acceptance checks. Top layer: may import any module."""

    name = "apps.demo"
    label = "demo"
