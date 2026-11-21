import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, GraduationCap, Plus, Trash2 } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import {
  AcademicDisabledError,
  AcademicRefusedError,
  addAssessment,
  addCourse,
  completeAssessment,
  enableAcademic,
  removeAssessment,
  removeCourse,
  updateAssessment,
  type Assessment,
  type AssessmentDraft,
  type AssessmentKind,
  type Course,
} from "@/api/academic";
import { Collapsible } from "@/components/Collapsible";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/features/chat/ConfirmDialog";
import { TopBar } from "@/features/chat/layout";
import { cn } from "@/lib/cn";
import { assessmentsQuery, coursesQuery } from "@/lib/queries";

import { duration, hoursToMinutes, localDay, longDate, minutesToHours, relativeDay, weight } from "@/lib/format";

const KIND_LABEL: Record<AssessmentKind, string> = { assignment: "Devoir", exam: "Examen" };
const SELECT =
  "h-11 w-full rounded-xl border border-line bg-raised px-3 text-md text-ink focus-visible:border-[color-mix(in_srgb,var(--accent)_55%,var(--line))] focus-visible:outline-none";

function message(error: unknown): string | null {
  if (!error) return null;
  return error instanceof AcademicRefusedError ? error.message : "L'opération a échoué. Réessaie.";
}

/**
 * Page « Cours » (PR 46, docs/frontend.md) : devoirs et examens par échéance, en retard
 * d'abord. Chaque évaluation a sa tâche : la terminer ici termine la tâche, et terminer la
 * tâche dans le chat termine l'évaluation.
 */
export function AcademicScreen() {
  const courses = useQuery(coursesQuery);
  const open = useQuery(assessmentsQuery("open"));
  const disabled = courses.error instanceof AcademicDisabledError;
  return (
    <>
      <TopBar />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="page-enter mx-auto flex max-w-2xl flex-col px-5 pb-16 sm:px-6">
          <header className="pt-2 pb-6">
            <h1 className="text-2xl font-semibold">Cours</h1>
            <p className="mt-1 text-sm text-ink-faint">
              Tes devoirs et tes examens. Chacun apparaît aussi dans tes tâches.
            </p>
          </header>
          {disabled ? (
            <EnableAcademic />
          ) : courses.isPending || open.isPending ? (
            <p className="text-sm text-ink-faint" aria-busy="true">
              Chargement…
            </p>
          ) : courses.isError || open.isError ? (
            <p role="alert" className="text-danger">
              Impossible de charger tes cours. Réessaie dans un instant.
            </p>
          ) : courses.data.length === 0 ? (
            <FirstCourse />
          ) : (
            <>
              <OpenAssessments items={open.data} />
              <AddAssessment courses={courses.data} />
              <DoneAssessments />
              <Courses items={courses.data} />
            </>
          )}
        </div>
      </div>
    </>
  );
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["academic"] });
}

function EnableAcademic() {
  const refresh = useRefresh();
  const enable = useMutation({ mutationFn: enableAcademic, onSuccess: refresh });
  return (
    <section aria-labelledby="enable-title" className="rounded-2xl bg-raised p-5">
      <h2 id="enable-title" className="text-base font-medium">
        Active les cours
      </h2>
      <p className="mt-1 text-sm text-ink-muted">
        Une seule fois. Tu pourras noter tes devoirs et tes examens ici, ou les dicter à Lorakus.
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

// ------------------------------------------------------------------ cours
function CourseForm({ label }: { label: string }) {
  const refresh = useRefresh();
  const id = useId();
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => addCourse(name),
    onSuccess: async () => {
      setName("");
      await refresh();
    },
  });
  const error = message(add.error);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate();
      }}
      className="flex flex-col gap-2"
    >
      <label htmlFor={id} className="text-sm text-ink-muted">
        {label}
      </label>
      <div className="flex gap-2">
        <Input
          id={id}
          value={name}
          maxLength={80}
          required
          autoComplete="off"
          placeholder="Machine Learning"
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <Button type="submit" variant="secondary" className="h-11" disabled={add.isPending || !name.trim()}>
          <Plus aria-hidden="true" />
          Ajouter
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

function FirstCourse() {
  return (
    <section aria-labelledby="first-title" className="rounded-2xl bg-raised p-5">
      <h2 id="first-title" className="text-base font-medium">
        Commence par un cours
      </h2>
      <p className="mt-1 mb-4 text-sm text-ink-muted">
        Un devoir ou un examen appartient toujours à un cours.
      </p>
      <CourseForm label="Nom du cours" />
    </section>
  );
}

function Courses({ items }: { items: Course[] }) {
  const refresh = useRefresh();
  const [removing, setRemoving] = useState<Course | null>(null);
  return (
    <Collapsible title="Mes cours" count={items.length} defaultOpen={false} className="mt-2" headerClassName="px-3">
      <ul aria-label="Mes cours" className="flex flex-col gap-0.5 pb-3">
        {items.map((course) => (
          <li key={course.id} className="flex min-h-12 items-center gap-3 rounded-xl px-3 hover:bg-hover">
            <GraduationCap aria-hidden="true" className="size-[18px] shrink-0 text-ink-faint" />
            <p className="min-w-0 flex-1 truncate text-base text-ink">{course.name}</p>
            <Button
              variant="danger-quiet"
              size="icon"
              aria-label={`Supprimer le cours ${course.name}`}
              onClick={() => {
                setRemoving(course);
              }}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
      <div className="px-3 pb-2">
        <CourseForm label="Nouveau cours" />
      </div>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setRemoving(null);
        }}
        title={`Supprimer « ${removing?.name ?? ""} » ?`}
        description="Ses devoirs, ses examens et leurs tâches sont supprimés aussi, terminés ou non."
        confirmLabel="Supprimer"
        onConfirm={async () => {
          if (removing) await removeCourse(removing.id);
          setRemoving(null);
          await refresh();
        }}
      />
    </Collapsible>
  );
}

// ------------------------------------------------------------ evaluations
function details(a: Assessment): string {
  const parts = [a.course_name];
  if (a.kind === "exam") parts.push("Examen");
  if (a.estimate_minutes != null) parts.push(duration(a.estimate_minutes));
  if (a.weight != null) parts.push(`coef. ${weight(a.weight)}`);
  return parts.join(" · ");
}

function OpenAssessments({ items }: { items: Assessment[] }) {
  const late = items.filter((a) => a.overdue);
  const coming = items.filter((a) => !a.overdue);
  if (items.length === 0) {
    return <p className="pb-6 text-base text-ink-muted">Rien à rendre pour l'instant.</p>;
  }
  return (
    <div className="flex flex-col gap-5 pb-6">
      {late.length > 0 && <AssessmentGroup title="En retard" items={late} />}
      {coming.length > 0 && <AssessmentGroup title="À venir" items={coming} />}
    </div>
  );
}

function AssessmentGroup({ title, items }: { title: string; items: Assessment[] }) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="px-3 pb-1 text-sm font-medium text-ink-faint">
        {title}
      </h2>
      <ul aria-labelledby={id} className="flex flex-col gap-0.5">
        {items.map((a) => (
          <AssessmentLine key={a.id} item={a} />
        ))}
      </ul>
    </section>
  );
}

function AssessmentLine({ item }: { item: Assessment }) {
  const refresh = useRefresh();
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  // Terminer ne se defait pas (ni ici, ni pour la tache) : jamais sur un simple toucher.
  const [completing, setCompleting] = useState(false);
  // Temps reellement passe (PR 49), facultatif : l'ecart avec l'estimation, plus tard.
  const [spent, setSpent] = useState("");
  const spentId = useId();

  if (editing) {
    return (
      <li className="rounded-2xl bg-raised p-4">
        <AssessmentForm
          legend={`Modifier « ${item.title} »`}
          initial={item}
          submitLabel="Enregistrer"
          onSubmit={async (draft) => {
            await updateAssessment(item.id, draft);
            setEditing(false);
            await refresh();
          }}
          onCancel={() => {
            setEditing(false);
          }}
          extraAction={
            <Button
              variant="danger-quiet"
              size="sm"
              onClick={() => {
                setRemoving(true);
              }}
            >
              Supprimer
            </Button>
          }
        />
        <ConfirmDialog
          open={removing}
          onOpenChange={setRemoving}
          title={`Supprimer « ${item.title} » ?`}
          description="Sa tâche disparaît aussi de ta liste."
          confirmLabel="Supprimer"
          onConfirm={async () => {
            await removeAssessment(item.id);
            await refresh();
          }}
        />
      </li>
    );
  }
  return (
    <li className="flex min-h-12 items-center gap-1 rounded-xl pr-3 pl-1 hover:bg-hover">
      <Button
        variant="quiet"
        size="icon"
        aria-label={`Marquer « ${item.title} » comme terminé`}
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
      <button
        type="button"
        aria-label={`Modifier « ${item.title} »`}
        onClick={() => {
          setEditing(true);
        }}
        className="min-w-0 flex-1 py-2.5 text-left"
      >
        <span className="block truncate text-base text-ink">{item.title}</span>
        <span className="block truncate text-sm text-ink-faint">{details(item)}</span>
        <span className={cn("block truncate text-sm", item.overdue ? "text-danger" : "text-ink-muted")}>
          {longDate(item.due_on)} ({relativeDay(item.days_left)})
        </span>
      </button>
      <ConfirmDialog
        open={completing}
        onOpenChange={setCompleting}
        tone="plain"
        title={`Terminer « ${item.title} » ?`}
        description="Sa tâche sera terminée aussi. Tu ne pourras pas la rouvrir."
        confirmLabel="Terminer"
        failure="Impossible de terminer cette évaluation. Réessaie."
        onConfirm={async () => {
          await completeAssessment(item.id, hoursToMinutes(spent));
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
            placeholder={item.estimate_minutes ? minutesToHours(item.estimate_minutes) : "2"}
            onChange={(e) => {
              setSpent(e.target.value);
            }}
          />
        </div>
      </ConfirmDialog>
    </li>
  );
}

function DoneAssessments() {
  const done = useQuery(assessmentsQuery("done"));
  return (
    <Collapsible title="Terminés" count={done.data?.length} defaultOpen={false} className="mt-6" headerClassName="px-3">
      {done.isPending ? (
        <p className="px-3 pb-3 text-sm text-ink-faint" aria-busy="true">
          Chargement…
        </p>
      ) : done.isError ? (
        <p role="alert" className="px-3 pb-3 text-sm text-danger">
          Impossible de charger les évaluations terminées.
        </p>
      ) : done.data.length === 0 ? (
        <p className="px-3 pb-3 text-sm text-ink-faint">Rien de terminé pour l'instant.</p>
      ) : (
        <ul aria-label="Terminés" className="flex flex-col gap-0.5 pb-3">
          {done.data.map((a) => (
            <li key={a.id} className="flex min-h-12 flex-col justify-center rounded-xl px-3 py-2">
              <span className="truncate text-base text-ink-muted line-through decoration-ink-faint">{a.title}</span>
              <span className="truncate text-sm text-ink-faint">
                {details(a)}
                {a.completed_at ? ` · terminé le ${longDate(localDay(a.completed_at))}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Collapsible>
  );
}

function AddAssessment({ courses }: { courses: Course[] }) {
  const refresh = useRefresh();
  const [courseId, setCourseId] = useState(courses[0]?.id ?? "");
  const [round, setRound] = useState(0);
  const selectId = useId();
  // Le cours choisi a pu etre supprime : on retombe sur le premier.
  const chosen = courses.some((c) => c.id === courseId) ? courseId : (courses[0]?.id ?? "");
  return (
    <section className="rounded-2xl bg-raised p-5">
      <AssessmentForm
        key={round} // formulaire vide apres chaque ajout
        legend="Ajouter une évaluation"
        submitLabel="Ajouter"
        onSubmit={async (draft) => {
          await addAssessment(chosen, draft);
          setRound((n) => n + 1);
          await refresh();
        }}
        before={
          <Field id={selectId} label="Cours">
            <select
              id={selectId}
              value={chosen}
              className={SELECT}
              onChange={(e) => {
                setCourseId(e.target.value);
              }}
            >
              {courses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        }
      />
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

/** Saisie d'une évaluation, pour l'ajout comme pour la correction. */
function AssessmentForm({
  legend,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
  before,
  extraAction,
}: {
  legend: string;
  initial?: Assessment;
  submitLabel: string;
  onSubmit: (draft: AssessmentDraft) => Promise<void>;
  onCancel?: () => void;
  /** Champ place avant les autres (le choix du cours, a l'ajout). */
  before?: ReactNode;
  extraAction?: ReactNode;
}) {
  const id = useId();
  const [kind, setKind] = useState<AssessmentKind>(initial?.kind ?? "assignment");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [dueOn, setDueOn] = useState(initial?.due_on ?? "");
  const [hours, setHours] = useState(minutesToHours(initial?.estimate_minutes ?? null));
  const [coefficient, setCoefficient] = useState(initial?.weight != null ? weight(initial.weight) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      aria-labelledby={`${id}-legend`}
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        const parsedWeight = coefficient.trim() === "" ? null : Number(coefficient.replace(",", "."));
        if (parsedWeight !== null && !(parsedWeight > 0 && parsedWeight <= 100)) {
          setError("Le coefficient doit être plus grand que 0, et de 100 au plus.");
          return;
        }
        setBusy(true);
        setError(null);
        onSubmit({
          kind,
          title, // nettoye par le serveur (une ligne, sans caractere invisible)
          due_on: dueOn,
          weight: parsedWeight,
          estimate_minutes: hoursToMinutes(hours),
        })
          .catch((cause: unknown) => {
            setError(message(cause));
          })
          .finally(() => {
            setBusy(false);
          });
      }}
    >
      <h2 id={`${id}-legend`} className="text-base font-medium">
        {legend}
      </h2>
      {before}
      <Field id={`${id}-title`} label="Titre">
        <Input
          id={`${id}-title`}
          value={title}
          maxLength={110}
          required
          autoComplete="off"
          placeholder={kind === "exam" ? "Partiel" : "TP 2"}
          onChange={(e) => {
            setTitle(e.target.value);
          }}
        />
      </Field>
      {/* Deux colonnes, telephone compris : quatre champs courts tiennent sur deux lignes. */}
      <div className="grid grid-cols-2 gap-3">
        <Field id={`${id}-kind`} label="Type">
          <select
            id={`${id}-kind`}
            value={kind}
            className={SELECT}
            onChange={(e) => {
              setKind(e.target.value as AssessmentKind);
            }}
          >
            <option value="assignment">{KIND_LABEL.assignment}</option>
            <option value="exam">{KIND_LABEL.exam}</option>
          </select>
        </Field>
        <Field id={`${id}-due`} label={kind === "exam" ? "Date" : "Échéance"}>
          <Input
            id={`${id}-due`}
            type="date"
            value={dueOn}
            required
            onChange={(e) => {
              setDueOn(e.target.value);
            }}
          />
        </Field>
        <Field id={`${id}-hours`} label="Durée (heures)">
          <Input
            id={`${id}-hours`}
            inputMode="decimal"
            value={hours}
            autoComplete="off"
            placeholder="3"
            onChange={(e) => {
              setHours(e.target.value);
            }}
          />
        </Field>
        <Field id={`${id}-weight`} label="Coefficient">
          <Input
            id={`${id}-weight`}
            inputMode="decimal"
            value={coefficient}
            autoComplete="off"
            placeholder="1"
            onChange={(e) => {
              setCoefficient(e.target.value);
            }}
          />
        </Field>
      </div>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={busy || !title.trim() || !dueOn}>
          {submitLabel}
        </Button>
        {onCancel && (
          <Button variant="quiet" size="sm" onClick={onCancel}>
            Annuler
          </Button>
        )}
        <div className="flex-1" />
        {extraAction}
      </div>
    </form>
  );
}
