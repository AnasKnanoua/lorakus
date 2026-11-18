# Avant le premier client

Lorakus est aujourd'hui à usage personnel (un seul compte, le propriétaire). Cette liste rassemble ce qu'il faut faire **avant** d'ouvrir un compte à quelqu'un d'autre, payant ou non. Rien de tout cela n'est commencé : la conception est gelée jusqu'à la v0.5 (ROADMAP, « Idées »). Rédigée à la clôture de la phase 3 (PR 41, 2026-11-18) ; à revoir au moment de décider.

Ce n'est pas un avis juridique : pour le RGPD, le contrat et l'entité, faire valider par un juriste ou un service d'accompagnement (CNIL, incubateur d'école).

## 1. RGPD

- **Registre des traitements** : un traitement par finalité (compte et authentification, conversations, mémoire, appels au modèle, journaux et traces, sauvegardes), avec base légale (contrat pour le service ; consentement explicite pour toute donnée de santé, RGPD art. 9, phase 10), durées de conservation (SECURITY.md §10) et destinataires.
- **Contrats de sous-traitance (art. 28)** avec chaque sous-traitant : Anthropic (conditions commerciales et DPA de l'API), hébergeur, Backblaze (sauvegardes chiffrées, illisibles pour lui), healthchecks.io (aucune donnée personnelle), GitHub (code seulement, aucune donnée d'utilisateur).
- **Analyse d'impact (AIPD)** : assistant qui retient des souvenirs, profil comportemental possible, puis santé et usage du téléphone : une AIPD est très probablement obligatoire avant d'ouvrir ces modules à d'autres personnes.
- **Transferts hors UE** : Anthropic traite les requêtes aux États-Unis et **ne propose pas de résidence des données dans l'UE** pour l'API (à revérifier le jour venu). Il faut donc des clauses contractuelles types, une évaluation du transfert et une information claire de l'utilisateur ; ou un fournisseur européen (§3).
- **Droits des personnes** : l'export complet et la suppression des conversations existent (PR 41, `/donnees`), « Tout oublier » aussi (PR 36). Il manque la **suppression du compte** (§5) et une procédure écrite pour répondre sous un mois.
- **Information** : politique de confidentialité courte et lisible (ce qui part chez le fournisseur d'IA, ce qui reste sur le serveur, durées), mentions légales.

## 2. Hébergement

Oracle Always Free n'offre **aucun engagement de disponibilité** et peut récupérer des ressources ; acceptable pour un usage personnel, pas pour un service vendu.

- Passer sur un serveur payant ARM avec engagement de disponibilité, dans l'UE : **Hetzner CAX21** (4 vCPU, 8 Go) ou **netcup** (ARM, Allemagne). Mesuré le 2026-11-14 : 2,4 Go utilisés sur 5,6 avec toute la pile, donc 8 Go laissent de la marge pour quelques utilisateurs.
- Garder le même `deploy.sh` (Compose) : la migration est une restauration de sauvegarde (`docs/runbooks/restore.md`) puis un changement de DNS.
- Sentinelle externe, sauvegardes hors hébergeur et test de restauration mensuel : déjà en place, à garder.

## 3. Fournisseur d'IA européen

Ajouter un adaptateur derrière le port `AIProvider` (ADR 0006, 0007) : **Mistral** (API hébergée dans l'UE) ou **Scaleway Generative APIs** (modèles ouverts, Paris). Il suffit d'un adaptateur et d'une ligne dans `routing.toml` ; les modules ne changent pas. Avant de basculer : passer le banc d'évaluation (`model-eval.yml`) sur ce fournisseur, avec les mêmes objectifs (100 % *security*, 80 % *quality*), et comparer coût et latence aux mesures de production (0,28 millième de dollar et 1,6 s par appel avec Haiku 5.5).

## 4. « Pourquoi cette réponse ? »

La trace sert aujourd'hui au propriétaire, qui est aussi l'exploitant. Pour un client :

- **garder pour tous** : souvenirs utilisés, outils et cartes, spécialistes consultés et classes de données transmises (c'est l'explication qui lui est due) ;
- **réserver au rôle `owner`** : modèle, version du prompt, identifiant de trace OpenTelemetry et coût (détails d'exploitation, et le coût n'a pas de sens pour un abonné).

Changement limité à `TraceOut` (route du module `assistant`) et à l'interface, avec un test par rôle.

## 5. Suppression du compte

Route avec preuve d'identité récente et double confirmation : suppression de l'utilisateur (les clés étrangères en cascade emportent ses données), révocation des sessions et des clés, entrée minimale au journal (identifiant seulement), purge des sauvegardes à l'échéance de leur rétention (le dire dans la politique de confidentialité). Proposer l'export juste avant.

## 6. Notifications

Web Push en canal principal (proposé le 2026-11-14, ROADMAP « Idées ») : contenu chiffré de bout en bout, contrairement à Telegram. À trancher en P5 (révision de l'ADR 0035).

## 7. Entité juridique

Encaisser exige une structure (micro-entreprise pour commencer, ou société), un compte professionnel, des conditions générales de vente et d'utilisation, et la facturation (Stripe, ROADMAP « Idées »). Le crédit Azure for Students et toute offre étudiante sont à quitter avant (usage non commercial).

## 8. Transparence : on parle à une IA

Dire clairement, dans l'interface et les conditions d'utilisation, que l'assistant est une IA et que ses réponses peuvent être fausses (obligation de transparence du règlement européen sur l'IA, art. 50, applicable aux systèmes qui dialoguent avec des personnes). Une mention discrète sous le champ de saisie et dans l'accueil suffit.

## 9. Sécurité avant la vente

Revue de sécurité complète (ROADMAP, « Idées ») : prise de contrôle de compte, abus de l'API payante (plafonds par client), isolation à plusieurs utilisateurs réels, ZAP complet sur le staging, corpus d'injections étendu aux nouveaux outils.
