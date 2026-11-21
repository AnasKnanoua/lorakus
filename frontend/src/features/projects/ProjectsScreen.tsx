import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Check, FolderPlus, Plus, Trash2 } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import {
  ProjectsDisabledError,
  ProjectsRefusedError,
  addIdea,
  addProject,
  addProjectTask,
  archiveIdea,
  completeProjectTask,
  enableProjects,
  finishProject,
  removeIdea,
  removeProject,
  removeProjectTask,
  type Idea,
  type Project,
  type ProjectTask,
} from "@/api/projects";
import { Collapsible } from "@/components/Collapsible";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/features/chat/ConfirmDialog";
import { TopBar } from "@/features/chat/layout";
import { cn } from "@/lib/cn";
import { duration, hoursToMinutes, localDay, longDate } from "@/lib/format";
import { ideasQuery, projectsQuery } from "@/lib/queries";

function message(error: unknown): string | null {
  if (!error) return null;
  return error instanceof ProjectsRefusedError ? error.message : "L'opération a échoué. Réessaie.";
}

/** « 1 tâche ouverte », « 3 tâches ouvertes ». */
function plural(count: number, one: string, many: string): string {
  return `${String(count)} ${count > 1 ? many : one}`;
}

/**
 * Page « Projets » (PR 51, docs/frontend.md) : une boîte d'idées où tout se note en une ligne,
 * les projets en cours avec leurs tâches, et ceux qui dorment depuis deux semaines. Chaque
 * tâche de projet a sa tâche dans « Ma journée » : la terminer ici la termine là-bas, et
 * inversement.
 */
export function ProjectsScreen() {
  const projects = useQuery(projectsQuery("active"));
  const ideas = useQuery(ideasQuery("inbox"));
  const disabled = projects.error instanceof ProjectsDisabledError || ideas.error instanceof ProjectsDisabledError;
  return (
    <>
      <TopBar />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="page-enter mx-auto flex max-w-2xl flex-col px-5 pb-16 sm:px-6">
          <header className="pt-2 pb-6">
            <h1 className="text-2xl font-semibold">Projets</h1>
            <p className="mt-1 text-sm text-ink-faint">
              Tes idées, tes projets en cours et leurs tâches. Chaque tâche apparaît aussi dans ta journée.
            </p>
          </header>
          {disabled ? (
            <EnableProjects />
          ) : projects.isPending || ideas.isPending ? (
            <p className="text-sm text-ink-faint" aria-busy="true">
              Chargement…
            </p>
          ) : projects.isError || ideas.isError ? (
            <p role="alert" className="text-danger">
              Impossible de charger tes projets. Réessaie dans un instant.
            </p>
          ) : (
            <>
              <IdeaBox items={ideas.data} />
              <ActiveProjects items={projects.data} />
              <NewProject />
              <DoneProjects />
              <ArchivedIdeas />
            </>
          )}
        </div>
      </div>
    </>
  );
}

function useRefresh() {
  const queryClient = useQueryClient();
  // « Ma journee » n'a rien a relire ici : elle se recharge a chaque ouverture.
  return () => queryClient.invalidateQueries({ queryKey: ["projects"] });
}

function EnableProjects() {
  const refresh = useRefresh();
  const enable = useMutation({ mutationFn: enableProjects, onSuccess: refresh });
  return (
    <section aria-labelledby="enable-title" className="rounded-2xl bg-raised p-5">
      <h2 id="enable-title" className="text-base font-medium">
        Active les projets
      </h2>
      <p className="mt-1 text-sm text-ink-muted">
        Une seule fois. Tu pourras noter tes idées, suivre tes projets et leurs tâches, ici ou en le
        disant à Lorakus.
      </p>
      <Button
        className="mt-4"
        size="sm"
        disabled={enable.isPending}
        onClick={() => {
          enable.mutate();
        }}
      >
        Activer
      </Button>
      {enable.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          L'activation a échoué. Réessaie dans un instant.
        </p>
      )}
    </section>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-sm text-ink-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

function Alert({ text }: { text: string | null }) {
  return text ? (
    <p role="alert" className="text-sm text-danger">
      {text}
    </p>
  ) : null;
}

// ------------------------------------------------------------------- idees
function IdeaBox({ items }: { items: Idea[] }) {
  const refresh = useRefresh();
  const id = useId();
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => addIdea(text),
    onSuccess: async () => {
      setText("");
      await refresh();
    },
  });
  return (
    <section aria-labelledby={`${id}-title`} className="pb-6">
      <h2 id={`${id}-title`} className="px-3 pb-1 text-sm font-medium text-ink-faint">
        Boîte d'idées
      </h2>
      <form
        className="flex flex-col gap-2 px-3 pb-2"
        onSubmit={(event) => {
          event.preventDefault();
          add.mutate();
        }}
      >
        <label htmlFor={id} className="sr-only">
          Nouvelle idée
        </label>
        <div className="flex gap-2">
          <Input
            id={id}
            value={text}
            maxLength={500}
            required
            autoComplete="off"
            placeholder="Une idée, en une ligne"
            onChange={(e) => {
              setText(e.target.value);
            }}
          />
          <Button type="submit" variant="secondary" className="h-11" disabled={add.isPending || !text.trim()}>
            <Plus aria-hidden="true" />
            Noter
          </Button>
        </div>
        <Alert text={message(add.error)} />
      </form>
      {items.length === 0 ? (
        <p className="px-3 text-sm text-ink-faint">
          Rien en attente. Note ici ce qui te passe par la tête : tu décideras plus tard.
        </p>
      ) : (
        <ul aria-labelledby={`${id}-title`} className="flex flex-col gap-0.5">
          {items.map((idea) => (
            <IdeaLine key={idea.id} idea={idea} />
          ))}
        </ul>
      )}
    </section>
  );
}

function IdeaLine({ idea }: { idea: Idea }) {
  const refresh = useRefresh();
  const [promoting, setPromoting] = useState(false);
  const [removing, setRemoving] = useState(false);
  const archive = useMutation({ mutationFn: () => archiveIdea(idea.id), onSuccess: refresh });
  if (promoting) {
    return (
      <li className="rounded-2xl bg-raised p-4">
        <ProjectForm
          legend="En faire un projet"
          quote={idea.text}
          ideaId={idea.id}
          onCancel={() => {
            setPromoting(false);
          }}
        />
      </li>
    );
  }
  return (
    <li className="flex min-h-12 items-center gap-1 rounded-xl pr-1 pl-3 hover:bg-hover">
      <p className="min-w-0 flex-1 py-2.5 text-base break-words text-ink">{idea.text}</p>
      <Button
        variant="quiet"
        size="icon"
        aria-label={`Faire un projet de l'idée « ${idea.text} »`}
        title="En faire un projet"
        onClick={() => {
          setPromoting(true);
        }}
      >
        <FolderPlus aria-hidden="true" />
      </Button>
      <Button
        variant="quiet"
        size="icon"
        aria-label={`Archiver l'idée « ${idea.text} »`}
        title="Archiver"
        disabled={archive.isPending}
        onClick={() => {
          archive.mutate();
        }}
      >
        <Archive aria-hidden="true" />
      </Button>
      <Button
        variant="danger-quiet"
        size="icon"
        aria-label={`Supprimer l'idée « ${idea.text} »`}
        title="Supprimer"
        onClick={() => {
          setRemoving(true);
        }}
      >
        <Trash2 aria-hidden="true" />
      </Button>
      {archive.isError && <span className="sr-only" role="alert">L'archivage a échoué. Réessaie.</span>}
      <ConfirmDialog
        open={removing}
        onOpenChange={setRemoving}
        title="Supprimer cette idée ?"
        description="Elle disparaît pour de bon. Pour la garder sans l'avoir sous les yeux, archive-la."
        confirmLabel="Supprimer"
        onConfirm={async () => {
          await removeIdea(idea.id);
          await refresh();
        }}
      />
    </li>
  );
}

function ArchivedIdeas() {
  const archived = useQuery(ideasQuery("archived"));
  if (!archived.data || archived.data.length === 0) return null;
  return (
    <Collapsible
      title="Idées archivées"
      count={archived.data.length}
      defaultOpen={false}
      className="mt-2"
      headerClassName="px-3"
    >
      <ul aria-label="Idées archivées" className="flex flex-col gap-0.5 pb-3">
        {archived.data.map((idea) => (
          <li key={idea.id} className="flex min-h-12 items-center rounded-xl px-3 py-2 text-base text-ink-muted">
            {idea.text}
          </li>
        ))}
      </ul>
    </Collapsible>
  );
}

// ---------------------------------------------------------------- projets
/** Création d'un projet, seul ou depuis une idée (l'idée devient sa description). */
function ProjectForm({
  legend,
  quote,
  ideaId,
  onCancel,
}: {
  legend: string;
  /** Texte de l'idée d'origine, rappelé au-dessus du nom. */
  quote?: string;
  ideaId?: string;
  onCancel?: () => void;
}) {
  const refresh = useRefresh();
  const id = useId();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const add = useMutation({
    // Depuis une idee, pas de champ description : le serveur reprend le texte de l'idee.
    mutationFn: () => addProject({ name, description: description.trim() || null, idea_id: ideaId ?? null }),
    // Depuis une idee, la ligne disparait avec elle : rien d'autre a fermer.
    onSuccess: async () => {
      setName("");
      setDescription("");
      await refresh();
    },
  });
  return (
    <form
      aria-labelledby={`${id}-legend`}
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate();
      }}
    >
      <h2 id={`${id}-legend`} className="text-base font-medium">
        {legend}
      </h2>
      {quote && <p className="text-sm break-words text-ink-muted">« {quote} »</p>}
      <Field id={`${id}-name`} label="Nom du projet">
        <Input
          id={`${id}-name`}
          value={name}
          maxLength={80}
          required
          autoComplete="off"
          placeholder="Portfolio"
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </Field>
      {!ideaId && (
        <Field id={`${id}-description`} label="Description (facultatif)">
          <Input
            id={`${id}-description`}
            value={description}
            maxLength={500}
            autoComplete="off"
            placeholder="Ce que tu veux obtenir"
            onChange={(e) => {
              setDescription(e.target.value);
            }}
          />
        </Field>
      )}
      <Alert text={message(add.error)} />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={add.isPending || !name.trim()}>
          Créer le projet
        </Button>
        {onCancel && (
          <Button variant="quiet" size="sm" onClick={onCancel}>
            Annuler
          </Button>
        )}
      </div>
    </form>
  );
}

function NewProject() {
  return (
    <section className="mt-2 rounded-2xl bg-raised p-5">
      <ProjectForm legend="Nouveau projet" />
    </section>
  );
}

function ActiveProjects({ items }: { items: Project[] }) {
  const id = useId();
  if (items.length === 0) {
    return <p className="px-3 pb-6 text-base text-ink-muted">Aucun projet en cours.</p>;
  }
  return (
    <section aria-labelledby={id} className="pb-6">
      <h2 id={id} className="px-3 pb-2 text-sm font-medium text-ink-faint">
        En cours
      </h2>
      <ul aria-labelledby={id} className="flex flex-col gap-3">
        {items.map((project) => (
          <ProjectCard key={project.id} project={project} />
        ))}
      </ul>
    </section>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const refresh = useRefresh();
  const [finishing, setFinishing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const total = project.open_tasks + project.done_tasks;
  const open = project.tasks.filter((t) => t.status === "open");
  const titleId = useId();
  return (
    <li aria-labelledby={titleId} className="rounded-2xl bg-raised p-4">
      <h3 id={titleId} className="text-base font-medium break-words text-ink">
        {project.name}
      </h3>
      {project.description && <p className="mt-0.5 text-sm break-words text-ink-muted">{project.description}</p>}
      {/* Sous le nom, jamais a cote : sur telephone, il le coupait en deux lignes. */}
      {project.idle_days !== null && (
        <p className="mt-2 inline-flex rounded-full bg-notice-soft px-2.5 py-0.5 text-xs text-notice">
          Sans activité depuis {plural(project.idle_days, "jour", "jours")}
        </p>
      )}
      <div className="mt-3 flex items-center gap-3">
        <div
          role="progressbar"
          aria-label={`Avancement de ${project.name}`}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={project.done_tasks}
          aria-valuetext={`${String(project.done_tasks)} tâches terminées sur ${String(total)}`}
          className="h-1.5 flex-1 overflow-hidden rounded-full bg-hover"
        >
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-300"
            style={{ width: total === 0 ? "0%" : `${String(Math.round((100 * project.done_tasks) / total))}%` }}
          />
        </div>
        <span className="shrink-0 text-sm text-ink-faint tabular-nums">
          {total === 0 ? "Aucune tâche" : `${String(project.done_tasks)} / ${String(total)}`}
        </span>
      </div>
      {open.length > 0 && (
        <ul aria-label={`Tâches ouvertes de ${project.name}`} className="mt-2 -ml-3 flex flex-col gap-0.5">
          {open.map((task) => (
            <TaskLine key={task.id} task={task} />
          ))}
        </ul>
      )}
      <AddTask project={project} />
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <Button
          variant="quiet"
          size="sm"
          onClick={() => {
            setFinishing(true);
          }}
        >
          <Check aria-hidden="true" />
          Terminer le projet
        </Button>
        <div className="flex-1" />
        <Button
          variant="danger-quiet"
          size="sm"
          onClick={() => {
            setRemoving(true);
          }}
        >
          Supprimer
        </Button>
      </div>
      <ConfirmDialog
        open={finishing}
        onOpenChange={setFinishing}
        tone="plain"
        title={`Terminer « ${project.name} » ?`}
        description={
          project.open_tasks > 0
            ? `${plural(project.open_tasks, "tâche ouverte sera terminée", "tâches ouvertes seront terminées")} aussi, ici et dans ta journée.`
            : "Il rejoint tes projets terminés."
        }
        confirmLabel="Terminer"
        failure="Impossible de terminer ce projet. Réessaie."
        onConfirm={async () => {
          await finishProject(project.id);
          await refresh();
        }}
      />
      <ConfirmDialog
        open={removing}
        onOpenChange={setRemoving}
        title={`Supprimer « ${project.name} » ?`}
        description="Ses tâches sont supprimées aussi, ici et dans ta journée, terminées ou non."
        confirmLabel="Supprimer"
        onConfirm={async () => {
          await removeProject(project.id);
          await refresh();
        }}
      />
    </li>
  );
}

function taskDetails(task: ProjectTask): string | null {
  const parts: string[] = [];
  if (task.due_on) parts.push(`pour le ${longDate(task.due_on)}`);
  if (task.estimate_minutes != null) parts.push(duration(task.estimate_minutes));
  return parts.length > 0 ? parts.join(" · ") : null;
}

function TaskLine({ task }: { task: ProjectTask }) {
  const refresh = useRefresh();
  // Terminer ne se defait pas (ni ici, ni dans le planning) : jamais sur un simple toucher.
  const [completing, setCompleting] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [spent, setSpent] = useState("");
  const spentId = useId();
  const details = taskDetails(task);
  return (
    <li className="flex min-h-12 items-center gap-1 rounded-xl pr-1 hover:bg-hover">
      <Button
        variant="quiet"
        size="icon"
        aria-label={`Marquer « ${task.title} » comme terminée`}
        onClick={() => {
          setCompleting(true);
        }}
        className="group/check"
      >
        <span
          aria-hidden="true"
          className="flex size-5 items-center justify-center rounded-full border-[1.5px] border-ink-faint text-transparent transition-colors group-hover/check:border-accent group-hover/check:text-accent"
        >
          <Check className="size-3" strokeWidth={3} />
        </span>
      </Button>
      <div className="min-w-0 flex-1 py-2">
        <p className="truncate text-base text-ink">{task.title}</p>
        {details && (
          <p className={cn("text-sm", task.overdue ? "text-danger" : "text-ink-faint")}>
            {task.overdue ? `En retard · ${details}` : details}
          </p>
        )}
      </div>
      <Button
        variant="danger-quiet"
        size="icon-sm"
        aria-label={`Supprimer la tâche « ${task.title} »`}
        onClick={() => {
          setRemoving(true);
        }}
      >
        <Trash2 aria-hidden="true" />
      </Button>
      <ConfirmDialog
        open={completing}
        onOpenChange={setCompleting}
        tone="plain"
        title={`Terminer « ${task.title} » ?`}
        description="Elle sera terminée aussi dans ta journée. Tu ne pourras pas la rouvrir."
        confirmLabel="Terminer"
        failure="Impossible de terminer cette tâche. Réessaie."
        onConfirm={async () => {
          await completeProjectTask(task.id, hoursToMinutes(spent));
          setSpent("");
          await refresh();
        }}
      >
        <div className="mt-4 flex flex-col gap-1.5">
          <label htmlFor={spentId} className="text-sm text-ink-muted">
            Temps passé, en heures (facultatif)
          </label>
          <Input
            id={spentId}
            inputMode="decimal"
            value={spent}
            autoComplete="off"
            placeholder="1"
            onChange={(e) => {
              setSpent(e.target.value);
            }}
          />
        </div>
      </ConfirmDialog>
      <ConfirmDialog
        open={removing}
        onOpenChange={setRemoving}
        title={`Supprimer « ${task.title} » ?`}
        description="Elle disparaît aussi de ta journée."
        confirmLabel="Supprimer"
        onConfirm={async () => {
          await removeProjectTask(task.id);
          await refresh();
        }}
      />
    </li>
  );
}

/** Ajout d'une tâche : un bouton discret, déplié à la demande (un formulaire par carte
 * alourdissait la page dès deux projets). Il reste ouvert pour enchaîner les ajouts. */
function AddTask({ project }: { project: Project }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <Button
        variant="quiet"
        size="sm"
        className="mt-1 -ml-1"
        aria-label={`Ajouter une tâche à ${project.name}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        <Plus aria-hidden="true" />
        Ajouter une tâche
      </Button>
    );
  }
  return (
    <TaskForm
      project={project}
      onClose={() => {
        setOpen(false);
      }}
    />
  );
}

function TaskForm({ project, onClose }: { project: Project; onClose: () => void }) {
  const refresh = useRefresh();
  const id = useId();
  const [title, setTitle] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [hours, setHours] = useState("");
  const add = useMutation({
    mutationFn: () =>
      addProjectTask(project.id, { title, due_on: dueOn || null, estimate_minutes: hoursToMinutes(hours) }),
    onSuccess: async () => {
      setTitle("");
      setDueOn("");
      setHours("");
      await refresh();
    },
  });
  return (
    <form
      aria-label={`Ajouter une tâche à ${project.name}`}
      className="mt-2 flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate();
      }}
    >
      <Field id={`${id}-title`} label="Nouvelle tâche">
        <div className="flex gap-2">
          <Input
            id={`${id}-title`}
            value={title}
            maxLength={110}
            required
            autoFocus
            autoComplete="off"
            placeholder="La prochaine étape"
            onChange={(e) => {
              setTitle(e.target.value);
            }}
          />
          <Button type="submit" variant="secondary" className="h-11" disabled={add.isPending || !title.trim()}>
            <Plus aria-hidden="true" />
            Ajouter
          </Button>
        </div>
      </Field>
      {/* Facultatifs : sans durée, la tâche n'entre pas dans le plan du jour (Lorakus la demandera). */}
      <div className="grid grid-cols-2 gap-3">
        <Field id={`${id}-due`} label="Pour le (facultatif)">
          <Input
            id={`${id}-due`}
            type="date"
            value={dueOn}
            onChange={(e) => {
              setDueOn(e.target.value);
            }}
          />
        </Field>
        <Field id={`${id}-hours`} label="Durée, en heures">
          <Input
            id={`${id}-hours`}
            inputMode="decimal"
            value={hours}
            autoComplete="off"
            placeholder="1"
            onChange={(e) => {
              setHours(e.target.value);
            }}
          />
        </Field>
      </div>
      <Alert text={message(add.error)} />
      <div>
        <Button variant="quiet" size="sm" onClick={onClose}>
          Fermer
        </Button>
      </div>
    </form>
  );
}

function DoneProjects() {
  const done = useQuery(projectsQuery("done"));
  return (
    <Collapsible
      title="Projets terminés"
      count={done.data?.length}
      defaultOpen={false}
      className="mt-6"
      headerClassName="px-3"
    >
      {done.isPending ? (
        <p className="px-3 pb-3 text-sm text-ink-faint" aria-busy="true">
          Chargement…
        </p>
      ) : done.isError ? (
        <p role="alert" className="px-3 pb-3 text-sm text-danger">
          Impossible de charger les projets terminés.
        </p>
      ) : done.data.length === 0 ? (
        <p className="px-3 pb-3 text-sm text-ink-faint">Aucun projet terminé pour l'instant.</p>
      ) : (
        <ul aria-label="Projets terminés" className="flex flex-col gap-0.5 pb-3">
          {done.data.map((project) => (
            <li key={project.id} className="flex min-h-12 flex-col justify-center rounded-xl px-3 py-2">
              <span className="truncate text-base text-ink-muted">{project.name}</span>
              <span className="truncate text-sm text-ink-faint">
                {plural(project.done_tasks, "tâche", "tâches")}
                {project.finished_at ? ` · terminé le ${longDate(localDay(project.finished_at))}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Collapsible>
  );
}
