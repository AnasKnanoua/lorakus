import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

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
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
