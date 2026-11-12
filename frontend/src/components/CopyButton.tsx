import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

/** Copie un texte ; confirme deux secondes (visuellement et pour les lecteurs d'écran). */
export function CopyButton({
  text,
  label = "Copier",
  className,
  showLabel = false,
}: {
  text: string;
  label?: string;
  className?: string;
  showLabel?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => {
      setCopied(false);
    }, 2000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // Presse-papiers refusé (contexte non sécurisé, permission) : rien à afficher de plus.
    }
  }

  const Icon = copied ? Check : Copy;
  return (
    <>
      <Button
        variant="quiet"
        size={showLabel ? "sm" : "icon-sm"}
        aria-label={showLabel ? undefined : label}
        onClick={() => void copy()}
        className={cn(showLabel && "h-7 px-2 text-xs", className)}
      >
        <Icon aria-hidden="true" className={cn(copied && "text-accent")} />
        {showLabel && <span>{copied ? "Copié" : label}</span>}
      </Button>
      <span role="status" className="sr-only">
        {copied ? "Copié dans le presse-papiers" : ""}
      </span>
    </>
  );
}
