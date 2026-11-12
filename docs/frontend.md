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
| `/` | Nouvelle conversation |
| `/c/<id>` | Conversation : messages enregistrés, réponse en direct, suppression |

Une réponse n'appartient pas à l'écran qui l'a demandée (`src/features/chat/replies.ts`) : on peut changer de conversation pendant qu'elle s'écrit, elle se termine et s'enregistre côté serveur, puis l'écran affiche les messages enregistrés, seule source de vérité.

## Design system

Jetons dans `src/styles.css` (variables CSS exposées à Tailwind), thème clair et sombre selon le réglage du système.

- **Couleurs** : fond brume (`#eef0f3`) ou ardoise nuit (`#131a24`), encre bleu-noir, un seul accent vert-de-gris (`#287363` clair, `#5fc2ae` sombre). Contrastes **calculés** (WCAG 2.x) : texte courant 11,6 à 15,6:1, texte secondaire 4,7 à 7,0:1, accent 4,54:1 minimum sur les trois fonds clairs (l'accent d'origine, `#2f7f6f`, ne faisait que 4,19:1 sur le fond et a été assombri).
- **Typographie** : Atkinson Hyperlegible Next (texte) et Mono (code), conçues pour la lisibilité ; lecture à 17 px, interligne 1,6, 68 caractères au plus par ligne.
- **Mouvement** : un seul, le monogramme qui respire pendant que l'assistant écrit ; coupé si le système demande moins d'animations.
- **Formes** : coins arrondis par niveau (bulles 16 px, champs et boutons 12 px), aucune ombre décorative.

## Sécurité de l'interface

- Réponses du modèle rendues comme données non fiables : pas de HTML brut, liens limités à `http`, `https` et `mailto`, ouverts sans référent, **aucune image distante** (une image chargerait une adresse choisie par le texte, moyen connu de faire fuiter des données). Testé (`src/components/Markdown.test.tsx`).
- Session par cookie `__Host-` (`HttpOnly`, même origine) : aucun jeton en `localStorage`. À la déconnexion, tout le cache en mémoire est vidé.
- Le service worker (`public/sw.js`) ne met **jamais** `/api/` en cache : aucune donnée personnelle sur l'appareil, seulement la coquille de l'application.
- En-têtes de sécurité (CSP, etc.) : posés par Caddy avec l'exposition publique (PR 35).

## Tests

Vitest et Testing Library sur l'application complète, contre un faux backend (`src/test/fakeApi.ts`) qui imite les routes, codes et flux SSE réels : connexion (avec et sans double authentification), premier message, Entrée et Maj+Entrée, message de secours et avertissement de budget, réponse interrompue, coupure réseau, suppression, activation du module, déconnexion. axe-core vérifie l'accessibilité des écrans de connexion et de conversation (le contraste, que jsdom ne sait pas mesurer, est calculé à part).

## Icônes

`scripts/make-icons.py` dessine les icônes (dont la version « maskable » d'Android) à partir de la géométrie du monogramme ; à relancer si l'accent change.
