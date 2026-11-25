"""static/dist/app.css is committed so `git pull` always brings a stylesheet that matches the
templates. A stale build showed the new page layout unstyled (menu icons above labels)."""

import re

from django.conf import settings

COMPONENT = re.compile(r"^\s*\.([a-z][\w-]*)\s*[{,:]", re.M)


def test_built_css_contains_every_component_class():
    source = (settings.BASE_DIR / "assets" / "app.css").read_text()
    built = (settings.BASE_DIR / "static" / "dist" / "app.css").read_text()
    missing = sorted({c for c in COMPONENT.findall(source) if f".{c}" not in built})
    assert not missing, f"Rebuild with `npm run build:css` and commit it; missing: {missing}"
