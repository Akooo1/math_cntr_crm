"""Django's own messages that its Uzbek catalog leaves untranslated.

Listing them here lets `makemessages` pull them into locale/uz/.../django.po, where our
translation overrides Django's (LOCALE_PATHS wins). Never imported at runtime.
"""

from django.utils.translation import gettext_noop, ngettext_lazy

STRINGS = [
    gettext_noop("Constraint “%(name)s” is violated."),
    gettext_noop("Ensure this value is a multiple of step size %(limit_value)s."),
    gettext_noop(
        "ManagementForm data is missing or has been tampered with. Missing fields: "
        "%(field_names)s. You may need to file a bug report if the issue persists."
    ),
    gettext_noop("…"),
]

PLURALS = [
    ngettext_lazy(
        "Please submit at most %(num)d form.", "Please submit at most %(num)d forms.", "num"
    ),
    ngettext_lazy(
        "Please submit at least %(num)d form.", "Please submit at least %(num)d forms.", "num"
    ),
]
