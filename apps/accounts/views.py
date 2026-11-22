from django.contrib import messages
from django.contrib.auth import authenticate
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.middleware import client_ip
from apps.core.permissions import login_required

from . import ratelimit, services
from .forms import LoginForm, PasswordChangeForm


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:home")
    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        ip = client_ip(request)
        if ratelimit.is_blocked(phone, ip):
            error = _("Too many failed attempts. Try again in 15 minutes.")
        else:
            user = authenticate(request, username=phone, password=form.cleaned_data["password"])
            if user is None:
                ratelimit.register_failure(phone, ip)
                services.record_failed_login(phone)
                error = _("Wrong phone number or password.")
            else:
                ratelimit.reset(phone)
                services.log_in(request, user)
                target = request.GET.get("next") or "/"
                if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
                    target = "/"
                return redirect(target)
    return render(request, "accounts/login.html", {"form": form, "error": error})


@require_POST
def logout_view(request):
    services.log_out(request)
    return redirect("accounts:login")


@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.change_own_password(request, form.cleaned_data["new_password1"])
        messages.success(request, _("Password changed."))
        return redirect("accounts:profile")
    return render(
        request,
        "accounts/password_change.html",
        {"form": form, "forced": request.user.must_change_password},
    )


@login_required
def profile(request):
    return render(request, "accounts/profile.html")
