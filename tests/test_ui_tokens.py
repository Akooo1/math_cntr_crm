"""Theme guardrails (assets/app.css): both themes come from CSS variables, so templates must
only use the colour scales that are mirrored for the dark theme, and every text colour they
use must meet WCAG AA contrast (4.5:1) on the app's surfaces in BOTH themes."""

import re
from pathlib import Path

import pytest
from django.conf import settings

ROOT = Path(settings.BASE_DIR)
CSS = (ROOT / "assets" / "app.css").read_text()
MIRRORED = ("slate", "sky", "rose", "emerald", "amber", "violet")
# The center name is a logotype (WCAG 1.4.3 exempts logos); receipts are a print page.
EXEMPT = {"brand_name.html", "receipt.html"}


def _block(selector_regex: str) -> dict[str, str]:
    m = re.search(selector_regex + r"\s*\{(.*?)\n\}", CSS, re.S)
    assert m, selector_regex
    return dict(re.findall(r"--color-([\w-]+):\s*(#[0-9a-fA-F]{6})", m.group(1)))


LIGHT = _block(r"@theme")
DARK = {**LIGHT, **_block(r':root\[data-theme="dark"\]')}
THEMES = {"light": LIGHT, "dark": DARK}


def _lum(hex_: str) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _sources():
    for d in [ROOT / "templates", *ROOT.glob("apps/*/templates")]:
        for p in d.rglob("*.html"):
            if p.name not in EXEMPT:
                yield p, p.read_text()
    for p in ROOT.glob("apps/*/**/*.py"):
        if "tests" not in p.parts and "migrations" not in p.parts:
            yield p, p.read_text()


TEXT_RE = re.compile(r"(?<![\w:-])text-((?:" + "|".join(MIRRORED) + r")-\d{2,3}|fg|muted)\b")


def _used_text_colors() -> set[str]:
    return {m for _, src in _sources() for m in TEXT_RE.findall(src)}


def test_theme_defines_every_mirrored_scale():
    for hue in MIRRORED:
        for step in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950):
            assert f"{hue}-{step}" in LIGHT and f"{hue}-{step}" in DARK, (hue, step)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_colors_meet_aa_on_surfaces(theme):
    t = THEMES[theme]
    failures = []
    for color in sorted(_used_text_colors()):
        for surface in ("surface", "surface-2", "canvas"):
            ratio = contrast(t[color], t[surface])
            if ratio < 4.5:
                failures.append(f"text-{color} on {surface}: {ratio:.2f}")
    assert not failures, failures


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_badge_pairs_meet_aa(theme):
    """`bg-X-N text-Y-M` in one class list (badges, notices): checked as a pair."""
    t = THEMES[theme]
    pair = re.compile(
        r"bg-((?:"
        + "|".join(MIRRORED)
        + r")-\d{2,3})\s+text-((?:"
        + "|".join(MIRRORED)
        + r")-\d{2,3})"
    )
    failures = set()
    for path, src in _sources():
        for bg, fg in pair.findall(src):
            ratio = contrast(t[fg], t[bg])
            if ratio < 4.5:
                failures.add(f"{path.name}: bg-{bg} text-{fg} = {ratio:.2f}")
    assert not failures, sorted(failures)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_buttons_and_charts(theme):
    t = THEMES[theme]
    white = "#ffffff"
    assert contrast(t["on-primary"], t["primary"]) >= 4.5
    assert contrast(t["on-primary"], t["primary-hover"]) >= 4.5
    for solid in ("danger", "danger-hover", "success", "success-hover"):
        assert contrast(white, t[solid]) >= 4.5, solid
    for text in ("fg", "muted"):
        for surface in ("surface", "surface-2", "canvas"):
            assert contrast(t[text], t[surface]) >= 4.5, (text, surface)
    # Chart bars are graphics: 3:1 against the card (WCAG 1.4.11), and told apart by hue.
    for c in ("chart-1", "chart-2"):
        assert contrast(t[c], t["surface"]) >= 3, c
    assert contrast(t["focus"], t["surface"]) >= 3


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_accent_tiles_and_sidebar(theme):
    """Solid accent tiles (.tile-*) and the dark sidebar carry their own text colours."""
    t = THEMES[theme]
    pairs = [
        ("on-accent-blue", "accent-blue"),
        ("on-accent-yellow", "accent-yellow"),
        ("on-accent-teal", "accent-teal"),
        ("on-ink", "ink"),
        ("rail-fg", "rail"),
        ("on-rail-active", "rail-active"),
    ]
    for fg, bg in pairs:
        assert contrast(t[fg], t[bg]) >= 4.5, (fg, bg, round(contrast(t[fg], t[bg]), 2))


def test_templates_use_theme_tokens_only():
    """No per-template dark: classes, no hard white surfaces, no unmirrored hues."""
    other_hues = re.compile(
        r"(?<![\w-])(?:bg|text|border|ring|divide|from|to|fill|stroke)-"
        r"(?:red|blue|green|gray|zinc|neutral|stone|orange|yellow|lime|teal|cyan|indigo|purple|fuchsia|pink)-\d"
    )
    problems = []
    for path, src in _sources():
        if path.suffix != ".html":
            continue
        for bad in ("dark:", "bg-white", "text-white", "bg-black"):
            if re.search(r"(?<![\w-])" + re.escape(bad), src):
                problems.append(f"{path.relative_to(ROOT)}: {bad}")
        if other_hues.search(src):
            problems.append(f"{path.relative_to(ROOT)}: {other_hues.search(src).group(0)}")
    assert not problems, problems
