import { useEffect, useState } from "react";

/**
 * Valeur stabilisee : ne change qu'apres `delay` ms sans nouvelle frappe. Evite une requete au
 * serveur par lettre tapee (recherche par le sens de la memoire, PR 37b).
 */
export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSettled(value);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);
  return settled;
}
