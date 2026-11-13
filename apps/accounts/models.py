import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class Language(models.TextChoices):
    FR = "fr", "Français"
    AR = "ar", "العربية"
    EN = "en", "English"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **fields):
        if not email:
            raise ValueError("email is required")
        user = self.model(email=self.normalize_email(email).lower(), **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **fields):
        fields.update(is_staff=True, is_superuser=True, email_verified_at=timezone.now())
        return self.create_user(email, password, **fields)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email)


class User(AbstractBaseUser, PermissionsMixin):
    """One account per person (email). Access to stores goes through `stores.Membership`;
    Mahali team members additionally have a `console.PlatformStaff` profile."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)  # always stored lowercase
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.FR)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    # Set the first time the Mahali team validates one of this person's stores (ID checked).
    identity_verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin only
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="uniq_user_email_ci")]

    def __str__(self):
        return self.email

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None


class EmailCode(models.Model):
    """6-digit code sent by email. Only a hash is stored."""

    class Purpose(models.TextChoices):
        VERIFY_EMAIL = "verify_email"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_codes")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class UserSession(models.Model):
    """One signed-in device. Its id is the `sid` claim of every token issued for it,
    so revoking the session kills its access and refresh tokens immediately."""

    class Realm(models.TextChoices):
        MERCHANT = "merchant"
        CONSOLE = "console"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    realm = models.CharField(max_length=10, choices=Realm.choices)
    user_agent = models.CharField(max_length=300, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    # "Log in as" from the console: read-only, limited to one store, short-lived.
    impersonator = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    impersonated_store = models.ForeignKey(
        "stores.Store", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        if self.revoked_at:
            return False
        return not (self.expires_at and self.expires_at <= timezone.now())

    def revoke(self):
        if not self.revoked_at:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])
