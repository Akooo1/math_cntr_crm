"""Extension registries (docs/SPEC.md 4.4). Modules register in AppConfig.ready()."""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    url_name: str
    icon: str
    permission: str
    order: int = 100
    mobile_priority: int = 100  # lower = shown in the phone bottom bar first
    active_prefix: str = ""


@dataclass(frozen=True)
class DashboardWidget:
    key: str
    template: str
    permission: str
    order: int = 100
    context: Callable | None = None  # context(request) -> dict


@dataclass
class Registry:
    nav: dict[str, NavItem] = field(default_factory=dict)
    widgets: dict[str, DashboardWidget] = field(default_factory=dict)
    # Set by the settings module so the layout can show the center name and branch switcher
    # without core importing a higher module.
    center_name_provider: Callable[[], str] | None = None
    branch_options_provider: Callable[[set[int] | None], list] | None = None

    def add_nav(self, item: NavItem):
        self.nav[item.key] = item

    def add_widget(self, widget: DashboardWidget):
        self.widgets[widget.key] = widget


registry = Registry()
