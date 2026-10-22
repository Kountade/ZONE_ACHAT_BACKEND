# apps/finances/models.py
# ============================================================
# MODELS COMPLET OPTIMISÉ - INDEX AVEC PRÉFIXE fin_
# ============================================================

from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator

from users.models import CustomUser
from produits_stocks.models import Product, Warehouse, Lot

# ⚠️ AUCUN IMPORT DE achats_fournisseurs OU ventes_clients OU tresorerie ICI


# ============================================================
# COMPTE COMPTABLE
# ============================================================

class CompteComptable(models.Model):
    """Plan comptable - Gestion des comptes"""
    TYPE_CHOICES = (
        ('actif', 'Actif'),
        ('passif', 'Passif'),
        ('capitaux', 'Capitaux propres'),
        ('produits', 'Produits'),
        ('charges', 'Charges'),
    )

    CLASSE_CHOICES = (
        ('1', 'Classe 1 - Capital'),
        ('2', 'Classe 2 - Immobilisations'),
        ('3', 'Classe 3 - Stocks'),
        ('4', 'Classe 4 - Tiers'),
        ('5', 'Classe 5 - Trésorerie'),
        ('6', 'Classe 6 - Charges'),
        ('7', 'Classe 7 - Produits'),
        ('8', 'Classe 8 - Comptes de régularisation'),
    )

    numero = models.CharField(
        max_length=20, unique=True, verbose_name="Numéro de compte")
    nom = models.CharField(max_length=200, verbose_name="Nom du compte")
    nom_complet = models.CharField(
        max_length=255, blank=True, verbose_name="Nom complet")
    type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, verbose_name="Type")
    classe = models.CharField(
        max_length=20, choices=CLASSE_CHOICES, verbose_name="Classe")
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        verbose_name="Compte parent"
    )
    niveau = models.PositiveIntegerField(
        default=0, verbose_name="Niveau hiérarchique")
    solde = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde actuel"
    )
    solde_initial = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde initial"
    )
    is_analytique = models.BooleanField(
        default=False, verbose_name="Compte analytique")
    is_budgetaire = models.BooleanField(
        default=False, verbose_name="Compte budgétaire")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_imported = models.BooleanField(default=False, verbose_name="Importé")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Compte comptable"
        verbose_name_plural = "Comptes comptables"
        ordering = ['numero']
        indexes = [
            models.Index(fields=['numero'], name='fin_compte_numero_idx'),
            models.Index(fields=['type'], name='fin_compte_type_idx'),
            models.Index(fields=['classe'], name='fin_compte_classe_idx'),
            models.Index(fields=['is_active'], name='fin_compte_active_idx'),
            models.Index(fields=['parent'], name='fin_compte_parent_idx'),
            models.Index(fields=['type', 'is_active'],
                         name='fin_compte_type_active_idx'),
        ]

    def __str__(self):
        return f"{self.numero} - {self.nom}"

    def get_full_path(self):
        if self.parent:
            return f"{self.parent.get_full_path()} > {self.nom}"
        return self.nom

    def update_solde(self):
        """Met à jour le solde à partir des écritures."""
        from django.db.models import Sum
        debit_total = self.ecritures_debit.aggregate(
            total=Sum('montant')
        )['total'] or Decimal('0')
        credit_total = self.ecritures_credit.aggregate(
            total=Sum('montant')
        )['total'] or Decimal('0')
        self.solde = debit_total - credit_total
        self.save(update_fields=['solde', 'updated_at'])


# ============================================================
# ÉCRITURE COMPTABLE
# ============================================================

class EcritureComptable(models.Model):
    """Écriture comptable"""
    TYPE_CHOICES = (
        ('vente', 'Vente'),
        ('achat', 'Achat'),
        ('paiement_client', 'Paiement client'),
        ('paiement_fournisseur', 'Paiement fournisseur'),
        ('recette', 'Recette'),
        ('depense', 'Dépense'),
        ('tresorerie', 'Trésorerie'),
        ('regularisation', 'Régularisation'),
        ('autre', 'Autre'),
    )

    STATUT_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('valide', 'Validée'),
        ('annulee', 'Annulée'),
    )

    numero = models.CharField(
        max_length=50, unique=True, verbose_name="N° d'écriture")
    date_ecriture = models.DateField(verbose_name="Date d'écriture")
    date_comptable = models.DateField(
        auto_now_add=True, verbose_name="Date comptable")
    date_echeance = models.DateField(
        null=True, blank=True, verbose_name="Date d'échéance")

    compte_debit = models.ForeignKey(
        CompteComptable,
        on_delete=models.CASCADE,
        related_name='ecritures_debit',
        verbose_name="Compte débit"
    )
    compte_credit = models.ForeignKey(
        CompteComptable,
        on_delete=models.CASCADE,
        related_name='ecritures_credit',
        verbose_name="Compte crédit"
    )

    montant = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant")
    taxe = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Taxe")
    total = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Total TTC")

    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Référence")
    type = models.CharField(
        max_length=30, choices=TYPE_CHOICES, verbose_name="Type")
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES,
        default='brouillon', verbose_name="Statut"
    )

    # ⚠️ IntegerField pour éviter les imports circulaires
    vente_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Vente")
    facture_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Facture client")
    paiement_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Paiement client")
    supplier_invoice_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Facture fournisseur")
    purchase_order_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Bon de commande")
    supplier_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Fournisseur")
    client_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Client")

    description = models.TextField(verbose_name="Description")
    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ecritures_created'
    )
    validated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ecritures_validated'
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Écriture comptable"
        verbose_name_plural = "Écritures comptables"
        ordering = ['-date_ecriture']
        indexes = [
            models.Index(fields=['-date_ecriture'], name='fin_ecr_date_idx'),
            models.Index(fields=['numero'], name='fin_ecr_numero_idx'),
            models.Index(fields=['type'], name='fin_ecr_type_idx'),
            models.Index(fields=['statut'], name='fin_ecr_statut_idx'),
            models.Index(
                fields=['compte_debit', '-date_ecriture'],
                name='fin_ecr_debit_date_idx'
            ),
            models.Index(
                fields=['compte_credit', '-date_ecriture'],
                name='fin_ecr_credit_date_idx'
            ),
            models.Index(fields=['supplier_invoice_id'],
                         name='fin_ecr_supplier_inv_idx'),
            models.Index(fields=['vente_id'], name='fin_ecr_vente_idx'),
            models.Index(fields=['facture_id'], name='fin_ecr_facture_idx'),
            models.Index(fields=['paiement_id'], name='fin_ecr_paiement_idx'),
            models.Index(fields=['purchase_order_id'], name='fin_ecr_po_idx'),
            models.Index(fields=['statut', 'type'],
                         name='fin_ecr_statut_type_idx'),
        ]

    def __str__(self):
        return f"{self.numero} - {self.montant} FCFA"

    def save(self, *args, **kwargs):
        self.total = self.montant + self.taxe
        super().save(*args, **kwargs)
        # Mise à jour des soldes des comptes
        self.compte_debit.update_solde()
        self.compte_credit.update_solde()

    def valider(self, user):
        self.statut = 'valide'
        self.validated_by = user
        self.validated_at = timezone.now()
        self.save()

    # ---------- Méthodes pour récupérer les objets liés ----------

    def get_vente(self):
        if self.vente_id:
            try:
                from ventes_clients.models import Vente
                return Vente.objects.get(id=self.vente_id)
            except Exception:
                return None
        return None

    def get_facture(self):
        if self.facture_id:
            try:
                from ventes_clients.models import Facture
                return Facture.objects.get(id=self.facture_id)
            except Exception:
                return None
        return None

    def get_paiement(self):
        if self.paiement_id:
            try:
                from ventes_clients.models import Paiement
                return Paiement.objects.get(id=self.paiement_id)
            except Exception:
                return None
        return None

    def get_supplier_invoice(self):
        if self.supplier_invoice_id:
            try:
                from achats_fournisseurs.models import SupplierInvoice
                return SupplierInvoice.objects.get(id=self.supplier_invoice_id)
            except Exception:
                return None
        return None

    def get_purchase_order(self):
        if self.purchase_order_id:
            try:
                from achats_fournisseurs.models import PurchaseOrder
                return PurchaseOrder.objects.get(id=self.purchase_order_id)
            except Exception:
                return None
        return None

    def get_supplier(self):
        if self.supplier_id:
            try:
                from achats_fournisseurs.models import Supplier
                return Supplier.objects.get(id=self.supplier_id)
            except Exception:
                return None
        return None

    def get_client(self):
        if self.client_id:
            try:
                from ventes_clients.models import Client
                return Client.objects.get(id=self.client_id)
            except Exception:
                return None
        return None


# ============================================================
# DÉPENSE
# ============================================================

class Depense(models.Model):
    """Gestion des dépenses"""
    CATEGORIE_CHOICES = (
        ('fournitures', 'Fournitures de bureau'),
        ('utilities', 'Services publics'),
        ('loyer', 'Loyer'),
        ('salaires', 'Salaires'),
        ('marketing', 'Marketing et publicité'),
        ('transport', 'Transport et déplacements'),
        ('maintenance', 'Maintenance et réparation'),
        ('formation', 'Formation'),
        ('informatique', 'Informatique'),
        ('telecommunication', 'Télécommunication'),
        ('frais_bancaires', 'Frais bancaires'),
        ('impots', 'Impôts et taxes'),
        ('assurance', 'Assurance'),
        ('frais_professionnels', 'Frais professionnels'),
        ('achat_stock', 'Achat de stock'),
        ('autre', 'Autre'),
    )

    STATUS_CHOICES = (
        ('en_attente', 'En attente'),
        ('approuve', 'Approuvé'),
        ('paye', 'Payé'),
        ('annule', 'Annulé'),
        ('rejete', 'Rejeté'),
    )

    # ✅ MAPPING CATÉGORIE → COMPTE COMPTABLE
    CATEGORIE_COMPTE_MAPPING = {
        'fournitures': ('606', 'Achats non stockés de matières et fournitures'),
        'utilities': ('606', 'Achats non stockés - Services publics'),
        'loyer': ('613', 'Locations'),
        'salaires': ('641', 'Rémunérations du personnel'),
        'marketing': ('623', 'Publicité, publications, relations publiques'),
        'transport': ('625', 'Déplacements, missions et réceptions'),
        'maintenance': ('615', 'Entretien et réparations'),
        'formation': ('628', 'Frais de formation'),
        'informatique': ('615', 'Entretien et réparations - Informatique'),
        'telecommunication': ('628', 'Frais de télécommunications'),
        'frais_bancaires': ('627', 'Services bancaires et assimilés'),
        'impots': ('631', 'Impôts, taxes et versements assimilés'),
        'assurance': ('616', 'Primes d\'assurance'),
        'frais_professionnels': ('628', 'Frais professionnels'),
        'achat_stock': ('601', 'Achats de marchandises'),
        'autre': ('658', 'Charges diverses'),
    }

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")
    categorie = models.CharField(
        max_length=30, choices=CATEGORIE_CHOICES, verbose_name="Catégorie")
    description = models.TextField(verbose_name="Description")
    montant = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant")
    taxe = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="TVA")
    total = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Total TTC")
    date_depense = models.DateField(verbose_name="Date de la dépense")
    date_echeance = models.DateField(
        null=True, blank=True, verbose_name="Date d'échéance")
    mode_paiement = models.CharField(
        max_length=50, blank=True, verbose_name="Mode de paiement")
    reference_paiement = models.CharField(
        max_length=100, blank=True, verbose_name="Référence paiement")
    date_paiement = models.DateField(
        null=True, blank=True, verbose_name="Date de paiement")

    supplier_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Fournisseur")
    supplier_name = models.CharField(
        max_length=200, blank=True, verbose_name="Nom du fournisseur")

    statut = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='en_attente', verbose_name="Statut"
    )
    piece_jointe = models.FileField(
        upload_to='depenses/', null=True, blank=True,
        verbose_name="Pièce jointe"
    )

    tresorerie_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Trésorerie")
    ecriture_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Écriture comptable")
    purchase_order_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Bon de commande")

    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    approuve_par = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='depenses_approuvees'
    )
    approuve_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Dépense"
        verbose_name_plural = "Dépenses"
        ordering = ['-date_depense']
        indexes = [
            models.Index(fields=['-date_depense'], name='fin_dep_date_idx'),
            models.Index(fields=['reference'], name='fin_dep_reference_idx'),
            models.Index(fields=['categorie'], name='fin_dep_categorie_idx'),
            models.Index(fields=['statut'], name='fin_dep_statut_idx'),
            models.Index(
                fields=['date_depense', 'statut'],
                name='fin_dep_date_statut_idx'
            ),
            models.Index(fields=['supplier_id'], name='fin_dep_supplier_idx'),
            models.Index(fields=['ecriture_id'], name='fin_dep_ecriture_idx'),
            models.Index(fields=['tresorerie_id'],
                         name='fin_dep_tresorerie_idx'),
            models.Index(
                fields=['date_depense', 'categorie'],
                name='fin_dep_date_cat_idx'
            ),
        ]

    def __str__(self):
        return f"{self.reference} - {self.montant} FCFA"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"DEP{datetime.now().strftime('%Y%m')}"
            last = Depense.objects.filter(
                reference__startswith=prefix
            ).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        self.total = self.montant + self.taxe
        super().save(*args, **kwargs)

    def approuver(self, user):
        self.statut = 'approuve'
        self.approuve_par = user
        self.approuve_le = timezone.now()
        self.save(update_fields=[
            'statut', 'approuve_par', 'approuve_le', 'updated_at'
        ])

    def payer(self, user):
        """
        ✅ Marque la dépense comme payée et déclenche automatiquement :
        - La création d'un MouvementTresorerie (décaissement)
        - La création d'une EcritureComptable
        """
        from django.core.exceptions import ValidationError

        if self.statut not in ['approuve', 'en_attente']:
            raise ValidationError(
                f"Impossible de payer une dépense au statut '{self.get_statut_display()}'"
            )

        self.statut = 'paye'
        self.date_paiement = timezone.now().date()
        self.save(update_fields=['statut', 'date_paiement', 'updated_at'])

        # ✅ Créer mouvement + écriture (import différé)
        result = self.creer_mouvement_et_ecriture(user)
        return result

    def creer_mouvement_et_ecriture(self, user):
        """
        Crée le mouvement de trésorerie ET l'écriture comptable associée.
        Idempotent : ne crée pas de doublons.
        """
        result = {'mouvement_id': None, 'ecriture_id': None, 'errors': []}

        # ============================================================
        # 1. MOUVEMENT DE TRÉSORERIE (décaissement)
        # ============================================================
        if not self.tresorerie_id:
            try:
                from tresorerie.models import MouvementTresorerie, Caisse

                caisse = Caisse.objects.filter(
                    is_default=True, is_active=True
                ).first()

                if not caisse:
                    caisse = Caisse.objects.filter(is_active=True).first()

                if not caisse:
                    from django.core.exceptions import ValidationError
                    raise ValidationError(
                        "Aucune caisse active disponible pour enregistrer la dépense."
                    )

                mouvement = MouvementTresorerie.objects.create(
                    type_mouvement='decaissement',
                    source_type='depense',
                    source_id=self.id,
                    source_reference=self.reference,
                    montant=self.total,
                    mode_paiement=self.mode_paiement or 'especes',
                    caisse=caisse,
                    compte_bancaire=None,
                    date_mouvement=timezone.now(),
                    date_valeur=self.date_paiement or timezone.now().date(),
                    status='effectue',
                    libelle=f"Dépense {self.reference} - {self.description[:100]}",
                    notes=self.notes or '',
                    created_by=user
                )

                self.tresorerie_id = mouvement.id
                self.save(update_fields=['tresorerie_id', 'updated_at'])

                # Mise à jour du solde de la caisse
                caisse.solde_actuel -= self.total
                caisse.save(update_fields=['solde_actuel', 'updated_at'])

                result['mouvement_id'] = mouvement.id

            except ImportError as e:
                result['errors'].append(
                    f"Module trésorerie indisponible : {e}")
            except Exception as e:
                result['errors'].append(f"Erreur mouvement trésorerie : {e}")

        else:
            result['mouvement_id'] = self.tresorerie_id

        # ============================================================
        # 2. ÉCRITURE COMPTABLE
        # ============================================================
        if not self.ecriture_id:
            try:
                # Compte de charge selon la catégorie
                numero_charge, nom_charge = self.CATEGORIE_COMPTE_MAPPING.get(
                    self.categorie,
                    ('658', 'Charges diverses')
                )

                compte_charge, _ = CompteComptable.objects.get_or_create(
                    numero=numero_charge,
                    defaults={
                        'nom': nom_charge,
                        'type': 'charges',
                        'classe': '6'
                    }
                )

                # Compte de trésorerie (source du décaissement)
                numero_tresorerie = '531'  # Caisse par défaut
                nom_tresorerie = 'Caisse'

                if result['mouvement_id']:
                    try:
                        from tresorerie.models import MouvementTresorerie
                        mvt = MouvementTresorerie.objects.get(
                            id=result['mouvement_id'])
                        if mvt.compte_bancaire:
                            numero_tresorerie = '521'
                            nom_tresorerie = 'Banque'
                    except Exception:
                        pass

                compte_tresorerie, _ = CompteComptable.objects.get_or_create(
                    numero=numero_tresorerie,
                    defaults={
                        'nom': nom_tresorerie,
                        'type': 'actif',
                        'classe': '5'
                    }
                )

                ecriture = EcritureComptable.objects.create(
                    numero=f"ECR-DEP-{timezone.now().strftime('%Y%m%d%H%M%S')}-{self.id}",
                    date_ecriture=self.date_paiement or timezone.now().date(),
                    compte_debit=compte_charge,
                    compte_credit=compte_tresorerie,
                    montant=self.total,
                    taxe=self.taxe,
                    total=self.total,
                    reference=self.reference,
                    type='depense',
                    statut='valide',
                    description=f"Dépense {self.reference} - {self.description[:200]}",
                    notes=f"Écriture générée automatiquement depuis la dépense {self.reference}",
                    created_by=user,
                    validated_by=user,
                    validated_at=timezone.now()
                )

                self.ecriture_id = ecriture.id
                self.save(update_fields=['ecriture_id', 'updated_at'])

                result['ecriture_id'] = ecriture.id

            except Exception as e:
                result['errors'].append(f"Erreur écriture comptable : {e}")

        else:
            result['ecriture_id'] = self.ecriture_id

        return result

    def get_supplier(self):
        if self.supplier_id:
            try:
                from achats_fournisseurs.models import Supplier
                return Supplier.objects.get(id=self.supplier_id)
            except Exception:
                return None
        return None

    def get_purchase_order(self):
        if self.purchase_order_id:
            try:
                from achats_fournisseurs.models import PurchaseOrder
                return PurchaseOrder.objects.get(id=self.purchase_order_id)
            except Exception:
                return None
        return None


# ============================================================
# BUDGET
# ============================================================

class Budget(models.Model):
    """Gestion des budgets"""
    TYPE_CHOICES = (
        ('annuel', 'Annuel'),
        ('trimestriel', 'Trimestriel'),
        ('mensuel', 'Mensuel'),
        ('projet', 'Projet'),
    )

    STATUT_CHOICES = (
        ('en_cours', 'En cours'),
        ('termine', 'Terminé'),
        ('annule', 'Annulé'),
    )

    nom = models.CharField(max_length=100, verbose_name="Nom")
    type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, verbose_name="Type")
    montant_total = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant total")
    montant_utilise = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Montant utilisé"
    )
    montant_restant = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Montant restant"
    )
    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES,
        default='en_cours', verbose_name="Statut"
    )
    categories = models.ManyToManyField(
        'BudgetCategorie', through='BudgetLigne',
        verbose_name="Catégories"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Budget"
        verbose_name_plural = "Budgets"
        ordering = ['-date_debut']
        indexes = [
            models.Index(fields=['-date_debut'], name='fin_bud_date_idx'),
            models.Index(fields=['statut'], name='fin_bud_statut_idx'),
            models.Index(fields=['type'], name='fin_bud_type_idx'),
            models.Index(
                fields=['date_debut', 'date_fin'],
                name='fin_bud_dates_idx'
            ),
            models.Index(
                fields=['statut', 'date_debut', 'date_fin'],
                name='fin_bud_statut_dates_idx'
            ),
        ]

    def __str__(self):
        return f"{self.nom} - {self.montant_total} FCFA"

    def update_utilise(self):
        total_utilise = self.lignes.aggregate(
            total=models.Sum('montant_utilise')
        )['total'] or Decimal('0')
        self.montant_utilise = total_utilise
        self.montant_restant = self.montant_total - self.montant_utilise
        self.save(update_fields=[
            'montant_utilise', 'montant_restant', 'updated_at'
        ])


class BudgetCategorie(models.Model):
    """Catégorie de budget"""

    DEPENSE_CATEGORIE_CHOICES = (
        ('fournitures', 'Fournitures de bureau'),
        ('utilities', 'Services publics'),
        ('loyer', 'Loyer'),
        ('salaires', 'Salaires'),
        ('marketing', 'Marketing et publicité'),
        ('transport', 'Transport et déplacements'),
        ('maintenance', 'Maintenance et réparation'),
        ('formation', 'Formation'),
        ('informatique', 'Informatique'),
        ('telecommunication', 'Télécommunication'),
        ('frais_bancaires', 'Frais bancaires'),
        ('impots', 'Impôts et taxes'),
        ('assurance', 'Assurance'),
        ('frais_professionnels', 'Frais professionnels'),
        ('achat_stock', 'Achat de stock'),
        ('autre', 'Autre'),
    )

    nom = models.CharField(max_length=100, verbose_name="Nom")
    description = models.TextField(blank=True, verbose_name="Description")
    code = models.CharField(
        max_length=20, unique=True, verbose_name="Code")
    categorie_depense = models.CharField(
        max_length=30,
        choices=DEPENSE_CATEGORIE_CHOICES,
        null=True,
        blank=True,
        unique=True,
        verbose_name="Catégorie de dépense associée",
        help_text="Permet de lier cette catégorie de budget aux dépenses correspondantes"
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")

    class Meta:
        verbose_name = "Catégorie de budget"
        verbose_name_plural = "Catégories de budget"
        ordering = ['nom']
        indexes = [
            models.Index(fields=['code'], name='fin_budcat_code_idx'),
            models.Index(fields=['nom'], name='fin_budcat_nom_idx'),
            models.Index(fields=['is_active'], name='fin_budcat_active_idx'),
            models.Index(
                fields=['categorie_depense'],
                name='fin_budcat_dep_cat_idx'
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.nom}"


class BudgetLigne(models.Model):
    """Ligne de budget"""
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name='lignes')
    categorie = models.ForeignKey(BudgetCategorie, on_delete=models.CASCADE)
    montant_prevu = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant prévu")
    montant_utilise = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Montant utilisé"
    )
    montant_restant = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Montant restant"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Ligne de budget"
        verbose_name_plural = "Lignes de budget"
        indexes = [
            models.Index(fields=['budget'], name='fin_budl_budget_idx'),
            models.Index(fields=['categorie'], name='fin_budl_categorie_idx'),
            models.Index(
                fields=['budget', 'categorie'],
                name='fin_budl_budget_cat_idx'
            ),
        ]

    def __str__(self):
        return f"{self.budget.nom} - {self.categorie.nom}"

    @property
    def pourcentage_utilise(self):
        """Pourcentage d'utilisation de cette ligne"""
        if self.montant_prevu > 0:
            return (self.montant_utilise / self.montant_prevu) * 100
        return 0

    def save(self, *args, **kwargs):
        self.montant_restant = self.montant_prevu - self.montant_utilise
        super().save(*args, **kwargs)
        # Met à jour le total du budget parent
        self.budget.update_utilise()


# ============================================================
# RAPPORT FINANCIER
# ============================================================

class RapportFinancier(models.Model):
    """Rapports financiers"""
    TYPE_CHOICES = (
        ('bilan', 'Bilan comptable'),
        ('compte_resultat', 'Compte de résultat'),
        ('tresorerie', 'Tableau de trésorerie'),
        ('budget', 'Suivi budgétaire'),
        ('ventes', 'Rapport de ventes'),
        ('depenses', 'Rapport de dépenses'),
        ('achats', 'Rapport d\'achats'),
        ('client', 'Rapport client'),
        ('fournisseur', 'Rapport fournisseur'),
    )

    FORMAT_CHOICES = (
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('csv', 'CSV'),
    )

    type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, verbose_name="Type")
    nom = models.CharField(max_length=200, verbose_name="Nom du rapport")
    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")
    format = models.CharField(
        max_length=10, choices=FORMAT_CHOICES,
        default='pdf', verbose_name="Format"
    )
    contenu = models.JSONField(
        default=dict, blank=True, verbose_name="Contenu")
    fichier = models.FileField(
        upload_to='rapports/', null=True, blank=True,
        verbose_name="Fichier"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Rapport financier"
        verbose_name_plural = "Rapports financiers"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at'], name='fin_rap_created_idx'),
            models.Index(fields=['type'], name='fin_rap_type_idx'),
            models.Index(
                fields=['date_debut', 'date_fin'],
                name='fin_rap_dates_idx'
            ),
        ]

    def __str__(self):
        return f"{self.nom} - {self.type}"


# ============================================================
# CONFIGURATION FINANCIÈRE
# ============================================================

class ConfigurationFinanciere(models.Model):
    """Configuration financière de l'entreprise"""
    devise = models.CharField(
        max_length=3, default='XOF', verbose_name="Devise")
    devise_symbole = models.CharField(
        max_length=5, default='CFA', verbose_name="Symbole devise")
    exercice_debut = models.DateField(verbose_name="Début de l'exercice")
    exercice_fin = models.DateField(verbose_name="Fin de l'exercice")
    taxe_default = models.DecimalField(
        max_digits=5, decimal_places=2, default=18,
        verbose_name="TVA par défaut (%)"
    )
    arrondi = models.PositiveIntegerField(
        default=0, verbose_name="Nombre de décimales")
    auto_validation = models.BooleanField(
        default=False, verbose_name="Validation automatique des écritures")
    budget_alerte = models.PositiveIntegerField(
        default=80, verbose_name="Alerte budget (%)")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Configuration financière"
        verbose_name_plural = "Configurations financières"
        indexes = [
            models.Index(
                fields=['exercice_debut', 'exercice_fin'],
                name='fin_config_exercice_idx'
            ),
        ]

    def __str__(self):
        return f"Configuration financière - {self.devise}"
