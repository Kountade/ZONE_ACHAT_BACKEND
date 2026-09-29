from django.shortcuts import render
from rest_framework import viewsets, permissions, status
from .serializers import (
    LoginSerializer, RegisterSerializer, UserSerializer,
    UserDetailSerializer, UserWriteSerializer
)
from django.contrib.auth import get_user_model, authenticate
from rest_framework.response import Response
from knox.models import AuthToken
from .permissions import IsAdmin

User = get_user_model()


class LoginViewset(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    def create(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            password = serializer.validated_data['password']
            user = authenticate(request, email=email, password=password)

            if user is not None and user.is_active:
                # Mettre à jour les infos de connexion
                user.is_online = True
                user.last_login_ip = self._get_client_ip(request)
                user.save(update_fields=['is_online', 'last_login_ip'])

                _, token = AuthToken.objects.create(user)
                return Response({
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "role": user.role,
                        "role_display": user.get_role_display(),
                    },
                    "token": token
                })
            else:
                return Response(
                    {"error": "Identifiants invalides ou compte désactivé"},
                    status=401
                )
        return Response(serializer.errors, status=400)

    @staticmethod
    def _get_client_ip(request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')


class RegisterViewset(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "role": user.role,
                    "role_display": user.get_role_display(),
                }
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


class UserViewset(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UserWriteSerializer
        return UserSerializer

    # Rôles autorisés à gérer les utilisateurs
    ADMIN_ROLES = ['admin', 'gestionnaire']

    def is_admin(self, user):
        """Vérifie si l'utilisateur a un rôle de gestion."""
        return user.role in self.ADMIN_ROLES

    def list(self, request):
        # Les admins/gestionnaires voient tous les utilisateurs
        if self.is_admin(request.user):
            queryset = User.objects.all().order_by('-created_at')

            # Filtres optionnels par rôle
            role_filter = request.query_params.get('role')
            if role_filter:
                queryset = queryset.filter(role=role_filter)

            # Filtre par statut actif
            is_active = request.query_params.get('is_active')
            if is_active is not None:
                queryset = queryset.filter(
                    is_active=is_active.lower() == 'true')

            serializer = UserSerializer(queryset, many=True)
            return Response(serializer.data)

        # Les autres voient seulement leur propre profil
        queryset = User.objects.filter(id=request.user.id)
        serializer = UserSerializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request):
        # Seuls les admins peuvent créer des utilisateurs
        if request.user.role != 'admin':
            return Response(
                {"error": "Seul un administrateur peut créer des utilisateurs"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = UserWriteSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            if hasattr(user, 'created_by'):
                user.created_by = request.user
                user.save(update_fields=['created_by'])
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def retrieve(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)

        # Admin/gestionnaire peut voir n'importe quel utilisateur
        if self.is_admin(request.user):
            serializer = UserDetailSerializer(user)
            return Response(serializer.data)

        # Un utilisateur peut voir son propre profil
        if request.user.id == user.id:
            serializer = UserDetailSerializer(user)
            return Response(serializer.data)

        return Response({"error": "Permission refusée"}, status=403)

    def update(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)

        # Seul un admin peut modifier un autre utilisateur
        if self.is_admin(request.user):
            serializer = UserWriteSerializer(user, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        # Un utilisateur peut modifier son propre profil
        if request.user.id == user.id:
            # Un non-admin ne peut pas changer son propre rôle
            data = request.data.copy()
            data.pop('role', None)
            serializer = UserWriteSerializer(user, data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        return Response({"error": "Permission refusée"}, status=403)

    def partial_update(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)

        if self.is_admin(request.user):
            serializer = UserWriteSerializer(
                user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        if request.user.id == user.id:
            data = request.data.copy()
            data.pop('role', None)
            serializer = UserWriteSerializer(user, data=data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        return Response({"error": "Permission refusée"}, status=403)

    def destroy(self, request, pk=None):
        # Seul un admin peut supprimer des utilisateurs
        if request.user.role != 'admin':
            return Response(
                {"error": "Seul un administrateur peut supprimer des utilisateurs"},
                status=403
            )

        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)

        if user.id == request.user.id:
            return Response(
                {"error": "Vous ne pouvez pas supprimer votre propre compte"},
                status=400
            )

        user.delete()
        return Response(status=204)


class ProfileViewset(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserDetailSerializer

    def retrieve(self, request):
        serializer = self.serializer_class(request.user)
        return Response(serializer.data)

    def update(self, request):
        # Empêcher la modification du rôle via le profil
        data = request.data.copy()
        data.pop('role', None)
        serializer = UserWriteSerializer(
            request.user, data=data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(UserDetailSerializer(request.user).data)
        return Response(serializer.errors, status=400)
