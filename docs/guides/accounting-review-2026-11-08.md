# Revue comptable des calculs (2026-11-08)

Revue du code par l'angle d'un expert-comptable tunisien. Les points « à confirmer » sont à valider par
l'expert-comptable de la société avant d'être codés (voir `docs/OPEN_QUESTIONS.md`, Q5 et Q26).

## Bugs de calcul

| # | État | Problème | Où |
|---|---|---|---|
| B1 | à faire | La facture fournisseur ne compte ni la TVA ni le timbre : le prix d'achat est hors TVA et le total = kg × prix, même « Achat avec TVA ». La dette fournisseur est trop basse. | `purchasing/services.py` `_set_receipts` |
| B2 | **corrigé (D-283)** | Une facture mêlant des lots avec et sans TVA mettait 19 % sur toutes les lignes ; le BL et la facture ne concordaient pas. | `sales/selectors.py` `proposed_vat_rates` |
| B3 | **corrigé (D-283)** | Le seuil de 1 000 DT de la retenue comptait le timbre et les frais. | `sales/invoicing.py` |
| B4 | à faire | La retenue s'applique à tout client dès 1 000 DT ; il faut un indicateur « soumis à retenue » par client. | `invoicing.withholding_applies`, D-250 |
| B5 | à faire | Avec des prix TTC (`prices_include_vat`), le CA d'un lot (et la part partenaire) inclut la TVA. | `sales/services.py` `_post_line` |
| B6 | à décider | Le coût d'une journée d'employé sur un lot (salaire / 26) n'inclut pas la CNSS patronale. | `hr/selectors.py` (D-041) |
| B7 | à confirmer | Primes hors CNSS (D-263) : en principe soumises à cotisation. | `hr/services.py` `add_prime` |
| B8 | à faire | Pas de prorata de salaire à l'embauche ni de date de sortie. | `hr/services.py` `generate_month` |
| B9 | à confirmer | Un avoir total restitue le timbre fiscal. | `sales/services.py` `create_credit_note` |
| B10 | **corrigé (D-283)** | L'estimation et la facture prenaient le taux du jour, le BL celui du jour de vente. | idem B2 |
| B11 | mineur | En prix TTC, le PU HT est arrondi seul (PU HT × kg ≠ montant HT au millime près). | `sales/invoicing.py` |

## Non couvert (obligations tunisiennes)

1. Régime TVA par produit (produits de la pêche frais exonérés ; 7 % / 19 %) et prorata de déduction.
2. TVA déductible sur achats et dépenses.
3. État de la déclaration mensuelle : TVA collectée / déductible / crédit reporté, droit de timbre, retenues opérées, TCL, TFP et FOPROLOS.
4. Retenues à opérer par la société (fournisseurs ≥ 1 000 DT, loyers, honoraires), certificats, déclaration annuelle de l'employeur.
5. Retenue de 25 % de la TVA par les clients publics.
6. Paie : IRPP au barème, CSS, bulletin de paie PDF, déclaration trimestrielle CNSS.
7. Paiement en espèces ≥ 5 000 DT : blocage ou trace, clients et fournisseurs.
8. TTN / El Fatoora (D-016, en attente) : risque de conformité.
9. Remise à zéro d'un solde client : justificatif de créance irrécouvrable.
10. Traitement fiscal du partage de profit avec les fournisseurs partenaires.

## Améliorations pour l'équipe finance

Export comptable (plan comptable tunisien), écran « Déclarations du mois », rapprochement bancaire, balance âgée et
relances, échéancier et trésorerie prévisionnelle (P9-T06), facturation groupée de fin de mois, verrouillage de
période, contrôles avant clôture, exports Excel partout, registre des certificats de retenue.
