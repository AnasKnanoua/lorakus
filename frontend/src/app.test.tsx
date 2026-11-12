/**
 * Parcours complets de l'application, contre le faux backend (src/test/fakeApi.ts).
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { installFakeApi } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

/** Titre de l'accueil (espace insecable avant « ? », typographie francaise). */
const HOME_TITLE = /^Que puis-je faire pour toi aujourd'hui\s\?$/u;

afterEach(() => {
  vi.unstubAllGlobals();
});

async function signIn(password = "un mot de passe assez long") {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Adresse e-mail"), "anas@example.com");
  await user.type(screen.getByLabelText("Mot de passe"), password);
  await user.click(screen.getByRole("button", { name: "Se connecter" }));
  return user;
}

/** Violations d'accessibilite detectees par axe-core (le contraste est calcule a part). */
async function a11yViolations(container: HTMLElement): Promise<string[]> {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return results.violations.map((v) => `${v.id} : ${v.help}`);
}

describe("connexion", () => {
  it("sans session, affiche la connexion puis l'accueil une fois connecte", async () => {
    installFakeApi();
    renderApp("/");

    await signIn();

    expect(await screen.findByRole("heading", { name: HOME_TITLE })).toBeVisible();
  });

  it("refuse un mauvais mot de passe avec un message clair", async () => {
    installFakeApi();
    renderApp("/connexion");

    await signIn("mauvais mot de passe");

    expect(await screen.findByRole("alert")).toHaveTextContent("Adresse ou mot de passe incorrect.");
  });

  it("demande le code de double authentification quand le compte l'exige", async () => {
    const api = installFakeApi({ secondFactor: "123456" });
    renderApp("/connexion");

    const user = await signIn();
    await user.type(await screen.findByLabelText("Code de double authentification"), "123456");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByRole("heading", { name: HOME_TITLE })).toBeVisible();
    const last = api.requests.filter((r) => r.path === "/api/v1/auth/login").at(-1);
    expect(last?.body).toMatchObject({ second_factor: "123456" });
  });

  it("une session expiree pendant l'utilisation ramene a la connexion", async () => {
    const api = installFakeApi({ loggedIn: true });
    const { router } = renderApp("/");
    await screen.findByLabelText("Message à Lorakus");

    api.loggedIn = false; // la session expire cote serveur
    await router.navigate({ to: "/c/$conversationId", params: { conversationId: "inconnue" } });

    expect(await screen.findByLabelText("Adresse e-mail")).toBeVisible();
  });

  it("l'ecran de connexion n'a pas de defaut d'accessibilite detectable", async () => {
    installFakeApi();
    const { container } = renderApp("/connexion");
    await screen.findByLabelText("Adresse e-mail");

    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe("conversation", () => {
  it("premier message : la reponse s'affiche puis la conversation apparait dans la liste", async () => {
    const api = installFakeApi({ loggedIn: true });
    renderApp("/");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Message à Lorakus"), "Quel jour sommes-nous ?");
    await user.click(screen.getByRole("button", { name: "Envoyer" }));

    const log = await screen.findByRole("log");
    await waitFor(() => {
      expect(log).toHaveTextContent("Bonjour Anas.");
    });
    expect(log).toHaveTextContent("Quel jour sommes-nous ?");
    const nav = screen.getAllByRole("navigation", { name: "Conversations" })[0];
    expect(nav).toBeDefined();
    expect(await within(nav as HTMLElement).findByRole("link", { name: "Quel jour sommes-nous ?" })).toBeVisible();
    const sent = api.requests.find((r) => r.path.endsWith("/messages"));
    expect(sent?.body).toEqual({ content: "Quel jour sommes-nous ?" });
  });

  it("pendant l'ecriture, le message envoye n'apparait qu'une fois", async () => {
    let release: () => void = () => undefined;
    const api = installFakeApi({
      loggedIn: true,
      holdReply: new Promise<void>((resolve) => {
        release = resolve;
      }),
    });
    renderApp("/");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Message à Lorakus"), "Un seul exemplaire{Enter}");
    const log = await screen.findByRole("log");
    await waitFor(() => {
      expect(log).toHaveTextContent("Bonjour Anas.");
    });
    // La conversation a ete chargee alors que le serveur avait deja enregistre le message.
    expect(api.conversations.values().next().value?.messages).toHaveLength(1);
    expect(within(log).getAllByText("Un seul exemplaire")).toHaveLength(1);

    release();
    await waitFor(() => {
      expect(screen.getByLabelText("Message à Lorakus")).toBeEnabled();
    });
    await waitFor(() => {
      expect(within(log).getAllByText("Un seul exemplaire")).toHaveLength(1);
    });
  });

  it("Entree envoie, Maj+Entree va a la ligne", async () => {
    const api = installFakeApi({ loggedIn: true });
    renderApp("/");
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Message à Lorakus");

    await user.type(box, "ligne un{Shift>}{Enter}{/Shift}ligne deux{Enter}");

    await waitFor(() => {
      expect(api.requests.find((r) => r.path.endsWith("/messages"))?.body).toEqual({
        content: "ligne un\nligne deux",
      });
    });
  });

  it("affiche le message de secours et l'avertissement de budget", async () => {
    installFakeApi({
      loggedIn: true,
      nextReply: {
        chunks: ["Mon modèle de langage est indisponible pour le moment."],
        status: "fallback",
        budgetWarning: true,
      },
    });
    renderApp("/");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Message à Lorakus"), "Bonjour{Enter}");

    expect(await screen.findByText("Mon modèle de langage est indisponible pour le moment.")).toBeVisible();
    expect(await screen.findByRole("status")).toHaveTextContent("80 % du budget");
  });

  it("signale une reponse interrompue", async () => {
    installFakeApi({ loggedIn: true, nextReply: { chunks: ["Il était une"], status: "interrupted" } });
    renderApp("/");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Message à Lorakus"), "Raconte{Enter}");

    expect(await screen.findByText("Réponse interrompue.")).toBeVisible();
  });

  it("une coupure reseau est expliquee sans perdre la conversation", async () => {
    installFakeApi({ loggedIn: true, failNextSend: true });
    renderApp("/");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Message à Lorakus"), "Bonjour{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("La réponse n'a pas pu être reçue.");
    expect(screen.getByLabelText("Message à Lorakus")).toBeEnabled();
  });

  it("supprime une conversation apres confirmation", async () => {
    const api = installFakeApi({ loggedIn: true });
    renderApp("/");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Message à Lorakus"), "A supprimer{Enter}");
    await screen.findByText("Bonjour Anas.");

    await user.click(screen.getByRole("button", { name: "Supprimer la conversation" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Supprimer la conversation" }));

    expect(await screen.findByRole("heading", { name: HOME_TITLE })).toBeVisible();
    expect(api.conversations.size).toBe(0);
  });

  it("propose d'activer l'assistant quand le module est desactive", async () => {
    const api = installFakeApi({ loggedIn: true, assistantEnabled: false });
    renderApp("/");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Activer l'assistant" }));

    expect(await screen.findByRole("heading", { name: HOME_TITLE })).toBeVisible();
    expect(api.assistantEnabled).toBe(true);
  });

  it("la deconnexion ramene a l'ecran de connexion", async () => {
    installFakeApi({ loggedIn: true });
    renderApp("/");
    const user = userEvent.setup();

    const buttons = await screen.findAllByRole("button", { name: "Se déconnecter" });
    await user.click(buttons[0] as HTMLElement);

    expect(await screen.findByLabelText("Adresse e-mail")).toBeVisible();
  });

  it("l'ecran de conversation n'a pas de defaut d'accessibilite detectable", async () => {
    installFakeApi({ loggedIn: true });
    const { container } = renderApp("/");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Message à Lorakus"), "Bonjour{Enter}");
    await screen.findByText("Bonjour Anas.");

    expect(await a11yViolations(container)).toEqual([]);
  });
});
