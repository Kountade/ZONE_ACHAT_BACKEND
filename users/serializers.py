# serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import CustomUser

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class RegisterSerializer(serializers.ModelSerializer):
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
            # Changé de 'commercial' à 'vendeur'
            validated_data['role'] = 'vendeur'
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    """Sérialiseur de lecture pour la liste des utilisateurs."""
    class Meta:
        model = User
        fields = (
            'id', 'email', 'username', 'role',
            'phone_number', 'is_active', 'profile_picture', 'created_at'
        )
        read_only_fields = fields


class UserDetailSerializer(serializers.ModelSerializer):
    """Sérialiseur de lecture détaillée."""
    class Meta:
        model = User
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at', 'last_login')


class UserWriteSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour la création et modification d'utilisateurs.
    """
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            'email', 'password', 'username', 'role',
            'first_name', 'last_name', 'phone_number',
            'address', 'birthday', 'is_active'
        ]

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        # Si aucun rôle n'est spécifié, mettre 'vendeur' par défaut
        if 'role' not in validated_data:
            validated_data['role'] = 'vendeur'
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
