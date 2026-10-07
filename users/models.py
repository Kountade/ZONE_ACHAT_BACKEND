# apps/users/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.base_user import BaseUserManager
from django_rest_passwordreset.signals import reset_password_token_created
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is a required field')

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)

    def create_admin(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)

    def create_gestionnaire(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'gestionnaire')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)

    def create_comptable(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'comptable')
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)

    def create_magasinier(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'magasinier')
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)

    def create_caissier(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'caissier')
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)

    def create_livreur(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'livreur')
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)

    def create_vendeur(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'vendeur')
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)

    def create_client(self, email, password=None, **extra_fields):
        """Créer un utilisateur avec le rôle client (non approuvé par défaut)"""
        extra_fields.setdefault('role', 'client')
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_approved', False)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Administrateur'),
        ('gestionnaire', 'Gestionnaire'),
        ('comptable', 'Comptable'),
        ('magasinier', 'Magasinier'),
        ('caissier', 'Caissier'),
        ('livreur', 'Livreur'),
        ('vendeur', 'Vendeur'),
        ('client', 'Client'),
    )

    email = models.EmailField(max_length=200, unique=True)
    birthday = models.DateField(null=True, blank=True)
    username = models.CharField(max_length=200, null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    profile_picture = models.ImageField(
        upload_to='profiles/', null=True, blank=True)

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='vendeur'
    )

    # ✅ Validation admin pour les clients
    is_approved = models.BooleanField(
        default=True,
        verbose_name="Approuvé par un administrateur",
        help_text="Les clients doivent être approuvés par un admin avant de pouvoir accéder à leur espace"
    )

    # ✅ Lien vers un Client existant
    client_profile = models.ForeignKey(
        'ventes_clients.Client',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='user_accounts',
        verbose_name="Profil client lié",
        help_text="Si ce compte utilisateur correspond à un client existant"
    )

    # Champs supplémentaires
    is_online = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'
        ordering = ['-date_joined']

    def __str__(self):
        return f"{self.get_full_name() or self.email} ({self.get_role_display()})"

    # ============ Propriétés de vérification des rôles ============
    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_gestionnaire(self):
        return self.role == 'gestionnaire'

    @property
    def is_comptable(self):
        return self.role == 'comptable'

    @property
    def is_magasinier(self):
        return self.role == 'magasinier'

    @property
    def is_caissier(self):
        return self.role == 'caissier'

    @property
    def is_livreur(self):
        return self.role == 'livreur'

    @property
    def is_vendeur(self):
        return self.role == 'vendeur'

    @property
    def is_client(self):
        return self.role == 'client'

    @property
    def has_admin_access(self):
        return self.role in ['admin', 'gestionnaire']

    @property
    def can_access_client_space(self):
        """Le client peut accéder à son espace s'il est approuvé et actif"""
        return (
            self.role == 'client'
            and self.is_approved
            and self.is_active
        )

    def get_full_name(self):
        if self.first_name or self.last_name:
            return f"{self.first_name} {self.last_name}".strip()
        return self.username or self.email

    # ============ Méthode pour changer le rôle ============
    def change_role(self, new_role):
        if new_role in dict(self.ROLE_CHOICES).keys():
            self.role = new_role
            if new_role == 'admin':
                self.is_staff = True
                self.is_superuser = True
            elif new_role == 'gestionnaire':
                self.is_staff = True
                self.is_superuser = False
            else:
                self.is_staff = False
                self.is_superuser = False
            self.save()
            return True
        return False

    # ============ Permissions par rôle ============
    def get_permissions(self):
        permissions = {
            'admin': [
                'view_all', 'edit_all', 'manage_users',
                'view_finances', 'edit_finances', 'generate_reports',
                'view_products', 'edit_products', 'manage_stock',
                'process_sales', 'view_sales', 'manage_cash',
                'view_deliveries', 'update_delivery_status',
                'delete_data', 'manage_lots', 'manage_inventory',
                'manage_expiry_alerts', 'approve_clients',
            ],
            'gestionnaire': [
                'view_all', 'edit_all',
                'view_finances', 'generate_reports',
                'view_products', 'edit_products', 'manage_stock',
                'process_sales', 'view_sales', 'manage_cash',
                'view_deliveries', 'update_delivery_status',
                'manage_lots', 'manage_inventory', 'manage_expiry_alerts',
                'approve_clients',
            ],
            'comptable': [
                'view_finances', 'edit_finances', 'generate_reports',
                'view_sales', 'view_products',
            ],
            'magasinier': [
                'view_products', 'edit_products', 'manage_stock',
                'view_sales', 'manage_lots', 'manage_inventory',
                'manage_expiry_alerts',
            ],
            'caissier': [
                'process_sales', 'view_sales', 'manage_cash',
                'view_products', 'view_stock',
            ],
            'livreur': [
                'view_deliveries', 'update_delivery_status',
                'view_sales',
            ],
            'vendeur': [
                'process_sales', 'view_sales', 'manage_cash',
                'view_products',
            ],
            'client': [
                'view_own_orders',
                'view_own_invoices',
                'view_own_payments',
                'view_own_wallet',
                'view_own_stock',
                'view_products',
            ],
        }
        return permissions.get(self.role, [])

    def has_permission(self, permission):
        return permission in self.get_permissions()


@receiver(reset_password_token_created)
def password_reset_token_created(reset_password_token, *args, **kwargs):
    sitelink = "http://localhost:5173/"
    token = "{}".format(reset_password_token.key)
    full_link = str(sitelink) + str("password-reset/") + str(token)

    print(f"Token généré: {token}")
    print(f"Lien complet: {full_link}")

    context = {
        'full_link': full_link,
        'email_address': reset_password_token.user.email,
        'user_name': reset_password_token.user.get_full_name() or reset_password_token.user.email,
        'role': reset_password_token.user.get_role_display()
    }

    html_message = render_to_string("backend/email.html", context=context)
    plain_message = strip_tags(html_message)

    msg = EmailMultiAlternatives(
        subject=f"Réinitialisation de votre mot de passe",
        body=plain_message,
        from_email="codelivecamp@gmail.com",
        to=[reset_password_token.user.email]
    )

    msg.attach_alternative(html_message, "text/html")
    msg.send()