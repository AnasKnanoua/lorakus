# Frontend : l'application Lorakus

Application web installable (PWA) : l'unique interface de Lorakus, sur téléphone comme sur ordinateur (ADR 0005, ADR 0013). Code dans `frontend/`.

## Pile

React 19 et TypeScript strict, construits par Vite ; TanStack Router (routes déclarées dans `src/router.tsx`) et TanStack Query (cache des données) ; Tailwind 4 ; composants à la manière de shadcn/ui, copiés seulement quand ils servent (`src/components/ui/`), dialogues sur Radix. Le client de l'API est **généré** depuis le contrat OpenAPI du backend (`openapi.json` → `src/api/schema.d.ts`) : aucun `fetch` écrit à la main en dehors de `src/api/client.ts` (règle ESLint). La CI refuse un contrat ou un client périmés (`make openapi`).

pnpm installe les dépendances et refuse toute version publiée depuis moins de 14 jours (`minimumReleaseAge` dans `pnpm-workspace.yaml`).

## Développer

1. Une API joignable sur `localhost:8001` : la production par le tunnel (`ssh -N -L 8001:127.0.0.1:8001 lorakus-prod`) ou la pile locale (`make up`).
2. `make front-dev`, puis http://localhost:5173 (adresse `localhost` obligatoire : c'est la condition pour que le navigateur accepte le cookie de session `Secure` en HTTP).

## Écrans

| Adresse | Écran |
| --- | --- |
| `/connexion` | Connexion, avec le code de double authentification si le compte l'exige |
| `/` | Accueil : la question et le champ de saisie au centre de la zone principale (barre latérale exclue) |
| `/c/<id>` | Conversation : messages enregistrés, réponse en direct, champ de saisie en bas, suppression |
| `/memoire` | Mémoire (ADR 0039) : titre de page, propositions en tête (seulement s'il y en a), recherche (sans accents ni casse) et bouton « + » collés en haut, filtres par catégorie (à partir de deux, sur plusieurs lignes, sans compteur), souvenirs en lignes de texte groupées par catégorie repliable (toucher une ligne pour la modifier ou la supprimer), réglages et « Tout oublier » repliés en bas |

Au premier envoi depuis l'accueil, le champ de saisie **glisse** du centre vers le bas pendant que la conversation apparaît en fondu : les deux écrans donnent au champ le même nom de transition (`view-transition-name: composer`) et le routeur navigue avec les View Transitions du navigateur. Les autres changements d'écran font un fondu bref. Un navigateur sans View Transitions affiche directement le nouvel écran.

Une réponse n'appartient pas à l'écran qui l'a demandée (`src/features/chat/replies.ts`) : on peut changer de conversation pendant qu'elle s'écrit, elle se termine et s'enregistre côté serveur, puis l'écran affiche les messages enregistrés, seule source de vérité. Le serveur enregistrant le message de l'utilisateur dès le début du tour, `withoutLiveTurn` évite de l'afficher deux fois (testé).

La zone principale n'affiche rien tant qu'on ne sait pas si l'assistant est activé (sinon l'accueil apparaissait un instant avant l'écran d'activation). L'application et les tests partagent le même client de requêtes (`src/lib/queryClient.ts`) : jamais de nouvelle tentative sur une réponse définitive de l'API (4xx, module désactivé), retour à la connexion si la session expire.

## Design system : « encre de nuit et aurore »

Jetons centralisés dans `src/styles.css` (variables CSS exposées à Tailwind) ; les composants n'utilisent que leurs noms (`bg-raised`, `text-ink-muted`…), jamais une couleur en dur. Thème sombre de référence, thème clair dérivé, selon le réglage du système.

- **Couleurs** : encre de nuit bleutée (`#0b0e13`), surfaces légèrement plus claires pour la barre latérale (`surface`) et ce qui flotte (`raised` : champ de saisie, bulles, code), un seul accent, le **jade lumineux** de Lorakus (`#4fd9bd` ; `#0e7563` en clair), une pointe de violet réservée aux dégradés. Contrastes **calculés** (WCAG 2.x) avant d'écrire le code : texte 5,64:1 minimum en sombre, 4,92:1 en clair ; bordure du champ au focus 9,9:1 et 5,6:1.
- **Typographie** : Inter (variable) avec son **axe de taille optique** (`@fontsource-variable/inter/opsz.css`, `font-optical-sizing: auto`) : dessin plus serré et plus net aux tailles de titre, plus ouvert aux petites tailles, comme les polices des interfaces de référence. Formes par défaut d'Inter (sans variantes stylistiques). Lecture à 16 px, interligne 1,75, colonne de 768 px au plus. Une seule police ; le code utilise la police à chasse fixe du système.
- **L'orbe** (`components/Orb.tsx`, `.orb`) : emblème de Lorakus, une sphère jade et violet. Elle marque les réponses, l'accueil, la connexion et l'icône de l'application ; quand Lorakus réfléchit, son halo tourne et elle respire. Agrandie, elle sera le cœur du mode vocal (ROADMAP, Idées).
- **L'aurore** (`.aurora`) : deux halos de lumière diffuse, lents, derrière l'accueil et la connexion ; elle disparaît dans la conversation pour ne pas gêner la lecture.
- **Formes et profondeur** : champ de saisie flottant à 26 px d'arrondi, bulles à 22 px, code à 16 px ; une ombre douce pour ce qui flotte ; **aucune ligne de séparation** entre les zones (le champ ancré en bas repose sur un fondu).
- **Mouvement** : apparition des messages (fondu montant, 360 ms), glissement du champ (460 ms), panneau mobile (240 ms), orbe et reflet « Lorakus réfléchit ». Tout est coupé si le système demande moins d'animations.
- **Voix** : tutoiement dans toute l'interface et dans les messages de secours du backend.

### Système de design (règles pour toute nouvelle page)

Diagnostic du 2026-11-13, comparé à Gemini et Claude : textes de liste trop petits (14 px) et trop gris (`ink-muted` à 7,5:1 sur la barre latérale, lu comme un texte désactivé), lignes de 36 px trop serrées, titres de section minuscules, marque et icône d'accent en compétition avec l'action principale, page sans vrai titre, compteurs répétés trois fois, boutons et filtres plus voyants que le contenu. Les règles ci-dessous en découlent.

- **Échelle typographique** (`styles.css`, classes Tailwind) : `xs` 12 (badges), `sm` 13 (métadonnées, titres de section), `base` 15 (interface : listes, boutons), `md` 16 (champs de saisie, contenu principal), `lg` 18 (marque, titres de panneau), `xl` 22 (titres de fenêtre), `2xl` 28 (titre de page). Interlignes fixes ; approche négative à partir de `lg`. Pas de taille arbitraire (`text-[…]`) dans un nouveau composant.
- **Graisses** : 400 pour le texte, 500 pour les libellés actifs et titres de section, 600 pour les titres de page et la marque. Jamais 700.
- **Trois niveaux de texte** : `ink` (contenu), `ink-muted` (listes et descriptions, éclairci à `#b6bdc8`, 9,9:1), `ink-faint` (titres de section, métadonnées, 6,1:1). La hiérarchie vient du niveau et de la taille, pas de couleurs supplémentaires.
- **Espacements** : grille de 4 px (classes Tailwind). Marges de page 20 px sur téléphone, 24 px au-delà ; 24 px entre le titre de page et le contenu ; 20 px entre deux groupes d'une liste ; 2 px entre deux lignes d'une même liste (c'est la hauteur de ligne qui aère, pas l'écart).
- **Hauteurs** : ligne de navigation ou de liste 40 px (48 px pour une ligne de contenu à toucher), champ 44 px (40 px dans une barre d'outils), bouton 40 px (`md`) ou 32 px (`sm`), filtre 32 px.
- **Arrondis** : 8 px (petits contrôles), 12 px (champs, boutons, lignes), 16 px (cartes, panneaux), pilule (navigation, filtres, badges).
- **Boutons** (`components/ui/button.tsx`) : `primary` (jade, une seule action principale par zone), `secondary` (fond `raised`), `quiet` (sans fond), `outline`, `danger`, `danger-quiet`.
- **Hiérarchie sans décor** : pas de bordure autour des éléments d'une liste, pas de ligne de séparation ; un fond seulement pour l'action principale, l'élément actif ou ce qui attend une décision (proposition). Les icônes d'action ne se répètent pas sur chaque ligne : la ligne se touche, un crayon apparaît au survol sur ordinateur.
- **Une information, un endroit** : un compteur apparaît une fois (en-tête de groupe), jamais dans le titre, les filtres et le groupe à la fois.
- **Titre de page** dans le contenu (`2xl`, une phrase d'aide en `sm` dessous), pas dans la barre du haut.

## Champ de saisie

`features/chat/Composer.tsx`, deux variantes (`hero` au centre, `docked` en bas). Entrée envoie et Maj+Entrée va à la ligne sur ordinateur ; sur écran tactile, Entrée va à la ligne et l'envoi passe par le bouton. Pendant qu'une réponse s'écrit, on peut préparer la suite sans l'envoyer. Les emplacements `leading` et `trailing` accueilleront les futurs outils (pièce jointe, micro, choix du modèle) : rien n'y est affiché tant que la fonction n'existe pas. Sur Android, `interactive-widget=resizes-content` garde le champ au-dessus du clavier.

## Navigation

L'application doit rester aussi simple avec vingt fonctionnalités qu'avec trois. La barre latérale a trois étages fixes :

1. **Marque et actions** : le nom « Lorakus » seul (l'orbe reste sur l'accueil et la connexion), « Nouvelle conversation » sur fond `raised` (seule ligne avec un fond permanent), puis les destinations déclarées dans `src/navigation.ts`, seul endroit à modifier pour en ajouter une. Groupe `assistant` (Mémoire ; puis Aujourd'hui, Tâches, Agenda) toujours visible, cinq entrées au plus ; groupe `tools` (services secondaires, modules) dans une section repliable, absente tant qu'elle est vide. Un badge discret signale ce qui attend l'utilisateur (propositions de souvenirs).
2. **Conversations** : seule partie qui défile, groupées par ancienneté (Aujourd'hui, Hier, 7 derniers jours, 30 derniers jours, Plus ancien), 25 affichées puis « Afficher plus ».
3. **Profil** : avatar, adresse, déconnexion ; les futurs réglages et la gestion du compte iront dans ce coin, jamais dans la liste.

Lignes de 40 px en forme de pilule, texte de 15 px, icônes de 18 px ; titres de section en 13 px alignés sur les icônes ; ligne active sur fond `hover` en graisse 500 ; compte en bas sans bordure. Largeur 280 px sur ordinateur, 86 % (320 px au plus) sur téléphone. Repliable sur ordinateur (préférence d'affichage gardée dans le navigateur, aucune donnée personnelle) ; sur téléphone, panneau coulissant qui s'ouvre en glissant vers la droite sur l'écran (comme Gemini ; ignoré sur le code, les tableaux et les champs) et se ferme en le glissant vers la gauche (geste vertical ignoré : la liste défile normalement).

Tant que des propositions attendent, la barre du haut de chaque écran (sauf la page Mémoire) affiche une mention discrète « N souvenirs à confirmer », qui mène à la page.

## Mouvement

Principe : la structure reste en place, seul le contenu change. Animations courtes (120 à 300 ms), sur `transform` et `opacity` seulement (fluides à 60 images par seconde), courbe `--ease-out-soft`. Avec « réduire les animations » du système, tout s'affiche immédiatement.

- **Changement d'écran** : View Transitions du navigateur. La barre latérale (`vt-sidebar`) ne bouge pas ; la zone principale (`vt-page`) s'efface en 120 ms puis revient en glissant de 6 px. De l'accueil à la conversation, le champ de saisie glisse en plus du centre vers le bas.
- **Souvenirs** : après un ajout, une confirmation, une correction ou une suppression, `withViewTransition` (`src/lib/motion.ts`) fait glisser chaque ligne (nommée `fact-<id>`) vers sa nouvelle place.
- **Sections repliables** (`components/Collapsible.tsx`) : la hauteur s'ouvre par `grid-template-rows` (0fr vers 1fr), sans mesure ni bibliothèque ; le contenu fermé est inerte.
- **Panneau et fenêtres** : le panneau entre en 280 ms et sort en 200 ms ; les fenêtres de confirmation montent légèrement.
- **Actions d'une ligne** : visibles au survol ou au focus avec une souris, toujours visibles sur écran tactile.

## Vérification visuelle

Les écrans sont capturés dans un vrai navigateur (Chromium sans interface) contre le vrai backend et un faux fournisseur d'IA : connexion, activation, accueil, saisie, transition, réflexion, conversation, barre repliée, thème clair, sur ordinateur (1440 × 900) et téléphone (390 × 844). Ces captures ont révélé trois défauts que les tests n'avaient pas vus (écran d'activation retardé, clignotement de l'accueil, message affiché deux fois), tous corrigés et désormais testés.

## Sécurité de l'interface

- Réponses du modèle rendues comme données non fiables : pas de HTML brut, liens limités à `http`, `https` et `mailto`, ouverts sans référent, **aucune image distante** (une image chargerait une adresse choisie par le texte, moyen connu de faire fuiter des données). Testé (`src/components/Markdown.test.tsx`).
- Session par cookie `__Host-` (`HttpOnly`, même origine) : aucun jeton en `localStorage`. À la déconnexion, tout le cache en mémoire est vidé.
- Le service worker (`public/sw.js`) ne met **jamais** `/api/` en cache : aucune donnée personnelle sur l'appareil, seulement la coquille de l'application.
- En-têtes de sécurité : posés par Caddy (`infra/web/Caddyfile`, ADR 0038). CSP `script-src 'self'` : aucun script en ligne ni externe, jamais d'`eval`. Les styles en ligne sont admis (Radix). Toute nouvelle ressource externe (police, image, script) doit être ajoutée à la CSP, ou mieux, embarquée dans le build.

## Tests

Vitest et Testing Library sur l'application complète, avec le même client de requêtes que l'application, contre un faux backend (`src/test/fakeApi.ts`) qui imite les routes, codes et flux SSE réels (message enregistré dès le début du tour, réponse à la fin) : connexion (avec et sans double authentification), session expirée, premier message, message affiché une seule fois pendant l'écriture, Entrée et Maj+Entrée, message de secours et avertissement de budget, réponse interrompue, coupure réseau, suppression, activation du module, déconnexion. axe-core vérifie l'accessibilité des écrans de connexion et de conversation (le contraste, que jsdom ne sait pas mesurer, est calculé à part).

## Icônes

`scripts/make-icons.py` dessine l'orbe sur fond encre de nuit (dont la version « maskable », qui reste entière dans la découpe ronde d'Android) ; à relancer si l'accent change.
