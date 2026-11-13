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
| `/memoire` | Mémoire (ADR 0039) : propositions à confirmer, corriger ou refuser (avec l'extrait du message cité), souvenirs confirmés par catégorie, ajout, réglage des propositions, « Tout oublier » avec ré-authentification |

Au premier envoi depuis l'accueil, le champ de saisie **glisse** du centre vers le bas pendant que la conversation apparaît en fondu : les deux écrans donnent au champ le même nom de transition (`view-transition-name: composer`) et le routeur navigue avec les View Transitions du navigateur. Les autres changements d'écran font un fondu bref. Un navigateur sans View Transitions affiche directement le nouvel écran.

Une réponse n'appartient pas à l'écran qui l'a demandée (`src/features/chat/replies.ts`) : on peut changer de conversation pendant qu'elle s'écrit, elle se termine et s'enregistre côté serveur, puis l'écran affiche les messages enregistrés, seule source de vérité. Le serveur enregistrant le message de l'utilisateur dès le début du tour, `withoutLiveTurn` évite de l'afficher deux fois (testé).

La zone principale n'affiche rien tant qu'on ne sait pas si l'assistant est activé (sinon l'accueil apparaissait un instant avant l'écran d'activation). L'application et les tests partagent le même client de requêtes (`src/lib/queryClient.ts`) : jamais de nouvelle tentative sur une réponse définitive de l'API (4xx, module désactivé), retour à la connexion si la session expire.

## Design system : « encre de nuit et aurore »

Jetons centralisés dans `src/styles.css` (variables CSS exposées à Tailwind) ; les composants n'utilisent que leurs noms (`bg-raised`, `text-ink-muted`…), jamais une couleur en dur. Thème sombre de référence, thème clair dérivé, selon le réglage du système.

- **Couleurs** : encre de nuit bleutée (`#0b0e13`), surfaces légèrement plus claires pour la barre latérale (`surface`) et ce qui flotte (`raised` : champ de saisie, bulles, code), un seul accent, le **jade lumineux** de Lorakus (`#4fd9bd` ; `#0e7563` en clair), une pointe de violet réservée aux dégradés. Contrastes **calculés** (WCAG 2.x) avant d'écrire le code : texte 5,64:1 minimum en sombre, 4,92:1 en clair ; bordure du champ au focus 9,9:1 et 5,6:1.
- **Typographie** : Inter (variable), la meilleure alternative libre à la police de ChatGPT (propriétaire) ; lecture à 16 px, interligne 1,75, colonne de 768 px au plus ; titres en graisse 500 à 600, approche resserrée. Une seule police ; le code utilise la police à chasse fixe du système (rien à télécharger).
- **L'orbe** (`components/Orb.tsx`, `.orb`) : emblème de Lorakus, une sphère jade et violet. Elle marque les réponses, l'accueil, la connexion et l'icône de l'application ; quand Lorakus réfléchit, son halo tourne et elle respire. Agrandie, elle sera le cœur du mode vocal (ROADMAP, Idées).
- **L'aurore** (`.aurora`) : deux halos de lumière diffuse, lents, derrière l'accueil et la connexion ; elle disparaît dans la conversation pour ne pas gêner la lecture.
- **Formes et profondeur** : champ de saisie flottant à 26 px d'arrondi, bulles à 22 px, code à 16 px ; une ombre douce pour ce qui flotte ; **aucune ligne de séparation** entre les zones (le champ ancré en bas repose sur un fondu).
- **Mouvement** : apparition des messages (fondu montant, 360 ms), glissement du champ (460 ms), panneau mobile (240 ms), orbe et reflet « Lorakus réfléchit ». Tout est coupé si le système demande moins d'animations.
- **Voix** : tutoiement dans toute l'interface et dans les messages de secours du backend.

## Champ de saisie

`features/chat/Composer.tsx`, deux variantes (`hero` au centre, `docked` en bas). Entrée envoie et Maj+Entrée va à la ligne sur ordinateur ; sur écran tactile, Entrée va à la ligne et l'envoi passe par le bouton. Pendant qu'une réponse s'écrit, on peut préparer la suite sans l'envoyer. Les emplacements `leading` et `trailing` accueilleront les futurs outils (pièce jointe, micro, choix du modèle) : rien n'y est affiché tant que la fonction n'existe pas. Sur Android, `interactive-widget=resizes-content` garde le champ au-dessus du clavier.

## Barre latérale

Marque, « Nouvelle conversation » (icône jade), « Mémoire » (avec le nombre de propositions en attente), conversations récentes (titre complet au survol), profil et déconnexion. Repliable sur ordinateur (préférence d'affichage gardée dans le navigateur, aucune donnée personnelle) ; sur téléphone, panneau coulissant par-dessus l'écran.

Tant que des propositions attendent, la barre du haut de chaque écran (sauf la page Mémoire) affiche une mention discrète « N souvenirs à confirmer », qui mène à la page.

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
