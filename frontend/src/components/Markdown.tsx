import type { ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CopyButton } from "./CopyButton";

/** Noeud de l'arbre HTML produit par react-markdown (forme minimale utilisee ici). */
interface HastNode {
  type: string;
  value?: string;
  properties?: { className?: unknown };
  children?: HastNode[];
}

function textOf(node: HastNode | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(textOf).join("");
}

/** Bloc de code : en-tete discret (langage, copier) sur un panneau sobre. */
function CodeBlock({ node, children }: { node: HastNode | undefined; children: ReactNode }) {
  const code = node?.children?.find((child) => child.type === "element");
  const classes = code?.properties?.className;
  const language = Array.isArray(classes)
    ? classes
        .map(String)
        .find((c) => c.startsWith("language-"))
        ?.slice("language-".length)
    : undefined;
  const text = textOf(code).replace(/\n$/, "");
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-raised">
      <div className="flex h-9 items-center justify-between pr-1.5 pl-4 text-xs text-ink-faint">
        <span>{language ?? "code"}</span>
        <CopyButton text={text} label="Copier" showLabel />
      </div>
      <pre className="!pt-1">{children}</pre>
    </div>
  );
}

/**
 * Rendu Markdown des reponses. Le texte vient d'un modele : il est traite comme non fiable.
 * - Aucun HTML brut (react-markdown l'ignore sans le plugin rehype-raw, jamais ajoute).
 * - Liens limites a http, https et mailto ; ouverts ailleurs, sans referent.
 * - Aucune image distante : elle ferait sortir une requete vers un tiers (fuite possible).
 */
function safeUrl(url: string): string {
  const cleaned = defaultUrlTransform(url);
  return /^(https?:|mailto:)/i.test(cleaned) ? cleaned : "";
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-lorakus">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeUrl}
        components={{
          a: ({ href, children }) =>
            href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          img: ({ alt }) => <span>{alt ? `[image : ${alt}]` : "[image]"}</span>,
          pre: ({ node, children }) => <CodeBlock node={node}>{children}</CodeBlock>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
