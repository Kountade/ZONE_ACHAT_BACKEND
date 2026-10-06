from django.apps import AppConfig


class TresorerieConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tresorerie'

    def ready(self):
        import tresorerie.signals
        print("✅ TRESORERIE SIGNALS CHARGES")
