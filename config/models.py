from django.db import models

# Create your models here.
# apps/config/models.py
from django.db import models


class Etablissement(models.Model):
    nom = models.CharField(max_length=200)
    sigle = models.CharField(max_length=20, blank=True)
    adresse = models.TextField()

    # ✅ NOUVEAU : Téléphone principal
    telephone1 = models.CharField(
        max_length=20,
        verbose_name="Téléphone principal",
        blank=True,
        null=True
    )

    # ✅ NOUVEAU : Téléphone secondaire
    telephone2 = models.CharField(
        max_length=20,
        verbose_name="Téléphone secondaire",
        blank=True,
        null=True
    )

    # Garder l'email
    email = models.EmailField(blank=True, null=True)
    site_web = models.URLField(blank=True, null=True)
    logo = models.ImageField(upload_to='etablissement/', blank=True, null=True)
    devise = models.CharField(max_length=10, default='F CFA')

    systeme_notation = models.CharField(
        max_length=20,
        choices=[('sur20', 'Sur 20'), ('sur100', 'Sur 100'),
                 ('lettre', 'Lettres')],
        default='sur20'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Établissement"
        verbose_name_plural = "Établissements"

    def __str__(self):
        return self.nom
