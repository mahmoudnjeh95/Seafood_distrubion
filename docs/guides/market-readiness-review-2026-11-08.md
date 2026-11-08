# Revue avant mise sur le marché (2026-11-08)

Revue de l'application sous l'angle fiscal, juridique et métier (mareyage / distribution de produits de la mer en
Tunisie), avant de la vendre à d'autres distributeurs (Q17). Elle complète `accounting-review-2026-11-08.md` (B1 à
B11, déjà corrigés en partie) et ne la répète pas. **Rien ici n'est un avis juridique** : chaque point « à
confirmer » se valide avec l'expert-comptable et un avocat avant d'être codé. Les taux et seuils de la loi de finances
2026 se lisent dans le texte publié au JORT et les notes communes de la DGI, pas dans des résumés.

Légende : 🔴 bloquant pour vendre · 🟠 à faire avant les premiers clients · 🟢 amélioration.

## 1. Facturation et TVA

| # | Niveau | Constat (vérifié dans le code) | Ce qu'il faut |
|---|---|---|---|
| F1 | 🔴 | **TTN / El Fatoora non implémenté** (D-016). La facture électronique est obligatoire pour les assujettis à la TVA depuis 2026, et la LF 2026 (loi 17-2025, art. 53) l'étend aux services ; amende citée de 100 à 500 DT par facture papier, plafond 50 000 DT (application des sanctions discutée en 2026). Un ERP vendu en Tunisie sans El Fatoora sera écarté par les acheteurs. | Format TEIF (XML), signature électronique (certificat TunTrust / ANCE), envoi à TTN, référence et QR code TTN sur le PDF, statut par facture. À planifier comme phase à part entière. |
| F2 | 🔴 | `issue_invoice` (`sales/services.py`) émet une facture **sans raison sociale, sans MF ni adresse du vendeur** : les champs de Paramètres financiers sont facultatifs. Une facture sans les mentions de l'art. 18 du Code de la TVA n'est pas valable et sa TVA n'est pas déductible pour le client. | Refuser l'émission tant que raison sociale, adresse et MF du vendeur ne sont pas remplis ; contrôler le format du MF (`1234567/A/B/M/000`). |
| F3 | 🟠 | Le client peut n'avoir **ni MF ni adresse**. Pour un client professionnel assujetti, l'art. 18 exige son identifiant fiscal. | Avertir (ou bloquer selon le type de client) quand un client professionnel n'a pas de MF ; CIN pour une personne physique (déjà possible, D-283). |
| F4 | 🟠 | Régime TVA des produits de la mer : tout est à 19 % par défaut (Q5). Les produits de la pêche frais relèvent d'une exonération ; le frais/congelé/transformé n'a pas le même régime ; la LF 2022 a fixé une base particulière pour les ventes de produits congelés. Une erreur ici fausse **chaque** facture. | L'expert-comptable donne le régime par catégorie de produit ; l'app propose par défaut le taux de la catégorie. Ligne exonérée : afficher « Exonéré » plutôt que 0 %. Une société mêlant opérations exonérées et taxables applique un **prorata de déduction**. |
| F5 | 🟠 | TVA déductible absente : ni les dépenses (`expenses`) ni les factures fournisseurs ne portent une TVA récupérable exploitable pour la déclaration. | TVA par dépense et par facture fournisseur, avec MF du fournisseur et n° de sa facture. |
| F6 | 🟠 | Pas d'écran **déclaration mensuelle** : TVA collectée / déductible / crédit reporté, droit de timbre collecté, retenues opérées, TCL (0,2 % du CA local), TFP et FOPROLOS sur salaires. | Écran « Déclarations du mois » (déjà prévu) avec export ; aide au remplissage, pas de télédéclaration. |
| F7 | 🟠 | Retenue de 25 % de la TVA par les acheteurs publics (État, collectivités, établissements publics) non gérée. | Type de client « public » : retenue TVA en plus de la retenue sur le montant. |
| F8 | 🟢 | Avoir : la restitution du timbre fiscal sur un avoir total est à confirmer (B9). | Réponse de l'expert-comptable. |

## 2. Retenues à la source opérées par la société

| # | Niveau | Constat | Ce qu'il faut |
|---|---|---|---|
| R1 | 🔴 | La société subit une retenue de ses clients (D-250, D-292), mais **n'en opère aucune** : rien dans `purchasing`, `expenses` ou `treasury`. Un acheteur soumis à l'impôt sur les sociétés retient sur ses paiements fournisseurs ≥ 1 000 DT TTC, sur les loyers et les honoraires (expert-comptable, avocat). Sans retenue, la société paie l'impôt non retenu plus les pénalités. | Taux par type de paiement (achats, loyer, honoraires) dans les paramètres, retenue au paiement, **certificat de retenue** PDF pour le fournisseur, total mensuel pour la déclaration, déclaration annuelle de l'employeur. Taux exacts de 2026 à confirmer. |
| R2 | 🟠 | Les **pêcheurs et petits fournisseurs du port** (achat terrain, Q28) sont souvent au forfait ou sans MF ; la retenue et la déductibilité de ces achats changent. | Statut fiscal par fournisseur (réel / forfaitaire / sans MF), alerte quand un achat sans facture est payé. |
| R3 | 🟢 | Registre des certificats reçus des clients : il permet d'imputer les retenues subies sur l'impôt de fin d'année. | Saisie du certificat reçu contre le règlement client. |

## 3. Paie et social

| # | Niveau | Constat | Ce qu'il faut |
|---|---|---|---|
| P1 | 🔴 (si la paie est vendue) | **IRPP non calculé** : il est tapé à la main dans « déductions » (D-119). Pas de **CSS** (contribution sociale de solidarité), pas de **bulletin de paie PDF** (aucun gabarit dans `hr`). Un bulletin est obligatoire (Code du travail). | Barème IRPP annuel, frais professionnels, déductions pour charges de famille, CSS ; bulletin PDF. Sinon, vendre le module comme « suivi des salaires » et non comme paie. |
| P2 | 🟠 | Taux CNSS provisoires (17,07 % patronal, 9,18 % salarial, Q26) ; primes hors CNSS (B7), à confirmer. Pas d'accident du travail selon le secteur, pas de plafond ou régime particulier. | Validation par l'expert-comptable ; taux par régime. |
| P3 | 🟠 | Pas de **déclaration trimestrielle CNSS** (DS) ni de prorata à l'embauche ou au départ (B8). | Export de la DS au format CNSS ; dates d'entrée et de sortie. |
| P4 | 🟢 | TFP et FOPROLOS (sur la masse salariale) absents du coût employeur. | Les ajouter au coût et à la déclaration (F6). |

## 4. Espèces, créances, traçabilité des écritures

| # | Niveau | Constat | Ce qu'il faut |
|---|---|---|---|
| E1 | 🟠 | Plafond espèces à 5 000 DT avec **confirmation** côté ventes (D-273). Côté **achats** (paiement du pêcheur ou du fournisseur en liquide), aucun contrôle. Une source sur la LF 2026 dit que les restrictions de 2019 sont abrogées, une autre que l'amende de 20 % sur les achats payés en espèces au-delà de 5 000 DT reste ; elles se contredisent. | Le même contrôle sur les paiements fournisseurs et les dépenses ; règle exacte à confirmer avec l'expert-comptable sur le texte. |
| E2 | 🟠 | Remise à zéro d'un solde client sans justificatif de créance irrécouvrable : la perte n'est pas déductible sans preuve. | Pièce jointe obligatoire (jugement, PV d'huissier) et motif. |
| E3 | 🟢 | Pas de **verrouillage de période** : une écriture datée dans un mois déjà déclaré reste possible. | Clôture d'un mois déclaré ; correction = écriture du mois en cours. |
| E4 | 🟢 | Pas d'export vers le **système comptable des entreprises** (loi 96-112) : journal, grand livre, plan comptable tunisien. Le client garde un expert-comptable qui ressaisit tout. | Export des écritures (CSV/Excel) au plan de comptes tunisien. |

## 5. Partage de profit avec les fournisseurs partenaires

| # | Niveau | Constat | Ce qu'il faut |
|---|---|---|---|
| S1 | 🔴 juridique | Le partage par lot (D-040) repose sur un **accord verbal** (Q2). Fiscalement, c'est proche d'une **association en participation** ; sans contrat écrit, l'administration peut requalifier les parts versées (non déductibles, ou revenus non déclarés pour le partenaire), et un litige sur un lot n'a aucune base. | Modèle de **contrat de participation par lot** (capital, taux profit / perte, charges imputées, clôture) rédigé par un avocat ; l'app imprime le relevé de lot signé par les deux. |
| S2 | 🟠 | Les charges réparties sur les lots (électricité, loyer, salaires /26, Q25) déterminent la part du partenaire. La méthode doit être écrite dans le contrat, sinon chaque clôture est contestable. | Annexe au contrat décrivant les clés de répartition, reprise de l'écran de paramètres. |

## 6. Règles métier de la pêche (sanitaire et circuits)

| # | Niveau | Constat | Ce qu'il faut |
|---|---|---|---|
| M1 | 🟠 | Le lot garde fournisseur, coût et date limite, mais **ni origine, ni zone ou date de capture, ni agrément sanitaire** du fournisseur. La traçabilité est exigée par la loi 2019-25 sur la sécurité sanitaire des aliments (retrait d'un lot) et par l'export (certificat de capture UE contre la pêche INN). | Champs sur la réception : origine (pêche / élevage), zone, date de capture, n° d'agrément ; fiche de traçabilité d'un lot (de qui, vers quels clients). |
| M2 | 🟠 | **Chaîne du froid** : la température de stockage est sur le produit, mais aucun relevé de température des chambres froides et des camions. Les services vétérinaires le demandent lors d'un contrôle. | Relevé journalier (manuel ou sonde), alerte hors plage. |
| M3 | 🟢 | **Repos biologique et tailles minimales** (ex. poulpe dans le golfe de Gabès) : acheter ou vendre pendant la fermeture est une infraction. | Calendrier des fermetures par espèce, avertissement à l'achat. À valider avec la DGPA. |
| M4 | 🟢 | Circuits de distribution des produits de la pêche (loi 94-86, marchés de gros) : l'achat direct au port hors halle peut demander une autorisation. | Question pour l'avocat ; justificatif d'achat (bon de la halle) en pièce jointe. |

## 7. Vendre le logiciel : obligations de l'éditeur

| # | Niveau | Constat | Ce qu'il faut |
|---|---|---|---|
| L1 | 🔴 | **Données personnelles** (loi organique 2004-63) : l'app traite salaires, CIN, CNSS, téléphones et positions des clients et chauffeurs. Le traitement se déclare à l'**INPDP** (autorisation pour certaines données). Les serveurs sont chez **OVH en France** (runbook) : un **transfert hors de Tunisie** demande l'autorisation de l'INPDP. Seul le site public a une phrase sur la confidentialité. | Déclaration INPDP (éditeur et chaque client) ; politique de confidentialité ; contrat de sous-traitance des données avec chaque client ; décider de l'hébergement (Tunisie ou autorisation de transfert). |
| L2 | 🔴 | **Pas de cadre commercial** : aucune CGV, CGU, mentions légales, contrat de licence ou d'abonnement (SLA, responsabilité limitée sur les calculs fiscaux, réversibilité et export des données en fin de contrat). | Contrats rédigés par un avocat ; clause qui dit que les paramètres fiscaux sont sous la responsabilité du client et de son expert-comptable. |
| L3 | 🔴 | **Hébergement** : le serveur est partagé avec d'autres sites clients (runbook) ; les sauvegardes sont gardées **30 jours**. Les documents comptables se conservent **10 ans** (Code des droits et procédures fiscaux). | Production sur un serveur dédié, sauvegardes hors site (D-139 encore ouvert), rétention longue ou export annuel archivé, plan de reprise testé. |
| L4 | 🟠 | **Multi-sociétés** : le modèle a une `organization` partout, mais il n'y a ni inscription d'une nouvelle société, ni abonnement, ni facturation de l'éditeur, ni paramètres par défaut neutres (le paramétrage de départ reprend les réponses de Frutti Del Mare : 19 %, timbre, etc.). | Création d'une société avec assistant de paramétrage fiscal, abonnement, isolement des données vérifié par des tests. |
| L5 | 🟢 | Les acheteurs comparent avec Perfaxis et d'autres logiciels déjà conformes TTN. | Argument commercial : le profit par lot et l'app chauffeur hors ligne ; TTN ferme l'écart. |

## Ordre conseillé

1. **Avant tout client payant** : F1 (TTN) ou une date ferme, F2, R1, L1, L2, L3, S1 (contrat type).
2. **Avec l'expert-comptable** (une séance) : F4, F5, F7, R2, P1 à P3, E1, B6 à B9, taux 2026.
3. **Ensuite** : F6 Déclarations du mois, M1 et M2 traçabilité et froid, E3 et E4, L4 multi-sociétés.

## Sources consultées

- [Deloitte, Tunisie : principales mesures de la LF 2026](https://blog.avocats.deloitte.fr/tunisie-les-principales-mesures-de-la-loi-de-finances-pour-2026/)
- [Juridoc, résumé de la note commune n° 02-2026](https://juridoc.tn/en/paroles-experts/77/resume-note-commune-n-02-2026)
- [Chaexpert, LF 2026 : paiements en espèces](https://chaexpert.com/tunisie-lf-2026-especes-cash/)
- [Business News, transactions en espèces (février 2026)](https://businessnews.com.tn/2026/02/04/transactions-en-especes-en-tunisie-ce-que-change-reellement-la-nouvelle-reglementation-fiscale/1386603/)
- [Hesabi, facture électronique obligatoire](https://hesabi.tn/facture-electronique-tunisie-obligatoire)
- [Finco, guide de la facturation électronique 2026](https://finco.tn/blog/guide-complet-facturation-electronique-tunisie)
- [Tunisie Numérique, LF 2022 (commissionnaires, produits congelés)](https://www.tunisienumerique.com/les-bizarreries-de-la-nouvelle-loi-des-finances-2022-3-3/)
