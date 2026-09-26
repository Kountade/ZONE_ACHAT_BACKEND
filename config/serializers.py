# apps/config/serializers.py
from rest_framework import serializers
from .models import Etablissement
from PIL import Image
import os
import logging

logger = logging.getLogger(__name__)

# ========================================
# VALIDATEUR D'IMAGE
# ========================================


def validate_image_file(value):
    valid_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']
    ext = os.path.splitext(value.name)[1].lower().lstrip('.')

    if ext not in valid_extensions:
        raise serializers.ValidationError(
            f"Format non supporté. Utilisez : {', '.join(valid_extensions)}"
        )

    if value.size > 5 * 1024 * 1024:
        raise serializers.ValidationError(
            "Le fichier ne doit pas dépasser 5 Mo."
        )

    if ext == 'svg':
        content = value.read(1024)
        value.seek(0)
        if not content.startswith(b'<svg') and not content.startswith(b'<?xml'):
            raise serializers.ValidationError("Le fichier SVG est invalide.")
        return value

    try:
        value.seek(0)
        img = Image.open(value)
        img.verify()
        value.seek(0)
        img = Image.open(value)
        if img.width <= 0 or img.height <= 0:
            raise serializers.ValidationError(
                "L'image a des dimensions invalides."
            )
        return value
    except Exception as e:
        logger.error(f"Erreur validation image : {str(e)}")
        raise serializers.ValidationError(
            f"Le fichier n'est pas une image valide ou est corrompu. Détail : {str(e)}"
        )


# ========================================
# SÉRIALIZER DE L'ÉTABLISSEMENT
# ========================================

class EtablissementSerializer(serializers.ModelSerializer):
    logo = serializers.ImageField(
        validators=[validate_image_file],
        required=False,
        allow_null=True
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Etablissement
        fields = [
            'id', 'nom', 'sigle', 'adresse',
            'telephone1', 'telephone2',  # ✅ Nouveaux champs
            'email', 'site_web', 'logo', 'devise', 'systeme_notation',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_nom(self, value):
        if not value or len(value.strip()) < 2:
            raise serializers.ValidationError(
                "Le nom doit contenir au moins 2 caractères."
            )
        return value.strip()

    def validate_email(self, value):
        if value and '@' not in value:
            raise serializers.ValidationError("Adresse email invalide.")
        return value

    # ✅ Validation pour telephone1 et telephone2
    def validate_telephone1(self, value):
        if value:
            cleaned = ''.join(c for c in value if c.isdigit() or c in '+ -')
            if len(cleaned) < 8:
                raise serializers.ValidationError(
                    "Le numéro de téléphone principal est trop court (minimum 8 chiffres)."
                )
        return value

    def validate_telephone2(self, value):
        if value:
            cleaned = ''.join(c for c in value if c.isdigit() or c in '+ -')
            if len(cleaned) < 8:
                raise serializers.ValidationError(
                    "Le numéro de téléphone secondaire est trop court (minimum 8 chiffres)."
                )
        return value
