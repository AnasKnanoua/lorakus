import { useId, useState } from "react";

import { ApiError, errorCode } from "@/api/client";
import { CATEGORIES, CATEGORY_LABELS, type Category } from "@/api/memory";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export const MAX_FACT_CHARS = 300;

/** Saisie d'un fait : texte d'une ligne et categorie. */
export function FactEditor({
  initialContent = "",
  initialCategory = "preference",
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initialContent?: string;
  initialCategory?: Category;
  submitLabel: string;
  onSubmit: (content: string, category: Category) => Promise<void>;
  onCancel?: () => void;
}) {
  const [content, setContent] = useState(initialContent);
  const [category, setCategory] = useState<Category>(initialCategory);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = useId();
  const text = content.trim();

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!text) {
          return;
        }
        setBusy(true);
        setError(null);
        onSubmit(text, category)
          .catch((cause: unknown) => {
            setError(messageFor(cause));
          })
          .finally(() => {
            setBusy(false);
          });
      }}
    >
      <label htmlFor={`${id}-text`} className="sr-only">
        Texte du souvenir
      </label>
      <Input
        id={`${id}-text`}
        value={content}
        maxLength={MAX_FACT_CHARS}
        placeholder="Ex. : Préfère réviser le soir"
        onChange={(event) => {
          setContent(event.target.value);
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`${id}-category`} className="sr-only">
          Catégorie
        </label>
        <select
          id={`${id}-category`}
          value={category}
          onChange={(event) => {
            setCategory(event.target.value as Category);
          }}
          className="h-9 rounded-lg border border-line bg-raised px-2 text-sm text-ink"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>
        <div className="flex-1" />
        {onCancel && (
          <Button variant="quiet" size="sm" onClick={onCancel}>
            Annuler
          </Button>
        )}
        <Button type="submit" size="sm" disabled={busy || !text}>
          {submitLabel}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </form>
  );
}

export function messageFor(cause: unknown): string {
  if (!(cause instanceof ApiError)) {
    return "L'opération a échoué. Réessaie.";
  }
  const code = errorCode(cause.detail);
  if (code === "duplicate") {
    return "Ce souvenir existe déjà.";
  }
  if (code === "limit") {
    return "Tu as atteint le nombre maximal de souvenirs : supprimes-en d'abord.";
  }
  if (cause.status === 422) {
    return "Texte refusé : une seule ligne, 300 caractères au plus.";
  }
  return "L'opération a échoué. Réessaie.";
}
