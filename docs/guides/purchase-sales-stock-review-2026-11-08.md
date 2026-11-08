# Achats, ventes et stock : revue des manques (2026-11-08)

Revue du code (modèles et services `purchasing`, `sales`, `inventory`, `catalog`, `partners`) comparée aux
décisions et aux questions déjà tranchées. Réponses du propriétaire le même jour : tout est voulu ; FEFO avec FIFO en
départage ; lot périmé toujours bloqué ; sortie de stock à la livraison pour tout BL ; transformations avec frais.
Tâches : `docs/phases/01-stock-core.md`, P1-T20 à P1-T27.

| # | Manque | Gravité | Tâche |
|---|---|---|---|
| 1 | Pas de retour fournisseur ni d'avoir fournisseur (le mouvement `supplier_return` existe, rien ne le poste) | haute | P1-T21 |
| 2 | Écart kg facturés / kg acceptés payé au fournisseur, jamais réclamé | haute | P1-T21 |
| 3 | Un lot périmé peut être vendu ou chargé | haute | P1-T20 (fait) |
| 4 | Ordre de sortie FIFO et non FEFO | haute | P1-T20 (fait) |
| 5 | Pas d'origine du lot (zone FAO, sauvage/élevage, bateau, agrément) ni d'écran de rappel | moyenne | P1-T23 |
| 6 | Pas de relevés de température (réception, chambres, camions) | moyenne | P1-T24 |
| 7 | Pas de transformation (nettoyage, filetage, déclassement) | moyenne | P1-T25 |
| 8 | Facture fournisseur : le total du papier du fournisseur n'est pas saisi ni comparé | moyenne | P1-T22 |
| 9 | Fournisseur : pas de délai de paiement ni de « TVA » par défaut | moyenne | P1-T22 |
| 10 | Bug 11 : sortie de stock d'un BL direct à la confirmation | moyenne | P1-T26 |
| 11 | `min_stock` n'avertit que ; pas de proposition de commande | basse | P1-T27 |
| 12 | Inventaire : la quantité attendue est visible pendant le comptage | basse | P1-T27 |
| 13 | Demande de prix : pas d'impression pour les fournisseurs | basse | P1-T27 |
| 14 | Demande du site : ressaisie à la main en devis ou BL | basse | P1-T27 |
| 15 | Pas de rapports achats (prix, écarts, retards, retours) | basse | P1-T27 |
| 16 | B9, B11 (revue comptable) et TTN | — | attendent le comptable / la spécification TTN |
