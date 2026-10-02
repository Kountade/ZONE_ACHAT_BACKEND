# apps/achats_fournisseurs/apps.py
from django.apps import AppConfig


class AchatsFournisseursConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'achats_fournisseurs'  # ✅ Nom correct sans 'apps.'
    verbose_name = "Achats et Fournisseurs"

    def ready(self):
        import achats_fournisseurs.signals
