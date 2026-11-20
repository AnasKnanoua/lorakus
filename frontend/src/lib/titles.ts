/**
 * Titre de conversation affiche : premiere lettre en majuscule. Le serveur reprend le debut du
 * premier message tel quel (sans appel a l'IA) ; la majuscule est une affaire d'affichage.
 */
export function displayTitle(title: string): string {
  return title.charAt(0).toLocaleUpperCase("fr") + title.slice(1);
}
