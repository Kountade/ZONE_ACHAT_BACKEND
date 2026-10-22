# apps/tresorerie/models.py
from django.db import models
from django.db.models import Sum, Count, Q, Value, DecimalField
from django.db.models.functions import Coalesce
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from users.models import CustomUser
from produits_stocks.models import Warehouse

# AUCUN IMPORT DE achats_fournisseurs OU finances ICI


# ============================================================
# CONSTANTES
# ============================================================

TYPE_MOUVEMENT = (
    ('encaissement', 'Encaissement'),
    ('decaissement', 'Decaissement'),
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
    ('especes', 'Especes'),
    ('carte', 'Carte bancaire'),
    ('cheque', 'Cheque'),
    ('virement', 'Virement'),
    ('mobile_money', 'Mobile Money'),
    ('prelevement', 'Prelevement'),
    ('autre', 'Autre'),
)

STATUS_CHOICES = (
    ('planifie', 'Planifie'),
    ('en_attente', 'En attente'),
    ('effectue', 'Effectue'),
    ('annule', 'Annule'),
    ('rejete', 'Rejete'),
)


# ============================================================
# 1. CAISSES
# ============================================================

class Caisse(models.Model):
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
        max_length=20, choices=TYPE_CAISSE, default='principale',
        verbose_name="Type de caisse")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        related_name='caisses', verbose_name="Entrepot/Magasin")
    responsable = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='caisses_gerrees',
        verbose_name="Responsable")
    solde_initial = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde initial")
    solde_actuel = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde actuel")
    seuil_min = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Seuil minimum")
    seuil_max = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Seuil maximum")
    devise = models.CharField(
        max_length=3, default='XOF', verbose_name="Devise")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    is_default = models.BooleanField(
        default=False, verbose_name="Caisse par defaut")
    description = models.TextField(
        blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='caisses_crees', verbose_name="Cree par")

    class Meta:
        verbose_name = "Caisse"
        verbose_name_plural = "Caisses"
        ordering = ['code']
        unique_together = ['warehouse', 'code']
        indexes = [
            models.Index(fields=['warehouse', 'is_active'],
                         name='caisse_wh_active_idx'),
            models.Index(fields=['warehouse', 'is_default'],
                         name='caisse_wh_default_idx'),
            models.Index(fields=['code'], name='caisse_code_idx'),
            models.Index(fields=['is_active'], name='caisse_active_idx'),
            models.Index(fields=['type_caisse'], name='caisse_type_idx'),
            models.Index(fields=['-created_at'], name='caisse_created_idx'),
        ]

    def __str__(self):
        return f"{self.code} - {self.nom} ({self.warehouse.name})"

    def save(self, *args, **kwargs):
        if self.is_default:
            Caisse.objects.filter(
                warehouse=self.warehouse, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def est_sous_seuil_min(self):
        return self.solde_actuel < self.seuil_min

    @property
    def est_sur_seuil_max(self):
        return self.seuil_max > 0 and self.solde_actuel > self.seuil_max

    def mettre_a_jour_solde(self):
        """
        CORRECTION N+1 : 1 seule requete au lieu de 2.
        """
        totals = MouvementTresorerie.objects.filter(
            caisse=self, status='effectue'
        ).aggregate(
            entrees=Coalesce(
                Sum('montant', filter=Q(type_mouvement='encaissement')),
                Value(0, output_field=DecimalField(
                    max_digits=15, decimal_places=2))
            ),
            sorties=Coalesce(
                Sum('montant', filter=Q(type_mouvement='decaissement')),
                Value(0, output_field=DecimalField(
                    max_digits=15, decimal_places=2))
            ),
        )

        self.solde_actuel = (
            self.solde_initial + totals['entrees'] - totals['sorties']
        )
        self.save(update_fields=['solde_actuel', 'updated_at'])


# ============================================================
# 2. COMPTES BANCAIRES
# ============================================================

class CompteBancaire(models.Model):
    TYPE_COMPTE = (
        ('courant', 'Compte courant'),
        ('epargne', 'Compte epargne'),
        ('bloque', 'Compte bloque'),
    )

    banque = models.CharField(max_length=100, verbose_name="Banque")
    code = models.CharField(max_length=20, unique=True,
                            verbose_name="Code compte")
    nom = models.CharField(max_length=100, verbose_name="Nom du compte")
    type_compte = models.CharField(
        max_length=20, choices=TYPE_COMPTE, default='courant',
        verbose_name="Type de compte")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        related_name='comptes_bancaires', verbose_name="Entrepot/Magasin")
    numero_compte = models.CharField(
        max_length=50, verbose_name="Numero de compte")
    iban = models.CharField(max_length=34, blank=True,
                            null=True, verbose_name="IBAN")
    bic = models.CharField(max_length=11, blank=True,
                           null=True, verbose_name="BIC/SWIFT")
    devise = models.CharField(
        max_length=3, default='XOF', verbose_name="Devise")
    solde_initial = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde initial")
    solde_actuel = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde actuel")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_default = models.BooleanField(
        default=False, verbose_name="Compte par defaut")
    date_ouverture = models.DateField(
        default=timezone.now, verbose_name="Date d'ouverture")
    description = models.TextField(
        blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='comptes_bancaires_crees', verbose_name="Cree par")

    class Meta:
        verbose_name = "Compte bancaire"
        verbose_name_plural = "Comptes bancaires"
        ordering = ['banque', 'code']
        unique_together = ['warehouse', 'code', 'numero_compte']
        indexes = [
            models.Index(fields=['warehouse', 'is_active'],
                         name='compte_wh_active_idx'),
            models.Index(fields=['warehouse', 'is_default'],
                         name='compte_wh_default_idx'),
            models.Index(fields=['banque'], name='compte_banque_idx'),
            models.Index(fields=['code'], name='compte_code_idx'),
            models.Index(fields=['is_active'], name='compte_active_idx'),
            models.Index(fields=['type_compte'], name='compte_type_idx'),
        ]

    def __str__(self):
        return f"{self.banque} - {self.nom} ({self.numero_compte})"

    def mettre_a_jour_solde(self):
        """
        CORRECTION N+1 : 1 seule requete au lieu de 2.
        """
        totals = MouvementTresorerie.objects.filter(
            compte_bancaire=self, status='effectue'
        ).aggregate(
            entrees=Coalesce(
                Sum('montant', filter=Q(type_mouvement='encaissement')),
                Value(0, output_field=DecimalField(
                    max_digits=15, decimal_places=2))
            ),
            sorties=Coalesce(
                Sum('montant', filter=Q(type_mouvement='decaissement')),
                Value(0, output_field=DecimalField(
                    max_digits=15, decimal_places=2))
            ),
        )

        self.solde_actuel = (
            self.solde_initial + totals['entrees'] - totals['sorties']
        )
        self.save(update_fields=['solde_actuel', 'updated_at'])


# ============================================================
# 3. MOUVEMENTS DE TRESORERIE
# ============================================================

class MouvementTresorerie(models.Model):
    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Reference")
    type_mouvement = models.CharField(
        max_length=20, choices=TYPE_MOUVEMENT,
        verbose_name="Type de mouvement")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        related_name='mouvements_tresorerie',
        verbose_name="Entrepot/Magasin", null=True, blank=True)
    source_type = models.CharField(
        max_length=20, choices=SOURCE_TYPE, verbose_name="Type source")
    source_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID source")
    source_reference = models.CharField(
        max_length=100, blank=True, null=True,
        verbose_name="Reference source")
    montant = models.DecimalField(
        max_digits=15, decimal_places=2,
        validators=[MinValueValidator(0)], verbose_name="Montant")
    mode_paiement = models.CharField(
        max_length=20, choices=MODE_PAIEMENT,
        verbose_name="Mode de paiement")
    caisse = models.ForeignKey(
        Caisse, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='mouvements', verbose_name="Caisse")
    compte_bancaire = models.ForeignKey(
        CompteBancaire, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='mouvements',
        verbose_name="Compte bancaire")
    date_mouvement = models.DateTimeField(
        default=timezone.now, verbose_name="Date du mouvement")
    date_valeur = models.DateField(verbose_name="Date de valeur")
    date_prevue = models.DateField(
        null=True, blank=True, verbose_name="Date prevue")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='planifie', verbose_name="Statut")
    reference_externe = models.CharField(
        max_length=100, blank=True, null=True,
        verbose_name="Reference externe")
    piece_justificative = models.CharField(
        max_length=50, blank=True, null=True,
        verbose_name="Piece justificative")
    date_rapprochement = models.DateField(
        null=True, blank=True, verbose_name="Date rapprochement")
    rapproche = models.BooleanField(default=False, verbose_name="Rapproche")
    libelle = models.CharField(max_length=200, verbose_name="Libelle")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='mouvements_tresorerie_crees',
        verbose_name="Cree par")
    valide_par = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='mouvements_tresorerie_valides',
        verbose_name="Valide par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Mouvement de tresorerie"
        verbose_name_plural = "Mouvements de tresorerie"
        ordering = ['-date_mouvement']
        indexes = [
            models.Index(fields=['-date_mouvement'], name='mvt_date_idx'),
            models.Index(fields=['warehouse', '-date_mouvement'],
                         name='mvt_wh_date_idx'),
            models.Index(fields=['type_mouvement', 'status'],
                         name='mvt_type_status_idx'),
            models.Index(fields=['source_type', 'source_id'],
                         name='mvt_source_idx'),
            models.Index(fields=['status', '-date_mouvement'],
                         name='mvt_status_date_idx'),
            models.Index(fields=['caisse', '-date_mouvement'],
                         name='mvt_caisse_date_idx'),
            models.Index(fields=['compte_bancaire', '-date_mouvement'],
                         name='mvt_compte_date_idx'),
            models.Index(fields=['mode_paiement'],
                         name='mvt_mode_paiement_idx'),
            models.Index(fields=['reference'], name='mvt_reference_idx'),
            models.Index(
                fields=['warehouse', 'date_mouvement', 'status'],
                name='mvt_wh_date_status_idx'),
            models.Index(fields=['rapproche', 'compte_bancaire'],
                         name='mvt_rapproche_idx'),
        ]

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
        if self.status == 'annule':
            return False
        old_status = self.status
        self.status = 'annule'
        self.save()
        if old_status == 'effectue':
            self._mettre_a_jour_soldes()
        return True

    def _mettre_a_jour_soldes(self):
        if self.caisse:
            self.caisse.mettre_a_jour_solde()
        if self.compte_bancaire:
            self.compte_bancaire.mettre_a_jour_solde()


# ============================================================
# 4. FRAIS
# ============================================================

class Frais(models.Model):
    CATEGORIE_FRAIS = (
        ('transport', 'Transport'),
        ('restauration', 'Restauration'),
        ('fournitures', 'Fournitures de bureau'),
        ('communication', 'Communication'),
        ('entretien', 'Entretien'),
        ('formation', 'Formation'),
        ('mission', 'Mission'),
        ('representations', 'Representation'),
        ('assurances', 'Assurances'),
        ('impots', 'Impots et taxes'),
        ('loyer', 'Loyer'),
        ('services', 'Services'),
        ('fournisseur', 'Paiement fournisseur'),
        ('autre', 'Autre'),
    )

    STATUS_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_attente', 'En attente de validation'),
        ('valide', 'Valide'),
        ('paye', 'Paye'),
        ('refuse', 'Refuse'),
        ('annule', 'Annule'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Reference")
    titre = models.CharField(max_length=200, verbose_name="Titre")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        related_name='frais', verbose_name="Entrepot/Magasin")
    categorie = models.CharField(
        max_length=20, choices=CATEGORIE_FRAIS, verbose_name="Categorie")
    montant = models.DecimalField(
        max_digits=15, decimal_places=2,
        validators=[MinValueValidator(0)], verbose_name="Montant")
    date_frais = models.DateField(
        default=timezone.now, verbose_name="Date du frais")
    date_paiement = models.DateField(
        null=True, blank=True, verbose_name="Date de paiement")
    beneficiaire = models.CharField(
        max_length=200, verbose_name="Beneficiaire")
    piece_justificative = models.CharField(
        max_length=50, blank=True, null=True,
        verbose_name="Piece justificative")
    mode_paiement = models.CharField(
        max_length=20, choices=MODE_PAIEMENT,
        default='especes', verbose_name="Mode de paiement")
    mouvement_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Mouvement associe")
    supplier_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Fournisseur")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='brouillon', verbose_name="Statut")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='frais_crees', verbose_name="Cree par")
    valide_par = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='frais_valides',
        verbose_name="Valide par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Frais"
        verbose_name_plural = "Frais"
        ordering = ['-date_frais']
        indexes = [
            models.Index(fields=['-date_frais'], name='frais_date_idx'),
            models.Index(fields=['warehouse', '-date_frais'],
                         name='frais_wh_date_idx'),
            models.Index(fields=['warehouse', 'status'],
                         name='frais_wh_status_idx'),
            models.Index(fields=['status', '-date_frais'],
                         name='frais_status_date_idx'),
            models.Index(fields=['categorie', '-date_frais'],
                         name='frais_cat_date_idx'),
            models.Index(fields=['reference'], name='frais_reference_idx'),
            models.Index(fields=['supplier_id'], name='frais_supplier_idx'),
            models.Index(fields=['mouvement_id'], name='frais_mouvement_idx'),
            models.Index(fields=['mode_paiement'], name='frais_mode_idx'),
        ]

    def __str__(self):
        return f"{self.reference} - {self.titre} ({self.montant:,.0f} XOF)"

    def save(self, *args, **kwargs):
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

        super().save(*args, **kwargs)

        if self.status == 'paye' and not self.mouvement_id:
            caisse_defaut = Caisse.objects.filter(
                warehouse=self.warehouse, is_default=True).first()
            if not caisse_defaut:
                raise ValidationError(
                    f"Aucune caisse par defaut pour l'entrepot "
                    f"'{self.warehouse.name}'. Veuillez configurer une "
                    f"caisse par defaut."
                )

            mouvement = MouvementTresorerie.objects.create(
                type_mouvement='decaissement',
                warehouse=self.warehouse,
                source_type='frais',
                source_id=self.id,
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
            super().save(update_fields=['mouvement_id', 'updated_at'])

    def get_supplier(self):
        if self.supplier_id:
            try:
                from achats_fournisseurs.models import Supplier
                return Supplier.objects.get(id=self.supplier_id)
            except:
                return None
        return None

    def get_mouvement(self):
        if self.mouvement_id:
            try:
                return MouvementTresorerie.objects.get(id=self.mouvement_id)
            except MouvementTresorerie.DoesNotExist:
                return None
        return None


# ============================================================
# 5. PREVISIONS DE TRESORERIE
# ============================================================

class PrevisionTresorerie(models.Model):
    PERIODE_CHOICES = (
        ('journalier', 'Journalier'),
        ('hebdomadaire', 'Hebdomadaire'),
        ('mensuel', 'Mensuel'),
        ('trimestriel', 'Trimestriel'),
        ('annuel', 'Annuel'),
    )

    TYPE_PREVISION = (
        ('entree', 'Entree prevue'),
        ('sortie', 'Sortie prevue'),
    )

    STATUT_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_cours', 'En cours'),
        ('valide', 'Validee'),
        ('realise', 'Realise'),
        ('annule', 'Annule'),
        ('ecart', 'Ecart constate'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Reference")
    titre = models.CharField(max_length=200, verbose_name="Titre")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        related_name='previsions_tresorerie',
        verbose_name="Entrepot/Magasin")
    type_prevision = models.CharField(
        max_length=20, choices=TYPE_PREVISION,
        verbose_name="Type de prevision")
    periode = models.CharField(
        max_length=20, choices=PERIODE_CHOICES,
        default='mensuel', verbose_name="Periode")
    montant_prevu = models.DecimalField(
        max_digits=15, decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Montant prevu")
    montant_reel = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Montant reel")
    date_debut = models.DateField(verbose_name="Date debut")
    date_fin = models.DateField(verbose_name="Date fin")
    source_type = models.CharField(
        max_length=50, blank=True, null=True,
        verbose_name="Type source")
    source_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID source")
    categorie = models.CharField(
        max_length=50, blank=True, null=True,
        verbose_name="Categorie")
    sous_categorie = models.CharField(
        max_length=50, blank=True, null=True,
        verbose_name="Sous-categorie")
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES,
        default='brouillon', verbose_name="Statut")
    probabilite = models.IntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Probabilite (%)")
    ecart = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Ecart")
    pourcentage_ecart = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name="Pourcentage d'ecart")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='previsions_crees', verbose_name="Cree par")

    class Meta:
        verbose_name = "Prevision de tresorerie"
        verbose_name_plural = "Previsions de tresorerie"
        ordering = ['-date_debut']
        indexes = [
            models.Index(fields=['-date_debut'], name='prev_date_idx'),
            models.Index(fields=['warehouse', '-date_debut'],
                         name='prev_wh_date_idx'),
            models.Index(fields=['warehouse', 'statut'],
                         name='prev_wh_statut_idx'),
            models.Index(fields=['type_prevision', 'statut'],
                         name='prev_type_statut_idx'),
            models.Index(fields=['date_debut', 'date_fin'],
                         name='prev_dates_idx'),
            models.Index(fields=['reference'], name='prev_reference_idx'),
            models.Index(fields=['statut'], name='prev_statut_idx'),
        ]

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
    STATUS_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_cours', 'En cours'),
        ('partiel', 'Partiellement rapproche'),
        ('complete', 'Completement rapproche'),
        ('ecart', 'Ecart constate'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Reference")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        related_name='rapprochements', verbose_name="Entrepot/Magasin")
    compte_bancaire = models.ForeignKey(
        CompteBancaire, on_delete=models.PROTECT,
        related_name='rapprochements', verbose_name="Compte bancaire")
    date_debut = models.DateField(verbose_name="Date debut")
    date_fin = models.DateField(verbose_name="Date fin")
    solde_comptable = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde comptable")
    solde_bancaire = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde bancaire")
    solde_rapproche = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde rapproche")
    ecart = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Ecart")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='brouillon', verbose_name="Statut")
    encours_emission = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="En-cours d'emission")
    encours_encaissement = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="En-cours d'encaissement")
    commissions = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Commissions bancaires")
    autres_ecarts = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Autres ecarts")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='rapprochements_crees', verbose_name="Cree par")
    valide_par = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='rapprochements_valides',
        verbose_name="Valide par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Rapprochement bancaire"
        verbose_name_plural = "Rapprochements bancaires"
        ordering = ['-date_fin']
        unique_together = ['compte_bancaire', 'date_debut', 'date_fin']
        indexes = [
            models.Index(fields=['-date_fin'], name='rap_date_idx'),
            models.Index(fields=['compte_bancaire', '-date_fin'],
                         name='rap_compte_date_idx'),
            models.Index(fields=['warehouse', '-date_fin'],
                         name='rap_wh_date_idx'),
            models.Index(fields=['status'], name='rap_status_idx'),
            models.Index(fields=['reference'], name='rap_reference_idx'),
        ]

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
        self.solde_rapproche = (
            self.solde_comptable - self.encours_emission
            + self.encours_encaissement - self.commissions
            - self.autres_ecarts
        )
        super().save(*args, **kwargs)


# ============================================================
# 7. TRESORERIE JOURNALIERE
# ============================================================

class TresorerieJournaliere(models.Model):
    date = models.DateField(verbose_name="Date")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        related_name='tresorerie_journaliere',
        verbose_name="Entrepot/Magasin")
    solde_ouverture = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde d'ouverture")
    solde_fermeture = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Solde de fermeture")
    total_entrees = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Total entrees")
    total_sorties = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Total sorties")
    entrees_ventes = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Entrees ventes")
    entrees_reglements = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Entrees reglements")
    entrees_autres = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Entrees autres")
    sorties_achats = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Sorties achats")
    sorties_frais = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Sorties frais")
    sorties_salaires = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Sorties salaires")
    sorties_autres = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Sorties autres")
    nb_operations = models.IntegerField(
        default=0, verbose_name="Nombre d'operations")
    nb_entrees = models.IntegerField(
        default=0, verbose_name="Nombre d'entrees")
    nb_sorties = models.IntegerField(
        default=0, verbose_name="Nombre de sorties")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tresorerie journaliere"
        verbose_name_plural = "Tresoreries journalieres"
        ordering = ['-date']
        unique_together = ['date', 'warehouse']
        indexes = [
            models.Index(fields=['-date'], name='tj_date_idx'),
            models.Index(fields=['warehouse', '-date'],
                         name='tj_wh_date_idx'),
            models.Index(fields=['date', 'warehouse'],
                         name='tj_date_wh_idx'),
        ]

    def __str__(self):
        return f"{self.date} - {self.warehouse.name}"

    @property
    def variation(self):
        return self.solde_fermeture - self.solde_ouverture

    # =========================================================
    # METHODES DETAILLEES
    # =========================================================

    def get_mouvements_du_jour(self):
        """
        Retourne tous les mouvements effectues du jour.
        N+1 : select_related sur caisse, compte_bancaire, created_by.
        """
        return (
            MouvementTresorerie.objects
            .filter(
                warehouse=self.warehouse,
                date_mouvement__date=self.date,
                status='effectue'
            )
            .select_related('caisse', 'compte_bancaire', 'created_by')
            .order_by('date_mouvement')
        )

    def get_frais_du_jour(self):
        """
        CORRECTION N+1 : avant 1 requete par frais, maintenant 1 seule.
        """
        frais_list = []
        mouvements = list(
            self.get_mouvements_du_jour()
            .filter(type_mouvement='decaissement', source_type='frais')
        )

        # CORRECTION : recuperer tous les Frais en 1 seule requete
        source_ids = [m.source_id for m in mouvements if m.source_id]
        frais_map = {}
        if source_ids:
            frais_map = {
                f.id: f
                for f in Frais.objects.filter(id__in=source_ids)
            }

        for mvt in mouvements:
            frais = frais_map.get(mvt.source_id)
            frais_list.append({
                'mouvement_reference': mvt.reference,
                'source_reference': mvt.source_reference or '-',
                'libelle': mvt.libelle,
                'montant': mvt.montant,
                'mode_paiement': mvt.get_mode_paiement_display(),
                'date_mouvement': mvt.date_mouvement,
                'caisse': mvt.caisse.nom if mvt.caisse else '-',
                'compte_bancaire': (
                    mvt.compte_bancaire.nom if mvt.compte_bancaire else '-'
                ),
                'created_by': (
                    mvt.created_by.full_name if mvt.created_by else '-'
                ),
                'titre': frais.titre if frais else None,
                'categorie': (
                    frais.get_categorie_display() if frais else None
                ),
                'beneficiaire': frais.beneficiaire if frais else None,
                'piece_justificative': (
                    frais.piece_justificative if frais else None
                ),
            })
        return frais_list

    def get_entrees_du_jour(self):
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
                'compte_bancaire': (
                    mvt.compte_bancaire.nom if mvt.compte_bancaire else '-'
                ),
            })
        return entrees_list

    def get_sorties_du_jour(self):
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
                'compte_bancaire': (
                    mvt.compte_bancaire.nom if mvt.compte_bancaire else '-'
                ),
            })
        return sorties_list

    # =========================================================
    # GENERATION JOURNALIERE
    # =========================================================

    def generer_journaliere(self, date_jour):
        """
        Genere ou met a jour la tresorerie journaliere.
        CORRECTION N+1 : 1 seule requete aggregate au lieu de 10.
        """
        warehouse = self.warehouse

        # Solde d'ouverture (jour precedent)
        jour_precedent = date_jour - timedelta(days=1)
        precedent = TresorerieJournaliere.objects.filter(
            date=jour_precedent, warehouse=warehouse
        ).only('solde_fermeture').first()

        solde_ouverture = (
            precedent.solde_fermeture if precedent else Decimal('0')
        )

        # Mouvements du jour
        mouvements = MouvementTresorerie.objects.filter(
            warehouse=warehouse,
            date_mouvement__date=date_jour,
            status='effectue'
        )

        # CORRECTION N+1 : UNE SEULE requete aggregate pour tout
        zero_decimal = Value(0, output_field=DecimalField(
            max_digits=15, decimal_places=2))

        totals = mouvements.aggregate(
            total_entrees=Coalesce(
                Sum('montant', filter=Q(type_mouvement='encaissement')),
                zero_decimal
            ),
            total_sorties=Coalesce(
                Sum('montant', filter=Q(type_mouvement='decaissement')),
                zero_decimal
            ),
            entrees_ventes=Coalesce(
                Sum('montant', filter=Q(
                    type_mouvement='encaissement', source_type='vente')),
                zero_decimal
            ),
            entrees_reglements=Coalesce(
                Sum('montant', filter=Q(
                    type_mouvement='encaissement',
                    source_type='paiement_client')),
                zero_decimal
            ),
            entrees_autres=Coalesce(
                Sum('montant', filter=Q(
                    type_mouvement='encaissement'
                ) & ~Q(source_type__in=['vente', 'paiement_client'])),
                zero_decimal
            ),
            sorties_achats=Coalesce(
                Sum('montant', filter=Q(
                    type_mouvement='decaissement', source_type='achat')),
                zero_decimal
            ),
            sorties_frais=Coalesce(
                Sum('montant', filter=Q(
                    type_mouvement='decaissement', source_type='frais')),
                zero_decimal
            ),
            sorties_salaires=Coalesce(
                Sum('montant', filter=Q(
                    type_mouvement='decaissement', source_type='salaires')),
                zero_decimal
            ),
            sorties_autres=Coalesce(
                Sum('montant', filter=Q(
                    type_mouvement='decaissement'
                ) & ~Q(source_type__in=['achat', 'frais', 'salaires'])),
                zero_decimal
            ),
            nb_entrees=Count(
                'id', filter=Q(type_mouvement='encaissement')),
            nb_sorties=Count(
                'id', filter=Q(type_mouvement='decaissement')),
            nb_operations=Count('id'),
        )

        # Mise a jour de l'objet
        self.solde_ouverture = solde_ouverture
        self.total_entrees = totals['total_entrees']
        self.total_sorties = totals['total_sorties']
        self.entrees_ventes = totals['entrees_ventes']
        self.entrees_reglements = totals['entrees_reglements']
        self.entrees_autres = totals['entrees_autres']
        self.sorties_achats = totals['sorties_achats']
        self.sorties_frais = totals['sorties_frais']
        self.sorties_salaires = totals['sorties_salaires']
        self.sorties_autres = totals['sorties_autres']
        self.nb_operations = totals['nb_operations']
        self.nb_entrees = totals['nb_entrees']
        self.nb_sorties = totals['nb_sorties']
        self.solde_fermeture = (
            solde_ouverture + totals['total_entrees'] - totals['total_sorties']
        )

        self.save()
        return self
