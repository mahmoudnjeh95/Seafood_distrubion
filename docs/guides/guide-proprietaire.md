# Guide du propriétaire : la journée dans l'application d'administration

Ce guide suit le travail du propriétaire, dans l'ordre d'une journée et d'un mois. Les mots entre « guillemets » sont
écrits exactement comme à l'écran. Le menu de gauche est rangé en quatre groupes : **Pilotage**, **Commercial**,
**Marchandise** et **Finances**.

> **À savoir.** Les points marqués **(provisoire)** reposent sur une règle qui n'est pas encore confirmée par le
> client ou par le comptable. Ils peuvent changer. La liste est en bas du guide.

## 0. Les rôles

| Rôle | Ce qu'il fait |
|---|---|
| **Propriétaire** | Tout : approuve, clôture, voit les salaires et le résultat des lots |
| **Gestionnaire** | Saisit achats, ventes, transferts, dépenses ; approuve les dépenses ; ne voit pas les salaires |
| **Comptable** | Lit presque tout, voit les salaires et le résultat ; vérifie la clôture mensuelle |
| **Chauffeur** | Utilise seulement l'application du téléphone (voir le guide du chauffeur) |

Un écran en « Consultation seule » est un écran où votre rôle ne peut que lire.

## 1. Acheter : bon d'achat et réception (menu « Achats »)

Un arrivage se saisit avec son **poids net réel** : le stock et les lots se créent tout seuls.

### Le bon d'achat (facultatif)

1. Menu **Achats**, onglet **Bons d'achat**, touchez **Nouveau bon d'achat**.
2. Choisissez le fournisseur, ajoutez les produits avec **Ajouter un produit** (kilos commandés et prix convenu).
3. Touchez **Enregistrer le bon d'achat**. Un bon enregistré ne se modifie plus.

### La réception

1. Onglet **Réceptions**, touchez **Nouvelle réception** (ou « Recevoir » depuis le bon d'achat : il pré-remplit ce qui reste à recevoir).
2. Choisissez le **Fournisseur**, **Reçu dans** (la chambre froide), la **Date de réception** et le **N° du bon de livraison ou de la facture**.
3. Pour chaque produit : **Facturé (kg)** (ce que le fournisseur réclame), **Accepté (kg)** (ce qui entre vraiment en stock), **Coût (DT/kg)**, et si besoin **À consommer avant**.
4. L'écran affiche **Total facturé** et **Valeur entrée en stock**. Un écart entre facturé et accepté est signalé.
5. Touchez **Enregistrer la réception**. « Réception … enregistrée : lots créés et stock mis à jour. »

Une réception enregistrée ne se modifie plus : une erreur se corrige par un retour fournisseur ou un ajustement.

### Payer le fournisseur

1. Onglet **Factures**, **Nouvelle facture** : choisissez les réceptions, puis **Enregistrer et valider** (ou **Enregistrer le brouillon**).
   Une facture validée compte dans le solde du fournisseur et ne se modifie plus.
2. Onglet **Paiements**, **Nouveau paiement** : choisissez les « Factures à régler », puis **Enregistrer le paiement**.

**(provisoire)** L'échéance du fournisseur est de 30 jours après la facture, et les modes de paiement sont à confirmer.

## 2. Le stock et les transferts (menu « Stock frigo & camions »)

Rubriques en haut : **Emplacements**, **Mouvements**, **Transferts**, **Pertes**, **Inventaires**.

### Charger le camion le matin

1. Rubrique **Transferts**, touchez **Nouveau transfert**.
2. Choisissez **Départ** (la chambre froide), **Arrivée** (le camion) et le **Jour**.
3. Ajoutez les produits et les kilos avec **Ajouter un produit**. Le prix du jour part avec le chauffeur.
4. **Enregistrer le brouillon** : rien ne bouge encore. Puis **Valider le transfert** : le stock est déplacé, le lot le plus ancien d'abord.
5. Le chauffeur voit alors le chargement dans son application.

Le menu **Camions du jour** sert à dire quel chauffeur prend quel camion ; le chauffeur peut aussi choisir lui-même.

### Le soir

Le chauffeur rend l'invendu depuis son téléphone. Vous pouvez aussi faire un transfert de type « Retour ».
**Journées chauffeurs** : voir la partie 6.

### Pertes

1. Rubrique **Pertes**, **Déclarer une perte** : emplacement, produit, poids, raison.
2. Une petite perte sort du stock tout de suite. Une plus grosse attend le propriétaire : ouvrez-la et touchez
   **Valider la perte** ou **Refuser** (avec la raison). Rien ne sort du stock tant qu'elle n'est pas validée.
3. **Changer le seuil** règle le poids à partir duquel une perte attend votre accord. **(provisoire)** 2 kg.

### Inventaire

Rubrique **Inventaires** : comptez le stock réel ; les écarts deviennent des corrections tracées.

## 3. Les prix du jour (menu « Prix du jour »)

1. Pour chaque produit, tapez le prix de vente (et le minimum).
2. Touchez **Enregistrer les prix**. Un prix sous le minimum est enregistré mais signalé « Sous le minimum ».
3. Sur un devis ou une vente, une remise qui ramène le prix sous le minimum est **refusée**. Le propriétaire et le gérant peuvent
   l'accepter en écrivant une **raison** (gardée dans le journal). Un produit sans minimum n'est pas contrôlé : l'écran le signale.

## 4. Vendre : devis, bon de livraison, facture

### Le devis (menu « Devis »)

1. **Nouveau devis** : client, date, « Valable jusqu'au », produits (kilos, prix, remise).
2. **Enregistrer et envoyer** (ou **Enregistrer le brouillon**). Un devis envoyé ne se modifie plus.
3. Quand le client répond : **Accepté par le client** ou **Refusé par le client** (avec un motif facultatif).
   Un devis sans réponse devient « Expiré ».

### Le bon de livraison (BL), menu « Ventes & factures »

1. Depuis un devis accepté : **Convertir en vente**, puis **Créer et confirmer**.
   Ou directement : **Nouvelle vente** (client, « Depuis » = chambre froide ou camion, produits, paiement sur place).
   Pour un client de passage : **Vente comptoir** (pesez, encaissez).
2. **Valider la vente (BL)** ou **Valider et imprimer le BL** : le stock sort, la vente devient un BL numéroté « BL-2026-0001 ».
3. Une vente confirmée peut être annulée avec **Annuler la vente** (motif obligatoire) : les kilos reviennent dans leurs lots.

### La facture (facultative, faite après)

1. Dans **Ventes**, filtrez sur **À facturer**, cochez un ou plusieurs BL **du même client**, puis **Facturer la sélection**.
   Ou, sur un BL : **Facturer**.
2. Vérifiez la TVA, le timbre fiscal et la retenue à la source ; **Enregistrer et recalculer** si vous changez quelque chose.
3. **Émettre la facture**, puis **Émettre**. La facture émise est figée.
4. Pour corriger une facture émise : **Faire un avoir** (total ou partiel). Les kilos rendus peuvent être remis en stock ou passés en perte.
5. Les règles de TVA et de timbre se règlent dans **Réglages de la facture** (Factures, « Paramètres financiers »).

**(provisoire)** La transmission à la TTN / El Fatoora n'est pas branchée. La TVA par défaut est à confirmer par le comptable.

## 5. Encaisser les clients (menu « Règlements »)

1. Ouvrez la page du client et touchez **Enregistrer un règlement**, ou touchez **Encaisser** dans « Créances par ancienneté ».
2. Tapez le **Montant (DT)**, le **Mode de paiement**, **Reçu le**, et la **Référence** (n° de chèque, virement).
3. **Enregistrer le règlement**. Il solde d'abord les plus anciennes ventes ; ce qui dépasse reste en crédit du client.
4. Une erreur : **Annuler** le règlement (avec la raison). Il reste dans la liste, marqué « Annulé ».
5. Retenue à la source : enregistrez le certificat du client sur la facture (**Enregistrer le certificat**, **Joindre le fichier**).

**(provisoire)** Quand un client dépasse sa limite de crédit, la vente est **bloquée** par défaut. Le réglage est dans
les paramètres (« Bloquer la vente », « Demander l'approbation du propriétaire ou du gérant », « Avertir et consigner »).
Les retards se comptent à partir de la date de la facture ou de la vente.

## 6. Contrôler les journées des chauffeurs (menu « Journées chauffeurs »)

1. En haut, « Envois refusés » liste ce que les téléphones n'ont pas pu envoyer. Appelez le chauffeur, puis touchez **Traité**.
2. Ouvrez une journée « À vérifier » : vous voyez l'argent attendu, l'argent compté, l'**Écart**, le stock chargé/vendu/perdu/rendu.
3. Touchez **Approuver la journée**, ou **Demander une justification** (écrivez la question puis **Envoyer la question**).
   Une journée approuvée est verrouillée : le chauffeur ne peut plus rien y ajouter.

## 7. Les charges (menu « Charges »)

Rubriques : **Dépenses**, **Calendrier journaliers**, **Journaliers**, **Chambres froides : coût**, **Frais généraux**.

### Une dépense

1. **Nouvelle dépense** : catégorie, montant, mode de paiement, libellé, « Payé à », justificatif (photo ou PDF).
2. **Imputer à** : **Charge générale** (sans lot), **Un lot** (le coût devient celui du lot) ou **Un camion (frais du jour)**
   (réparti entre les lots chargés dans ce camion ce jour-là, au prorata des kilos).
3. **Enregistrer le brouillon**, ou **Enregistrer et approuver**.
4. Les dépenses saisies par les chauffeurs arrivent « À approuver » : ouvrez-les et touchez **Approuver** ou **Refuser** (avec le motif).
5. Une dépense approuvée ou refusée ne change plus : on corrige par une nouvelle dépense.

### Les journaliers

- **Journaliers** : **Nouveau journalier** (nom, paie habituelle par jour). Ce ne sont pas des salariés.
- **Calendrier journaliers** : touchez un jour, choisissez le journalier, le lot (ou « Aucun lot (travail général) »),
  le montant (vide = paie habituelle), puis **Ajouter** ou **Ajouter et approuver**.

### Le froid et les frais généraux

- **Chambres froides : coût** : à la fin du mois, tapez la facture d'électricité (**Enregistrer et approuver**).
  Avant cela, les lots paient une estimation au tarif du mois précédent ; l'approbation corrige la différence sur chaque lot.
  Le propriétaire règle le **poids** de chaque chambre (une chambre à −20 °C pèse plus).
- **Frais généraux** : **Ajouter un frais mensuel** (loyer, comptable, assurance), puis chaque mois **Générer le mois**
  (ou **Générer et approuver**). **Facture sur plusieurs mois** répartit une facture annuelle à parts égales.

Les frais généraux et le froid sont comptés **à l'heure** : une journée vaut 24 heures, et chaque heure est partagée entre
les lots présents dans la chambre pendant cette heure, selon leurs kilos. Un lot qui reste de 00 h 28 à 21 h 38 paie
21 h 10 de chambre, pas une journée entière. Le temps où la chambre est vide n'est facturé à personne. Pour aujourd'hui,
on compte les heures déjà passées (décidé le 14/10/2026, D-142). **(provisoire)** Restent à confirmer avec le client : la
répartition des frais de camion (question Q24 de `docs/OPEN_QUESTIONS.md`), et le calcul des factures d'électricité déjà approuvées (D-142).

## 8. Le personnel et les salaires (menu « Personnel & salaires »)

Réservé au propriétaire (qui modifie) et au comptable (qui lit). Onglets : **Paie** et **Employés**.

1. **Employés**, **Nouvel employé** : nom, poste, « Salaire mensuel brut (DT) », « Taux CNSS employeur (%) », compte de connexion.
2. **Paie**, choisissez le mois, touchez **Générer le mois** : une paie en brouillon est créée pour chaque employé actif.
3. Pour des heures supplémentaires ou des retenues sur un brouillon : **Modifier** sur la ligne, puis **Enregistrer**.
4. **Approuver** (ou **Tout approuver**) : la paie devient la charge du mois et ne change plus.
5. **Payer** : date, montant, mode de paiement, référence. Un paiement peut solder une paie, une partie. Chaque paiement sort de la trésorerie le jour où il est fait : la Caisse pour les espèces, la banque pour le reste. La paie et le paiement affichent « Débité de la trésorerie ».
6. Correction après approbation : **Ajuster** (montant positif ou négatif, avec le motif).
7. **Prime** : ajoute un montant positif à ce qui est dû pour le mois, avec son motif. Pas de paiement séparé : la prime se paie avec le salaire.
8. **Avance sur salaire** : dans **Payer**, choisissez « Avance sur salaire ». L'avance se déduit du salaire du mois. Si elle dépasse ce qui reste dû, cochez la confirmation (sinon elle est refusée).
7. Sur la page d'un employé, **Jours sur lot** note les jours passés sur un lot : un jour coûte le salaire mensuel / 26.

**(provisoire)** Le taux CNSS employeur est de 17,07 % par défaut, à confirmer par le comptable.

## 9. Les lots en partenariat et la clôture d'un lot

Le résultat est calculé **lot par lot**, et partagé avec le fournisseur partenaire. Trois soldes restent séparés :
ce qui est dû au fournisseur pour ses marchandises, son capital investi, et sa part de bénéfice.

### Mettre un lot en partenariat

1. Menu **Stock frigo & camions**, ouvrez la page du lot.
2. Touchez **Mettre en partenariat** (possible tant que le lot n'est pas vendu).
3. Choisissez le **Fournisseur partenaire**, l'**Apport du propriétaire (DT)**, l'**Apport du partenaire (DT)**,
   la **Part du bénéfice (%)** et la **Part de la perte (%)** : les deux taux peuvent être différents.
4. **Enregistrer**. Un seul partenaire par lot. Le menu **Partage des bénéfices** liste tous les partenariats.

### Suivre le résultat

Sur la page du lot, **Résultat du lot** montre, à ce jour : les ventes, le coût d'achat des kilos vendus, les pertes,
les coûts (saisis sur le lot, employés, frais généraux), puis le résultat et la part de chacun. **Coûts du lot** permet
d'**Ajouter une dépense** ou **Ajouter une journée**.

### Clôturer le lot

1. Le bloc **Pour clôturer le lot** liste ce qui bloque : stock restant, coûts en attente, clients qui doivent encore de l'argent.
2. Quand tout est bon, **Clôturer le lot**, cochez **Tous les coûts du lot sont saisis**, puis **Clôturer**.
3. Le résultat est figé. Si vous vous êtes trompé : **Rouvrir le lot** (avec un motif ; la clôture précédente reste dans l'historique).
4. Un coût qui arrive après la clôture n'ouvre pas le lot : il est reporté sur le prochain règlement du partenaire
   (**Reporter sur le solde du partenaire**).

### Régler le partenaire

1. Sur le lot clôturé, **Règlement du partenaire** montre : capital rendu, part de bénéfice, perte déjà déduite, **À payer au partenaire**.
2. **Régler avec le partenaire** : ajoutez un ou plusieurs paiements (montant, mode, référence) jusqu'à ce que **Reste à saisir** soit à zéro,
   puis **Enregistrer le règlement**.
3. **Relevé du partenaire (PDF)** produit la feuille à lui remettre : le calcul expliqué étape par étape.

**(provisoire)** Une perte au-delà du capital du partenaire reste sur son solde de part de bénéfice. On ne peut pas encore
clôturer un lot dont des ventes ne sont pas payées en choisissant de passer outre.

## 10. La clôture mensuelle (menu « Clôture mensuelle »)

Réservée au propriétaire et au comptable. Choisissez le mois dans **Mois** (un mois en cours ne se clôture pas).

1. Lisez le **Résultat du mois** : ventes − coût d'achat des kilos vendus − pertes − dépenses − salaires.
   Ce qui reste en stock n'est pas une charge : il est montré dans **Stock à la fin du mois**.
2. Regardez les **Contrôles**. Ceux marqués « Bloquant » doivent être réglés : dépenses non approuvées, salaires encore en brouillon,
   pertes en attente. Ceux marqués « À voir » sont des avertissements.
3. Le comptable (ou le propriétaire) touche **Vérifier le mois**.
4. Le propriétaire touche **Approuver et figer**. Les chiffres du mois sont figés. Si les chiffres ont bougé depuis la
   vérification, il faut **Refaire la vérification** d'abord.
5. En cas d'erreur : **Rouvrir** (avec un motif). Les chiffres figés restent dans l'historique.

La clôture mensuelle ne change pas les parts des partenaires : elles se règlent lot par lot (partie 9).

**(provisoire)** Une facture couvrant plusieurs mois compte en entier dans le mois où elle est datée. Une vente ou un coût
enregistré après la clôture n'est pas bloqué : l'écran montre l'écart avec les chiffres figés.

## Points provisoires en un coup d'œil

| Sujet | Règle actuelle | À confirmer avec |
|---|---|---|
| Frais généraux (loyer, comptable) : jours comptés | Un 26e du montant mensuel, compté à l'heure : chaque heure partagée entre les lots présents pendant cette heure, selon les kilos (D-142, qui remplace la règle du jour de Q21) | Le client (Q25) |
| Frais de camion du jour | Répartis entre les lots chargés, au prorata des kilos | Le client (Q24) |
| Prix d'une vente du chauffeur | Prix du client, sinon prix du jour ; le total affiché peut différer du reçu | Le client |
| Seuil de validation des pertes | 2 kg | Le client |
| Échéance fournisseur, modes de paiement | 30 jours | Le comptable |
| Taux CNSS employeur, TVA par défaut | 17,07 % ; 19 % | Le comptable |
| Limite de crédit dépassée | La vente est bloquée | Le client |
| Perte au-delà du capital du partenaire | Reste sur le solde de part de bénéfice | Le client |
| Facture électronique (TTN / El Fatoora) | Pas branchée | Le comptable |
| Textes arabes du chauffeur | Pas encore relus par une personne de langue arabe | Un locuteur arabe |
