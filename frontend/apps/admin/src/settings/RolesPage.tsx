import {
  type AccessSection,
  createCustomRole,
  type CustomRole,
  deleteCustomRole,
  getListCustomRolesQueryKey,
  getListMembersQueryKey,
  updateCustomRole,
  useListAccessSections,
  useListCustomRoles,
} from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Icon,
  Input,
  PageHeader,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { AccessMatrix, type Levels } from "./AccessMatrix";

type Template = "manager" | "accountant";

function templateLevels(sections: AccessSection[], template: Template): Levels {
  return Object.fromEntries(sections.map((section) => [section.key, section.defaults[template]]));
}

function RoleDialog({
  role,
  sections,
  onDone,
}: {
  role: CustomRole | null;
  sections: AccessSection[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [name, setName] = useState(role?.name ?? "");
  const [levels, setLevels] = useState<Levels>(role ? { ...role.access } : templateLevels(sections, "manager"));
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () => {
      const access = Object.fromEntries(
        Object.entries(levels).filter((entry): entry is [string, NonNullable<Levels[string]>] => !!entry[1]),
      );
      const body = { name: name.trim(), access };
      return role ? updateCustomRole(role.id, body) : createCustomRole(body);
    },
    onSuccess: async () => {
      toast.success(t(role ? "admin.roles.saved" : "admin.roles.created"));
      await queryClient.invalidateQueries({ queryKey: getListCustomRolesQueryKey() });
      await queryClient.invalidateQueries({ queryKey: getListMembersQueryKey() });
      onDone();
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      if (Object.keys(found).length > 0) setErrors(found);
      else toast.error(t("admin.roles.error"));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    save.mutate();
  };

  const otherErrors = Object.entries(errors).filter(([key]) => key !== "name");

  return (
    <DialogContent className="max-h-[90dvh] w-[min(640px,calc(100vw-2rem))] overflow-y-auto">
      <DialogTitle>{role ? t("admin.roles.editTitle", { name: role.name }) : t("admin.roles.createTitle")}</DialogTitle>
      <DialogDescription>{t("admin.roles.description")}</DialogDescription>
      <form onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label={t("admin.roles.name")} htmlFor={`${formId}-name`} error={errors.name}>
          <Input id={`${formId}-name`} value={name} onChange={(event) => setName(event.target.value)} maxLength={60} />
        </Field>
        <div className="flex flex-wrap items-center gap-2 text-[0.85rem]">
          <span className="text-ink-2">{t("admin.roles.startFrom")}</span>
          {(["manager", "accountant"] as const).map((template) => (
            <Button key={template} variant="ghost" onClick={() => setLevels(templateLevels(sections, template))}>
              {t(`roles.${template}`)}
            </Button>
          ))}
          <Button variant="ghost" onClick={() => setLevels({})}>
            {t("admin.roles.startEmpty")}
          </Button>
        </div>
        <AccessMatrix sections={sections} value={levels} onChange={setLevels} />
        {otherErrors.map(([key, text]) => (
          <p key={key} role="alert" className="text-[0.85rem] font-semibold text-bad">
            {text}
          </p>
        ))}
        <DialogFooter>
          <Button variant="ghost" onClick={onDone}>
            {t("admin.users.cancel")}
          </Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.users.save")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

function DeleteRoleDialog({ role, onDone }: { role: CustomRole; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => deleteCustomRole(role.id),
    onSuccess: async () => {
      toast.success(t("admin.roles.removed"));
      await queryClient.invalidateQueries({ queryKey: getListCustomRolesQueryKey() });
      onDone();
    },
    onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.roles.error")),
  });
  return (
    <DialogContent className="w-[min(440px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.roles.removeTitle", { name: role.name })}</DialogTitle>
      <DialogDescription>{t("admin.roles.removeDescription")}</DialogDescription>
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          {t("admin.users.cancel")}
        </Button>
        <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
          {t("admin.roles.remove")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** "Rôles" in Paramètres: the roles the owner makes, each with a level per section (D-306). Owner only. */
export function RolesPage() {
  const { t } = useTranslation();
  const roles = useListCustomRoles();
  const sections = useListAccessSections();
  const [editing, setEditing] = useState<CustomRole | "new" | null>(null);
  const [removing, setRemoving] = useState<CustomRole | null>(null);

  return (
    <>
      <PageHeader eyebrow={t("admin.settings.title")} title={t("admin.roles.title")}>
        <Button variant="primary" onClick={() => setEditing("new")} disabled={!sections.data}>
          <Icon name="plus" />
          {t("admin.roles.add")}
        </Button>
      </PageHeader>
      <p className="mb-4 text-ink-2">{t("admin.roles.intro")}</p>
      {roles.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : roles.data ? (
        roles.data.length === 0 ? (
          <p className="text-ink-2">{t("admin.roles.empty")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.roles.name")}</Th>
                <Th>{t("admin.roles.members")}</Th>
                <Th>{t("admin.users.columns.actions")}</Th>
              </tr>
            </thead>
            <tbody>
              {roles.data.map((role) => (
                <tr key={role.id}>
                  <Td className="font-semibold">{role.name}</Td>
                  <Td>{t("admin.roles.membersCount", { count: role.member_count })}</Td>
                  <Td>
                    <div className="flex flex-wrap justify-end gap-1.5">
                      <Button variant="ghost" onClick={() => setEditing(role)} disabled={!sections.data}>
                        {t("admin.users.edit")}
                      </Button>
                      <Button variant="ghost" onClick={() => setRemoving(role)} disabled={role.member_count > 0}>
                        <Icon name="trash" />
                        {t("admin.roles.remove")}
                      </Button>
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )
      ) : (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      )}
      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        {editing !== null && sections.data && (
          <RoleDialog
            role={editing === "new" ? null : editing}
            sections={sections.data}
            onDone={() => setEditing(null)}
          />
        )}
      </Dialog>
      <Dialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        {removing && <DeleteRoleDialog role={removing} onDone={() => setRemoving(null)} />}
      </Dialog>
    </>
  );
}
