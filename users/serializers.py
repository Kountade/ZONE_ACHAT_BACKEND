# apps/users/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import CustomUser

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class ClientRegisterSerializer(serializers.ModelSerializer):
    """
    Inscription publique pour les CLIENTS uniquement.
    Le rôle est forcé à 'client' et is_approved=False par défaut.
    """
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'password', 'password2',
            'first_name', 'last_name', 'phone_number', 'address'
        ]
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
            'phone_number': {'required': True},
            'address': {'required': False},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Cet email est déjà utilisé")
        return value.lower()

    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError({
                'password2': "Les mots de passe ne correspondent pas"
            })
        return data

    def create(self, validated_data):
        validated_data.pop('password2')
        password = validated_data.pop('password')

        # ✅ Rôle TOUJOURS 'client'
        validated_data['role'] = 'client'
        validated_data['is_approved'] = False
        validated_data['is_active'] = True
        validated_data['is_staff'] = False
        validated_data['is_superuser'] = False

        user = User.objects.create_user(password=password, **validated_data)

        # ✅ Créer un profil Client et le lier
        try:
            from ventes_clients.models import Client

            # Vérifier si un client avec cet email existe déjà
            existing_client = Client.objects.filter(
                email__iexact=user.email
            ).first() if hasattr(Client, 'email') else None

            if existing_client:
                user.client_profile = existing_client
                user.save(update_fields=['client_profile'])
            else:
                # Générer un code unique
                count = Client.objects.count()
                code = f"CLI-{count + 1:05d}"
                while Client.objects.filter(code=code).exists():
                    count += 1
                    code = f"CLI-{count + 1:05d}"

                new_client = Client.objects.create(
                    code=code,
                    name=f"{user.first_name} {user.last_name}".strip() or user.email,
                    phone=user.phone_number or '',
                    address=user.address or '',
                    statut='actif'
                )
                user.client_profile = new_client
                user.save(update_fields=['client_profile'])
        except Exception as e:
            print(f"⚠️ Erreur création profil client: {e}")

        return user


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer interne (utilisé par les admins pour créer des utilisateurs)"""
    role = serializers.ChoiceField(
        choices=CustomUser.ROLE_CHOICES, required=False
    )

    class Meta:
        model = User
        fields = ('id', 'email', 'password', 'role')
        extra_kwargs = {
            'password': {'write_only': True},
            'role': {'required': False}
        }

    def create(self, validated_data):
        if 'role' not in validated_data:
            validated_data['role'] = 'vendeur'
        validated_data.setdefault('is_approved', True)
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    """Sérialiseur de lecture pour la liste des utilisateurs."""
    role_display = serializers.CharField(
        source='get_role_display', read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'email', 'username', 'full_name', 'role', 'role_display',
            'phone_number', 'is_active', 'is_approved',
            'profile_picture', 'created_at'
        )
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()


class UserDetailSerializer(serializers.ModelSerializer):
    """Sérialiseur de lecture détaillée."""
    role_display = serializers.CharField(
        source='get_role_display', read_only=True)
    can_access_client_space = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at', 'last_login')


class UserWriteSerializer(serializers.ModelSerializer):
    """Sérialiseur pour la création et modification par les admins."""
    password = serializers.CharField(write_only=True, required=False)
    is_approved = serializers.BooleanField(required=False)

    class Meta:
        model = User
        fields = [
            'email', 'password', 'username', 'role',
            'first_name', 'last_name', 'phone_number',
            'address', 'birthday', 'is_active', 'is_approved'
        ]

    def validate_role(self, value):
        valid_roles = [choice[0] for choice in CustomUser.ROLE_CHOICES]
        if value not in valid_roles:
            raise serializers.ValidationError(
                f"Rôle invalide. Choix possibles : {', '.join(valid_roles)}"
            )
        return value

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        if 'role' not in validated_data:
            validated_data['role'] = 'vendeur'
        validated_data.setdefault('is_approved', True)
        user = User.objects.create_user(**validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user


class ClientApprovalSerializer(serializers.Serializer):
    """Serializer pour approuver/rejeter un client"""
    notes = serializers.CharField(required=False, allow_blank=True)