/**
 * Mes donnees (PR 41) : export complet et suppression de toutes les conversations.
 * Les deux exigent une preuve d'identite recente : "reauth" demande de la redonner.
 */
import { ApiError, api } from "./client";

export interface ExportFile {
  blob: Blob;
  filename: string;
}

const DEFAULT_FILENAME = "lorakus-export.json";

/** Nom du fichier annonce par le serveur (Content-Disposition), sans chemin. */
export function filenameFrom(disposition: string | null): string {
  const match = /filename="([^"/\\]+)"/.exec(disposition ?? "");
  return match?.[1] ?? DEFAULT_FILENAME;
}

/** Telecharge l'export ; "reauth" si la preuve d'identite date de plus de 10 minutes. */
export async function exportMyData(): Promise<ExportFile | "reauth"> {
  const { data, response, error } = await api.GET("/api/v1/data/export", { parseAs: "blob" });
  if (response.status === 403) {
    return "reauth";
  }
  if (!response.ok || data === undefined) {
    throw new ApiError(response.status, error);
  }
  return { blob: data, filename: filenameFrom(response.headers.get("content-disposition")) };
}

/** Supprime toutes les conversations ; renvoie leur nombre, ou "reauth". */
export async function deleteAllConversations(): Promise<number | "reauth"> {
  const { data, response, error } = await api.DELETE("/api/v1/assistant/conversations");
  if (response.status === 403) {
    return "reauth";
  }
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data.deleted;
}

/** Enregistre un fichier sur l'appareil, par un lien temporaire (rien ne part ailleurs). */
export function saveFile({ blob, filename }: ExportFile): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
  // Apres le clic : le navigateur a deja pris le fichier.
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}
