from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "full_name", "email_verified_at", "is_active"]
    search_fields = ["email", "full_name"]
    fieldsets = [
        (None, {"fields": ["email", "password", "full_name", "phone", "language"]}),
        ("Status", {"fields": ["is_active", "email_verified_at", "identity_verified_at"]}),
        ("Admin", {"fields": ["is_staff", "is_superuser"]}),
    ]
    add_fieldsets = [(None, {"fields": ["email", "full_name", "password1", "password2"]})]
