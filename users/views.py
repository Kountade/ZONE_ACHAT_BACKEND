from django.shortcuts import render

# Create your views here.
# views.py
from rest_framework import viewsets, permissions, status
from .serializers import (
    LoginSerializer, RegisterSerializer, UserSerializer,
    UserDetailSerializer, UserWriteSerializer
)
from django.contrib.auth import get_user_model, authenticate
from rest_framework.response import Response
from knox.models import AuthToken
from .permissions import IsAdmin  # Importez vos permissions

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
                _, token = AuthToken.objects.create(user)
                return Response({
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "role": user.role
                    },
                    "token": token
                })
            else:
                return Response({"error": "Identifiants invalides ou compte désactivé"}, status=401)
        return Response(serializer.errors, status=400)


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
                    "role": user.role
                }
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


class UserViewset(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UserWriteSerializer
        return UserSerializer

    # CORRECTION ICI : Vérifier si l'utilisateur est admin (pas super_admin)
    def is_admin(self, user):
        return user.role == 'admin'  # Changé de 'super_admin' à 'admin'

    def list(self, request):
        # Les admins voient tous les utilisateurs
        if self.is_admin(request.user):
            queryset = User.objects.all().order_by('-created_at')
        else:
            # Les vendeurs voient seulement leur propre profil
            queryset = User.objects.filter(id=request.user.id)
        serializer = UserSerializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request):
        # Seuls les admins peuvent créer des utilisateurs
        if not self.is_admin(request.user):
            return Response(
                {"error": "Seul un administrateur peut créer des utilisateurs"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = UserWriteSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            # Si le champ created_by existe dans votre modèle
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

        # Admin peut voir n'importe quel utilisateur
        if self.is_admin(request.user):
            serializer = UserDetailSerializer(user)
            return Response(serializer.data)

        # Vendeur ne peut voir que son propre profil
        if request.user.id == user.id:
            serializer = UserDetailSerializer(user)
            return Response(serializer.data)

        return Response({"error": "Permission refusée"}, status=403)

    def update(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)

        # Admin peut modifier n'importe quel utilisateur
        if self.is_admin(request.user):
            serializer = UserWriteSerializer(user, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        # Vendeur ne peut modifier que son propre profil
        if request.user.id == user.id:
            serializer = UserWriteSerializer(user, data=request.data)
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

        # Admin peut modifier n'importe quel utilisateur
        if self.is_admin(request.user):
            serializer = UserWriteSerializer(
                user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        # Vendeur ne peut modifier que son propre profil
        if request.user.id == user.id:
            serializer = UserWriteSerializer(
                user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        return Response({"error": "Permission refusée"}, status=403)

    def destroy(self, request, pk=None):
        # Seul un admin peut supprimer des utilisateurs
        if not self.is_admin(request.user):
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
        serializer = UserWriteSerializer(
            request.user, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(UserDetailSerializer(request.user).data)
        return Response(serializer.errors, status=400)
