# apps/users/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth import get_user_model, authenticate
from knox.models import AuthToken
from django.db.models import Q

from .serializers import (
    LoginSerializer, RegisterSerializer, ClientRegisterSerializer,
    UserSerializer, UserDetailSerializer, UserWriteSerializer,
    ClientApprovalSerializer
)
from .permissions import IsAdmin, IsGestionnaire, CanApproveClients

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
                user.is_online = True
                user.last_login_ip = self._get_client_ip(request)
                user.save(update_fields=['is_online', 'last_login_ip'])

                _, token = AuthToken.objects.create(user)

                is_approved = getattr(user, 'is_approved', True)
                can_access_client_space = (
                    user.can_access_client_space
                    if hasattr(user, 'can_access_client_space') and user.role == 'client'
                    else True
                )

                # Message d'avertissement si client non approuvé
                warning_message = None
                if user.role == 'client' and not is_approved:
                    warning_message = (
                        "Votre compte est en attente d'approbation. "
                        "Certaines fonctionnalités sont limitées."
                    )

                return Response({
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "full_name": user.get_full_name(),
                        "role": user.role,
                        "role_display": user.get_role_display(),
                        "is_approved": is_approved,
                        "can_access_client_space": can_access_client_space,
                        "client_profile_id": (
                            user.client_profile.id
                            if user.client_profile
                            else None
                        ),
                    },
                    "token": token,
                    "warning": warning_message,
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
    """Inscription interne (admin)"""
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


class ClientRegisterViewset(viewsets.ViewSet):
    """
    Endpoint public d'inscription pour les CLIENTS uniquement.
    Le compte est créé avec rôle='client' et is_approved=False.
    Un admin doit l'approuver pour qu'il puisse accéder à son espace.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = ClientRegisterSerializer

    def create(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                "message": (
                    "Votre compte a été créé avec succès. "
                    "Il est en attente d'approbation par un administrateur. "
                    "Vous recevrez une notification dès que votre compte sera activé."
                ),
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.get_full_name(),
                    "role": user.role,
                    "is_approved": user.is_approved,
                }
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


class UserViewset(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UserWriteSerializer
        return UserSerializer

    ADMIN_ROLES = ['admin', 'gestionnaire']

    def is_admin(self, user):
        return user.role in self.ADMIN_ROLES

    def list(self, request):
        if self.is_admin(request.user):
            queryset = User.objects.all().order_by('-created_at')

            role_filter = request.query_params.get('role')
            if role_filter:
                queryset = queryset.filter(role=role_filter)

            is_approved = request.query_params.get('is_approved')
            if is_approved is not None:
                queryset = queryset.filter(
                    is_approved=is_approved.lower() == 'true')

            is_active = request.query_params.get('is_active')
            if is_active is not None:
                queryset = queryset.filter(
                    is_active=is_active.lower() == 'true')

            search = request.query_params.get('search')
            if search:
                queryset = queryset.filter(
                    Q(email__icontains=search) |
                    Q(first_name__icontains=search) |
                    Q(last_name__icontains=search) |
                    Q(phone_number__icontains=search)
                )

            serializer = UserSerializer(queryset, many=True)
            return Response(serializer.data)

        queryset = User.objects.filter(id=request.user.id)
        serializer = UserSerializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request):
        if request.user.role != 'admin':
            return Response(
                {"error": "Seul un administrateur peut créer des utilisateurs"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = UserWriteSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def retrieve(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)

        if self.is_admin(request.user):
            serializer = UserDetailSerializer(user)
            return Response(serializer.data)

        if request.user.id == user.id:
            serializer = UserDetailSerializer(user)
            return Response(serializer.data)

        return Response({"error": "Permission refusée"}, status=403)

    def update(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)

        if self.is_admin(request.user):
            serializer = UserWriteSerializer(user, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        if request.user.id == user.id:
            data = request.data.copy()
            data.pop('role', None)
            data.pop('is_approved', None)
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
            data.pop('is_approved', None)
            serializer = UserWriteSerializer(user, data=data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(UserSerializer(user).data)
            return Response(serializer.errors, status=400)

        return Response({"error": "Permission refusée"}, status=403)

    def destroy(self, request, pk=None):
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

    # ============================================================
    # ACTIONS CLIENTS
    # ============================================================

    @action(detail=True, methods=['post'], url_path='approve',
            permission_classes=[CanApproveClients])
    def approve_client(self, request, pk=None):
        """Approuver un compte client en attente"""
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error": "Utilisateur non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )

        if user.role != 'client':
            return Response(
                {"error": "Seuls les clients peuvent être approuvés via cet endpoint"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if user.is_approved:
            return Response(
                {"error": "Ce client est déjà approuvé"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_approved = True
        user.is_active = True
        user.save(update_fields=['is_approved', 'is_active', 'updated_at'])

        return Response({
            'status': 'success',
            'message': f'Le client {user.email} a été approuvé avec succès',
            'user': UserSerializer(user).data
        })

    @action(detail=True, methods=['post'], url_path='reject',
            permission_classes=[CanApproveClients])
    def reject_client(self, request, pk=None):
        """Rejeter un compte client en attente"""
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error": "Utilisateur non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )

        if user.role != 'client':
            return Response(
                {"error": "Seuls les clients peuvent être rejetés via cet endpoint"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_active = False
        user.is_approved = False
        user.save(update_fields=['is_active', 'is_approved', 'updated_at'])

        return Response({
            'status': 'success',
            'message': f'Le client {user.email} a été rejeté',
            'user': UserSerializer(user).data
        })

    @action(detail=False, methods=['get'], url_path='pending-clients',
            permission_classes=[CanApproveClients])
    def pending_clients(self, request):
        """Liste tous les clients en attente d'approbation"""
        clients = User.objects.filter(
            role='client',
            is_approved=False,
            is_active=True
        ).order_by('-created_at')

        return Response({
            'count': clients.count(),
            'results': UserSerializer(clients, many=True).data
        })

    @action(detail=False, methods=['get'], url_path='approved-clients',
            permission_classes=[CanApproveClients])
    def approved_clients(self, request):
        """Liste tous les clients approuvés"""
        clients = User.objects.filter(
            role='client',
            is_approved=True,
            is_active=True
        ).order_by('-created_at')

        return Response({
            'count': clients.count(),
            'results': UserSerializer(clients, many=True).data
        })


class ProfileViewset(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserDetailSerializer

    def retrieve(self, request):
        serializer = self.serializer_class(request.user)
        return Response(serializer.data)

    def update(self, request):
        data = request.data.copy()
        data.pop('role', None)
        data.pop('is_approved', None)
        serializer = UserWriteSerializer(
            request.user, data=data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(UserDetailSerializer(request.user).data)
        return Response(serializer.errors, status=400)