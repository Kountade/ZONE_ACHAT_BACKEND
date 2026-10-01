from django.db import models

# Create your models here.
# apps/tresorerie/models.py
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from users.models import CustomUser
from produits_stocks.models import Warehouse

# ⚠️ AUCUN IMPORT DE achats_fournisseurs OU finances ICI


# ============================================================
# CONSTANTES - DOIVENT ÊTRE DÉFINIES AVANT LES MODÈLES
# ============================================================

TYPE_MOUVEMENT = (
    ('encaissement', 'Encaissement'),
    ('decaissement', 'Décaissement'),
)

SOURCE_TYPE = (
    ('vente', 'Vente'),
    ('achat', 'Achat'),
    ('facture_client', 'Facture client'),
    ('facture_fournisseur', 'Facture fournisseur'),
    ('paiement_client', 'Paiement client'),
    ('paiement_fournisseur', 'Paiement fournisseur'),
    ('frais', 'Frais'),
    ('caisse', 'Caisse'),
    ('compte_bancaire', 'Compte bancaire'),
    ('autre', 'Autre'),
)

MODE_PAIEMENT = (
    ('especes', 'Espèces'),
    ('carte', 'Carte bancaire'),
    ('cheque', 'Chèque'),
    ('virement', 'Virement'),
    ('mobile_money', 'Mobile Money'),
    ('prelevement', 'Prélèvement'),
    ('autre', 'Autre'),
)

STATUS_CHOICES = (
    ('planifie', 'Planifié'),
    ('en_attente', 'En attente'),
    ('effectue', 'Effectué'),
    ('annule', 'Annulé'),
    ('rejete', 'Rejeté'),
)


# ============================================================
# 1. CAISSES
# ============================================================

class Caisse(models.Model):
    """Caisse physique ou virtuelle"""
    TYPE_CAISSE = (
        ('principale', 'Caisse principale'),
        ('secondaire', 'Caisse secondaire'),
        ('mobile', 'Caisse mobile'),
        ('virtuelle', 'Caisse virtuelle'),
    )

    code = models.CharField(max_length=20, unique=True,
                            verbose_name="Code caisse")
    nom = models.CharField(max_length=100, verbose_name="Nom de la caisse")
    type_caisse = models.CharField(
        max_length=20, choices=TYPE_CAISSE, default='principale', verbose_name="Type de caisse")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='caisses', verbose_name="Entrepôt/Magasin")
    responsable = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='caisses_gerrees', verbose_name="Responsable")
    solde_initial = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Solde initial")
    solde_actuel = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Solde actuel")
    seuil_min = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Seuil minimum")
    seuil_max = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Seuil maximum")
    devise = models.CharField(
        max_length=3, default='XOF', verbose_name="Devise")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    is_default = models.BooleanField(
        default=False, verbose_name="Caisse par défaut")
    description = models.TextField(
        blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   null=True, related_name='caisses_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Caisse"
        verbose_name_plural = "Caisses"
        ordering = ['code']
        unique_together = ['warehouse', 'code']

    def __str__(self):
        return f"{self.code} - {self.nom} ({self.warehouse.name})"

    def save(self, *args, **kwargs):
        if self.is_default:
            Caisse.objects.filter(warehouse=self.warehouse,
                                  is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def est_sous_seuil_min(self):
        return self.solde_actuel < self.seuil_min

    @property
    def est_sur_seuil_max(self):
        return self.seuil_max > 0 and self.solde_actuel > self.seuil_max

    def mettre_a_jour_solde(self):
        """Met à jour le solde de la caisse"""
        from .models import MouvementTresorerie
        from django.db.models import Sum

        total_entrees = MouvementTresorerie.objects.filter(
            caisse=self,
            type_mouvement='encaissement',
            status='effectue'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        total_sorties = MouvementTresorerie.objects.filter(
            caisse=self,
            type_mouvement='decaissement',
            status='effectue'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        self.solde_actuel = self.solde_initial + total_entrees - total_sorties
        self.save(update_fields=['solde_actuel'])


# ============================================================
# 2. COMPTES BANCAIRES
# ============================================================

class CompteBancaire(models.Model):
    """Compte bancaire de l'entreprise"""
    TYPE_COMPTE = (
        ('courant', 'Compte courant'),
        ('epargne', 'Compte épargne'),
        ('bloque', 'Compte bloqué'),
    )

    banque = models.CharField(max_length=100, verbose_name="Banque")
    code = models.CharField(max_length=20, unique=True,
                            verbose_name="Code compte")
    nom = models.CharField(max_length=100, verbose_name="Nom du compte")
    type_compte = models.CharField(
        max_length=20, choices=TYPE_COMPTE, default='courant', verbose_name="Type de compte")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT,
                                  related_name='comptes_bancaires', verbose_name="Entrepôt/Magasin")
    numero_compte = models.CharField(
        max_length=50, verbose_name="Numéro de compte")
    iban = models.CharField(max_length=34, blank=True,
                            null=True, verbose_name="IBAN")
    bic = models.CharField(max_length=11, blank=True,
                           null=True, verbose_name="BIC/SWIFT")
    devise = models.CharField(
        max_length=3, default='XOF', verbose_name="Devise")
    solde_initial = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Solde initial")
    solde_actuel = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Solde actuel")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_default = models.BooleanField(
        default=False, verbose_name="Compte par défaut")
    date_ouverture = models.DateField(
        default=timezone.now, verbose_name="Date d'ouverture")
    description = models.TextField(
        blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   related_name='comptes_bancaires_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Compte bancaire"
        verbose_name_plural = "Comptes bancaires"
        ordering = ['banque', 'code']
        unique_together = ['warehouse', 'code', 'numero_compte']

    def __str__(self):
        return f"{self.banque} - {self.nom} ({self.numero_compte})"

    def mettre_a_jour_solde(self):
        """Met à jour le solde du compte bancaire"""
        from .models import MouvementTresorerie
        from django.db.models import Sum

        total_entrees = MouvementTresorerie.objects.filter(
            compte_bancaire=self,
            type_mouvement='encaissement',
            status='effectue'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        total_sorties = MouvementTresorerie.objects.filter(
            compte_bancaire=self,
            type_mouvement='decaissement',
            status='effectue'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        self.solde_actuel = self.solde_initial + total_entrees - total_sorties
        self.save(update_fields=['solde_actuel'])


# ============================================================
# 3. MOUVEMENTS DE TRÉSORERIE
# ============================================================

class MouvementTresorerie(models.Model):
    """Mouvement de trésorerie"""

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")
    type_mouvement = models.CharField(
        max_length=20, choices=TYPE_MOUVEMENT, verbose_name="Type de mouvement")

    # ✅ warehouse peut être null pour les paiements sans entrepôt
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='mouvements_tresorerie',
        verbose_name="Entrepôt/Magasin",
        null=True,
        blank=True
    )

    source_type = models.CharField(
        max_length=20, choices=SOURCE_TYPE, verbose_name="Type source")
    source_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID source")
    source_reference = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Référence source")

    montant = models.DecimalField(max_digits=15, decimal_places=2, validators=[
                                  MinValueValidator(0)], verbose_name="Montant")
    mode_paiement = models.CharField(
        max_length=20, choices=MODE_PAIEMENT, verbose_name="Mode de paiement")

    caisse = models.ForeignKey(Caisse, on_delete=models.SET_NULL, null=True,
                               blank=True, related_name='mouvements', verbose_name="Caisse")
    compte_bancaire = models.ForeignKey(CompteBancaire, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='mouvements', verbose_name="Compte bancaire")

    date_mouvement = models.DateTimeField(
        default=timezone.now, verbose_name="Date du mouvement")
    date_valeur = models.DateField(verbose_name="Date de valeur")
    date_prevue = models.DateField(
        null=True, blank=True, verbose_name="Date prévue")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='planifie', verbose_name="Statut")

    reference_externe = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Référence externe")
    piece_justificative = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Pièce justificative")

    date_rapprochement = models.DateField(
        null=True, blank=True, verbose_name="Date rapprochement")
    rapproche = models.BooleanField(default=False, verbose_name="Rapproché")

    libelle = models.CharField(max_length=200, verbose_name="Libellé")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   related_name='mouvements_tresorerie_crees', verbose_name="Créé par")
    valide_par = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='mouvements_tresorerie_valides', verbose_name="Validé par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Mouvement de trésorerie"
        verbose_name_plural = "Mouvements de trésorerie"
        ordering = ['-date_mouvement']

    def __str__(self):
        return f"{self.reference} - {self.type_mouvement} - {self.montant:,.0f} XOF"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"TRES{datetime.now().strftime('%Y%m')}"
            if self.type_mouvement == 'encaissement':
                prefix = f"ENC{datetime.now().strftime('%Y%m')}"
            elif self.type_mouvement == 'decaissement':
                prefix = f"DEC{datetime.now().strftime('%Y%m')}"

            last = MouvementTresorerie.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        super().save(*args, **kwargs)

    def get_source_object(self):
        """Récupère l'objet source avec import différé"""
        if not self.source_type or not self.source_id:
            return None

        if self.source_type == 'achat':
            try:
                from achats_fournisseurs.models import PurchaseOrder
                return PurchaseOrder.objects.get(id=self.source_id)
            except:
                return None
        elif self.source_type == 'facture_fournisseur':
            try:
                from achats_fournisseurs.models import SupplierInvoice
                return SupplierInvoice.objects.get(id=self.source_id)
            except:
                return None
        elif self.source_type == 'paiement_fournisseur':
            try:
                from achats_fournisseurs.models import FournisseurPaiement
                return FournisseurPaiement.objects.get(id=self.source_id)
            except:
                return None
        elif self.source_type == 'vente':
            try:
                from ventes_clients.models import Vente
                return Vente.objects.get(id=self.source_id)
            except:
                return None
        elif self.source_type == 'facture_client':
            try:
                from ventes_clients.models import Facture
                return Facture.objects.get(id=self.source_id)
            except:
                return None
        elif self.source_type == 'paiement_client':
            try:
                from ventes_clients.models import Paiement
                return Paiement.objects.get(id=self.source_id)
            except:
                return None
        return None

    @property
    def est_encaissement(self):
        return self.type_mouvement == 'encaissement'

    @property
    def est_decaissement(self):
        return self.type_mouvement == 'decaissement'

    @property
    def est_transfert(self):
        return self.source_type in ('caisse', 'compte_bancaire')

    def valider(self, user=None):
        """Valide le mouvement et met à jour les soldes"""
        if self.status == 'effectue':
            return False
        self.status = 'effectue'
        if user:
            self.valide_par = user
        self.date_validation = timezone.now()
        self.save()
        self._mettre_a_jour_soldes()
        return True

    def annuler(self, user=None):
        """Annule le mouvement et met à jour les soldes"""
        if self.status == 'annule':
            return False
        old_status = self.status
        self.status = 'annule'
        self.save()
        if old_status == 'effectue':
            self._mettre_a_jour_soldes()
        return True

    def _mettre_a_jour_soldes(self):
        """Met à jour les soldes de la caisse et/ou du compte bancaire"""
        if self.caisse:
            self.caisse.mettre_a_jour_solde()
        if self.compte_bancaire:
            self.compte_bancaire.mettre_a_jour_solde()


# ============================================================
# 4. FRAIS ET DÉPENSES (CORRIGÉ)
# ============================================================

class Frais(models.Model):
    """Frais et dépenses diverses"""
    CATEGORIE_FRAIS = (
        ('transport', 'Transport'),
        ('restauration', 'Restauration'),
        ('fournitures', 'Fournitures de bureau'),
        ('communication', 'Communication'),
        ('entretien', 'Entretien'),
        ('formation', 'Formation'),
        ('mission', 'Mission'),
        ('representations', 'Représentation'),
        ('assurances', 'Assurances'),
        ('impots', 'Impôts et taxes'),
        ('loyer', 'Loyer'),
        ('services', 'Services'),
        ('fournisseur', 'Paiement fournisseur'),
        ('autre', 'Autre'),
    )

    STATUS_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_attente', 'En attente de validation'),
        ('valide', 'Validé'),
        ('paye', 'Payé'),
        ('refuse', 'Refusé'),
        ('annule', 'Annulé'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")
    titre = models.CharField(max_length=200, verbose_name="Titre")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='frais', verbose_name="Entrepôt/Magasin")
    categorie = models.CharField(
        max_length=20, choices=CATEGORIE_FRAIS, verbose_name="Catégorie")
    montant = models.DecimalField(
        max_digits=15, decimal_places=2, validators=[MinValueValidator(0)], verbose_name="Montant")
    date_frais = models.DateField(
        default=timezone.now, verbose_name="Date du frais")
    date_paiement = models.DateField(
        null=True, blank=True, verbose_name="Date de paiement")
    beneficiaire = models.CharField(
        max_length=200, verbose_name="Bénéficiaire")
    piece_justificative = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Pièce justificative")
    mode_paiement = models.CharField(
        max_length=20, choices=MODE_PAIEMENT, default='especes', verbose_name="Mode de paiement")

    # ⚠️ UTILISATION D'IntegerField pour éviter les imports circulaires
    mouvement_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Mouvement associé")
    supplier_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Fournisseur")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='brouillon', verbose_name="Statut")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='frais_crees', verbose_name="Créé par")
    valide_par = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='frais_valides', verbose_name="Validé par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Frais"
        verbose_name_plural = "Frais"
        ordering = ['-date_frais']

    def __str__(self):
        return f"{self.reference} - {self.titre} ({self.montant:,.0f} XOF)"

    def save(self, *args, **kwargs):
        """
        ✅ CORRECTION : On sauvegarde d'abord l'objet pour avoir un ID,
        puis on crée le mouvement associé avec le bon source_id.
        """
        from django.core.exceptions import ValidationError

        # ---- 1. Génération de la référence ----
        if not self.reference:
            from datetime import datetime
            prefix = f"FRAIS{datetime.now().strftime('%Y%m')}"
            last = Frais.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        # ---- 2. Premier save pour obtenir un ID valide ----
        super().save(*args, **kwargs)

        # ---- 3. Créer le mouvement si le frais est payé ----
        if self.status == 'paye' and not self.mouvement_id:
            from .models import MouvementTresorerie, Caisse

            caisse_defaut = Caisse.objects.filter(
                warehouse=self.warehouse, is_default=True).first()
            if not caisse_defaut:
                raise ValidationError(
                    f"Aucune caisse par défaut pour l'entrepôt '{self.warehouse.name}'. "
                    "Veuillez configurer une caisse par défaut."
                )

            mouvement = MouvementTresorerie.objects.create(
                type_mouvement='decaissement',
                warehouse=self.warehouse,
                source_type='frais',
                source_id=self.id,  # ✅ Maintenant valide !
                source_reference=self.reference,
                montant=self.montant,
                mode_paiement=self.mode_paiement,
                caisse=caisse_defaut,
                date_mouvement=timezone.now(),
                date_valeur=self.date_paiement or timezone.now().date(),
                status='effectue',
                libelle=f"Frais: {self.titre}",
                created_by=self.created_by
            )
            self.mouvement_id = mouvement.id
            # Re-sauvegarder pour persister mouvement_id
            super().save(update_fields=['mouvement_id'])

    def get_supplier(self):
        """Récupère le fournisseur associé (import différé)"""
        if self.supplier_id:
            try:
                from achats_fournisseurs.models import Supplier
                return Supplier.objects.get(id=self.supplier_id)
            except:
                return None
        return None

    def get_mouvement(self):
        """Récupère le mouvement de trésorerie associé"""
        if self.mouvement_id:
            try:
                return MouvementTresorerie.objects.get(id=self.mouvement_id)
            except MouvementTresorerie.DoesNotExist:
                return None
        return None


# ============================================================
# 5. PRÉVISIONS DE TRÉSORERIE
# ============================================================

class PrevisionTresorerie(models.Model):
    """Prévision de trésorerie"""
    PERIODE_CHOICES = (
        ('journalier', 'Journalier'),
        ('hebdomadaire', 'Hebdomadaire'),
        ('mensuel', 'Mensuel'),
        ('trimestriel', 'Trimestriel'),
        ('annuel', 'Annuel'),
    )

    TYPE_PREVISION = (
        ('entree', 'Entrée prévue'),
        ('sortie', 'Sortie prévue'),
    )

    STATUT_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_cours', 'En cours'),
        ('valide', 'Validée'),
        ('realise', 'Réalisé'),
        ('annule', 'Annulé'),
        ('ecart', 'Écart constaté'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")
    titre = models.CharField(max_length=200, verbose_name="Titre")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT,
                                  related_name='previsions_tresorerie', verbose_name="Entrepôt/Magasin")
    type_prevision = models.CharField(
        max_length=20, choices=TYPE_PREVISION, verbose_name="Type de prévision")
    periode = models.CharField(
        max_length=20, choices=PERIODE_CHOICES, default='mensuel', verbose_name="Période")
    montant_prevu = models.DecimalField(max_digits=15, decimal_places=2, validators=[
                                        MinValueValidator(0)], verbose_name="Montant prévu")
    montant_reel = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Montant réel")
    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")
    source_type = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Type source")
    source_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID source")
    categorie = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Catégorie")
    sous_categorie = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Sous-catégorie")
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default='brouillon', verbose_name="Statut")
    probabilite = models.IntegerField(default=50, validators=[MinValueValidator(
        0), MaxValueValidator(100)], verbose_name="Probabilité (%)")
    ecart = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Écart")
    pourcentage_ecart = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Pourcentage d'écart")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   null=True, related_name='previsions_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Prévision de trésorerie"
        verbose_name_plural = "Prévisions de trésorerie"
        ordering = ['-date_debut']

    def __str__(self):
        return f"{self.reference} - {self.titre} ({self.montant_prevu:,.0f} XOF)"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"PREV{datetime.now().strftime('%Y%m')}"
            last = PrevisionTresorerie.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        self.ecart = self.montant_reel - self.montant_prevu
        if self.montant_prevu > 0:
            self.pourcentage_ecart = (self.ecart / self.montant_prevu) * 100

        super().save(*args, **kwargs)


# ============================================================
# 6. RAPPROCHEMENT BANCAIRE
# ============================================================

class RapprochementBancaire(models.Model):
    """Rapprochement bancaire"""
    STATUS_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_cours', 'En cours'),
        ('partiel', 'Partiellement rapproché'),
        ('complete', 'Complètement rapproché'),
        ('ecart', 'Écart constaté'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT,
                                  related_name='rapprochements', verbose_name="Entrepôt/Magasin")
    compte_bancaire = models.ForeignKey(
        CompteBancaire, on_delete=models.PROTECT, related_name='rapprochements', verbose_name="Compte bancaire")
    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")
    solde_comptable = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Solde comptable")
    solde_bancaire = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Solde bancaire")
    solde_rapproche = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Solde rapproché")
    ecart = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Écart")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='brouillon', verbose_name="Statut")
    encours_emission = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="En-cours d'émission")
    encours_encaissement = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="En-cours d'encaissement")
    commissions = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Commissions bancaires")
    autres_ecarts = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Autres écarts")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   null=True, related_name='rapprochements_crees', verbose_name="Créé par")
    valide_par = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='rapprochements_valides', verbose_name="Validé par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Rapprochement bancaire"
        verbose_name_plural = "Rapprochements bancaires"
        ordering = ['-date_fin']
        unique_together = ['compte_bancaire', 'date_debut', 'date_fin']

    def __str__(self):
        return f"{self.reference} - {self.compte_bancaire.banque} ({self.date_debut} au {self.date_fin})"

    @property
    def est_rapproche(self):
        return self.status == 'complete' and abs(self.ecart) < 1

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"RAP{datetime.now().strftime('%Y%m')}"
            last = RapprochementBancaire.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        self.ecart = self.solde_comptable - self.solde_bancaire
        self.solde_rapproche = self.solde_comptable - self.encours_emission + \
            self.encours_encaissement - self.commissions - self.autres_ecarts
        super().save(*args, **kwargs)


# ============================================================
# 7. TRÉSORERIE JOURNALIÈRE (COMPLET AVEC MÉTHODES DÉTAILLÉES)
# ============================================================

class TresorerieJournaliere(models.Model):
    """Suivi journalier de la trésorerie"""
    date = models.DateField(unique=True, verbose_name="Date")
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='tresorerie_journaliere',
        verbose_name="Entrepôt/Magasin"
    )
    solde_ouverture = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde d'ouverture"
    )
    solde_fermeture = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde de fermeture"
    )
    total_entrees = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Total entrées"
    )
    total_sorties = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Total sorties"
    )
    entrees_ventes = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Entrées ventes"
    )
    entrees_reglements = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Entrées règlements"
    )
    entrees_autres = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Entrées autres"
    )
    sorties_achats = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Sorties achats"
    )
    sorties_frais = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Sorties frais"
    )
    sorties_salaires = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Sorties salaires"
    )
    sorties_autres = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Sorties autres"
    )
    nb_operations = models.IntegerField(
        default=0, verbose_name="Nombre d'opérations"
    )
    nb_entrees = models.IntegerField(
        default=0, verbose_name="Nombre d'entrées"
    )
    nb_sorties = models.IntegerField(
        default=0, verbose_name="Nombre de sorties"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Trésorerie journalière"
        verbose_name_plural = "Trésoreries journalières"
        ordering = ['-date']
        unique_together = ['date', 'warehouse']

    def __str__(self):
        return f"{self.date} - {self.warehouse.name}"

    @property
    def variation(self):
        return self.solde_fermeture - self.solde_ouverture

    # =========================================================
    # MÉTHODES DÉTAILLÉES POUR LE DÉTAIL / PDF
    # =========================================================

    def get_mouvements_du_jour(self):
        """Retourne tous les mouvements effectués du jour pour cet entrepôt"""
        return MouvementTresorerie.objects.filter(
            warehouse=self.warehouse,
            date_mouvement__date=self.date,
            status='effectue'
        ).select_related('caisse', 'compte_bancaire', 'created_by').order_by('date_mouvement')

    def get_frais_du_jour(self):
        """Retourne les détails complets des frais du jour"""
        frais_list = []
        mouvements = self.get_mouvements_du_jour().filter(
            type_mouvement='decaissement',
            source_type='frais'
        )
        for mvt in mouvements:
            frais_data = {
                'mouvement_reference': mvt.reference,
                'source_reference': mvt.source_reference or '-',
                'libelle': mvt.libelle,
                'montant': mvt.montant,
                'mode_paiement': mvt.get_mode_paiement_display(),
                'date_mouvement': mvt.date_mouvement,
                'caisse': mvt.caisse.nom if mvt.caisse else '-',
                'compte_bancaire': mvt.compte_bancaire.nom if mvt.compte_bancaire else '-',
                'created_by': mvt.created_by.full_name if mvt.created_by else '-',
                'titre': None,
                'categorie': None,
                'beneficiaire': None,
                'piece_justificative': None,
            }
            # Enrichir avec les infos du Frais source
            if mvt.source_id:
                try:
                    frais = Frais.objects.get(id=mvt.source_id)
                    frais_data.update({
                        'titre': frais.titre,
                        'categorie': frais.get_categorie_display(),
                        'beneficiaire': frais.beneficiaire,
                        'piece_justificative': frais.piece_justificative,
                    })
                except Frais.DoesNotExist:
                    pass
            frais_list.append(frais_data)
        return frais_list

    def get_entrees_du_jour(self):
        """Retourne le détail des entrées du jour"""
        entrees_list = []
        mouvements = self.get_mouvements_du_jour().filter(
            type_mouvement='encaissement'
        )
        for mvt in mouvements:
            entrees_list.append({
                'mouvement_reference': mvt.reference,
                'source_reference': mvt.source_reference or '-',
                'source_type': mvt.get_source_type_display(),
                'libelle': mvt.libelle,
                'montant': mvt.montant,
                'mode_paiement': mvt.get_mode_paiement_display(),
                'date_mouvement': mvt.date_mouvement,
                'caisse': mvt.caisse.nom if mvt.caisse else '-',
                'compte_bancaire': mvt.compte_bancaire.nom if mvt.compte_bancaire else '-',
            })
        return entrees_list

    def get_sorties_du_jour(self):
        """Retourne le détail des sorties du jour (hors frais déjà listés séparément)"""
        sorties_list = []
        mouvements = self.get_mouvements_du_jour().filter(
            type_mouvement='decaissement'
        ).exclude(source_type='frais')
        for mvt in mouvements:
            sorties_list.append({
                'mouvement_reference': mvt.reference,
                'source_reference': mvt.source_reference or '-',
                'source_type': mvt.get_source_type_display(),
                'libelle': mvt.libelle,
                'montant': mvt.montant,
                'mode_paiement': mvt.get_mode_paiement_display(),
                'date_mouvement': mvt.date_mouvement,
                'caisse': mvt.caisse.nom if mvt.caisse else '-',
                'compte_bancaire': mvt.compte_bancaire.nom if mvt.compte_bancaire else '-',
            })
        return sorties_list

    # =========================================================
    # GÉNÉRATION JOURNALIÈRE
    # =========================================================

    def generer_journaliere(self, date_jour):
        """
        Génère ou met à jour la trésorerie journalière pour une date donnée
        """
        from django.db.models import Sum, Q
        from decimal import Decimal
        from datetime import timedelta

        warehouse = self.warehouse

        # Récupérer le solde d'ouverture (jour précédent)
        jour_precedent = date_jour - timedelta(days=1)
        precedent = TresorerieJournaliere.objects.filter(
            date=jour_precedent,
            warehouse=warehouse
        ).first()

        solde_ouverture = precedent.solde_fermeture if precedent else Decimal(
            '0')

        # Récupérer les mouvements du jour
        mouvements = MouvementTresorerie.objects.filter(
            warehouse=warehouse,
            date_mouvement__date=date_jour,
            status='effectue'
        )

        # Total des entrées
        total_entrees = mouvements.filter(
            type_mouvement='encaissement'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        # Total des sorties
        total_sorties = mouvements.filter(
            type_mouvement='decaissement'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        # Détail des entrées par source
        entrees_ventes = mouvements.filter(
            type_mouvement='encaissement',
            source_type='vente'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        entrees_reglements = mouvements.filter(
            type_mouvement='encaissement',
            source_type='paiement_client'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        entrees_autres = mouvements.filter(
            type_mouvement='encaissement'
        ).exclude(
            source_type__in=['vente', 'paiement_client']
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        # Détail des sorties par source
        sorties_achats = mouvements.filter(
            type_mouvement='decaissement',
            source_type='achat'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        sorties_frais = mouvements.filter(
            type_mouvement='decaissement',
            source_type='frais'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        sorties_salaires = mouvements.filter(
            type_mouvement='decaissement',
            source_type='salaires'
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        sorties_autres = mouvements.filter(
            type_mouvement='decaissement'
        ).exclude(
            source_type__in=['achat', 'frais', 'salaires']
        ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

        # Nombre d'opérations
        nb_entrees = mouvements.filter(type_mouvement='encaissement').count()
        nb_sorties = mouvements.filter(type_mouvement='decaissement').count()
        nb_operations = mouvements.count()

        # Mettre à jour l'objet
        self.solde_ouverture = solde_ouverture
        self.total_entrees = total_entrees
        self.total_sorties = total_sorties
        self.entrees_ventes = entrees_ventes
        self.entrees_reglements = entrees_reglements
        self.entrees_autres = entrees_autres
        self.sorties_achats = sorties_achats
        self.sorties_frais = sorties_frais
        self.sorties_salaires = sorties_salaires
        self.sorties_autres = sorties_autres
        self.nb_operations = nb_operations
        self.nb_entrees = nb_entrees
        self.nb_sorties = nb_sorties
        self.solde_fermeture = solde_ouverture + total_entrees - total_sorties

        self.save()

        return self
