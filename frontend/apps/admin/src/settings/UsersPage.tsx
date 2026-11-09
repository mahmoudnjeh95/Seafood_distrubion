import type { Session } from "@frutti/auth";
import {
  type AccessSection,
  createMember,
  type CustomRole,
  deactivateMember,
  deleteMember,
  getListMembersQueryKey,
  type Member,
  type RoleEnum,
  reactivateMember,
  resetMemberPassword,
  setMemberAccess,
  setMemberCanBuy,
  setMemberRole,
  updateMember,
  useListAccessSections,
  useListCustomRoles,
  useListMembers,
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
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { AccessMatrix, type Level, type Levels } from "./AccessMatrix";

const ROLES: RoleEnum[] = ["owner", "manager", "accountant", "driver"];

// A role in the pickers: a built-in one by its name, a custom one as "custom:<id>" (D-306).
interface RoleChoice {
  role: RoleEnum;
  custom_role: number | null;
}

function choiceValue(choice: RoleChoice): string {
  return choice.role === "custom" ? `custom:${choice.custom_role}` : choice.role;
}

function parseChoice(value: string): RoleChoice {
  if (value.startsWith("custom:")) return { role: "custom", custom_role: Number(value.slice(7)) };
  return { role: value as RoleEnum, custom_role: null };
}

function RoleOptions({ customRoles }: { customRoles: CustomRole[] }) {
  const { t } = useTranslation();
  return (
    <>
      {ROLES.map((value) => (
        <SelectItem key={value} value={value}>
          {t(`roles.${value}`)}
        </SelectItem>
      ))}
      {customRoles.map((role) => (
        <SelectItem key={role.id} value={`custom:${role.id}`}>
          {role.name}
        </SelectItem>
      ))}
    </>
  );
}

/** The levels a person's role gives, section by section. */
function roleLevels(member: Member, sections: AccessSection[], customRoles: CustomRole[]): Record<string, Level> {
  if (member.role === "custom") {
    const role = customRoles.find((row) => row.id === member.custom_role?.id);
    return Object.fromEntries(sections.map((section) => [section.key, role?.access[section.key] ?? "none"]));
  }
  const builtIn = member.role as "owner" | "manager" | "accountant";
  return Object.fromEntries(sections.map((section) => [section.key, section.defaults[builtIn] ?? "none"]));
}

/** A custom role's own name, or the built-in role's label (`builtIn`). */
function memberRoleLabel(member: Member, builtIn: string): string {
  return member.role === "custom" && member.custom_role ? member.custom_role.name : builtIn;
}

function AccessDialog({ member, onDone }: { member: Member; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const sections = useListAccessSections();
  const customRoles = useListCustomRoles();
  const [levels, setLevels] = useState<Levels>({ ...member.access_overrides });
  const name = member.user.first_name || member.user.username;

  const save = useMutation({
    mutationFn: () => {
      const overrides = Object.fromEntries(
        Object.entries(levels).filter((entry): entry is [string, Level] => !!entry[1]),
      );
      return setMemberAccess(member.id, { overrides });
    },
    onSuccess: async () => {
      toast.success(t("admin.users.accessSaved"));
      await queryClient.invalidateQueries({ queryKey: getListMembersQueryKey() });
      onDone();
    },
    onError: (failure) => toast.error(errorText(failure, t("admin.users.error"))),
  });

  return (
    <DialogContent className="max-h-[90dvh] w-[min(640px,calc(100vw-2rem))] overflow-y-auto">
      <DialogTitle>{t("admin.users.accessTitle", { name })}</DialogTitle>
      <DialogDescription>
        {t("admin.users.accessDescription", { role: memberRoleLabel(member, t(`roles.${member.role}`)) })}
      </DialogDescription>
      {sections.data && customRoles.data ? (
        <AccessMatrix
          sections={sections.data}
          value={levels}
          onChange={setLevels}
          inherited={roleLevels(member, sections.data, customRoles.data)}
          disabled={save.isPending}
        />
      ) : (
        <p className="text-ink-2">{t("common.loading")}</p>
      )}
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          {t("admin.users.cancel")}
        </Button>
        <Button variant="primary" disabled={save.isPending || !sections.data} onClick={() => save.mutate()}>
          {t("admin.users.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function errorText(failure: unknown, fallback: string): string {
  return Object.values(fieldErrors(failure))[0] ?? fallback;
}

function AddMemberDialog({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [role, setRole] = useState<RoleChoice>({ role: "manager", custom_role: null });
  const customRoles = useListCustomRoles();
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const create = useMutation({
    mutationFn: () =>
      createMember({
        username: username.trim(),
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        role: role.role,
        custom_role: role.custom_role,
        password,
      }),
    onSuccess: async () => {
      toast.success(t("admin.users.created"));
      await queryClient.invalidateQueries({ queryKey: getListMembersQueryKey() });
      onDone();
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      if (Object.keys(found).length > 0) setErrors(found);
      else toast.error(t("admin.users.error"));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    create.mutate();
  };

  return (
    <DialogContent className="w-[min(480px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.users.createTitle")}</DialogTitle>
      <DialogDescription>{t("admin.users.createDescription")}</DialogDescription>
      <form onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label={t("admin.users.username")} htmlFor={`${formId}-username`} error={errors.username}>
          <Input
            id={`${formId}-username`}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3 max-[520px]:grid-cols-1">
          <Field label={t("admin.users.firstName")} htmlFor={`${formId}-first`} error={errors.first_name}>
            <Input id={`${formId}-first`} value={firstName} onChange={(event) => setFirstName(event.target.value)} />
          </Field>
          <Field label={t("admin.users.lastName")} htmlFor={`${formId}-last`} error={errors.last_name}>
            <Input id={`${formId}-last`} value={lastName} onChange={(event) => setLastName(event.target.value)} />
          </Field>
        </div>
        <Field label={t("admin.users.role")} htmlFor={`${formId}-role`} error={errors.role ?? errors.custom_role}>
          <Select value={choiceValue(role)} onValueChange={(value) => setRole(parseChoice(value))}>
            <SelectTrigger id={`${formId}-role`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <RoleOptions customRoles={customRoles.data ?? []} />
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("admin.users.password")} htmlFor={`${formId}-password`} error={errors.password}>
          <Input
            id={`${formId}-password`}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
          />
        </Field>
        <DialogFooter>
          <Button variant="ghost" onClick={onDone}>
            {t("admin.users.cancel")}
          </Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {t("admin.users.create")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

function ResetPasswordDialog({ member, onDone }: { member: Member; onDone: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | undefined>();
  const name = member.user.first_name || member.user.username;

  const reset = useMutation({
    mutationFn: () => resetMemberPassword(member.id, { new_password: password }),
    onSuccess: () => {
      toast.success(t("admin.users.passwordReset"));
      onDone();
    },
    onError: (failure) => setError(errorText(failure, t("admin.users.error"))),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    reset.mutate();
  };

  return (
    <DialogContent className="w-[min(440px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.users.resetTitle", { name })}</DialogTitle>
      <DialogDescription>{t("admin.users.resetDescription")}</DialogDescription>
      <form onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label={t("admin.users.password")} htmlFor={`${formId}-password`} error={error}>
          <Input
            id={`${formId}-password`}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
          />
        </Field>
        <DialogFooter>
          <Button variant="ghost" onClick={onDone}>
            {t("admin.users.cancel")}
          </Button>
          <Button type="submit" variant="primary" disabled={reset.isPending}>
            {t("admin.users.resetPassword")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

function EditMemberDialog({ member, onDone }: { member: Member; onDone: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState(member.user.username);
  const [firstName, setFirstName] = useState(member.user.first_name);
  const [lastName, setLastName] = useState(member.user.last_name);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const name = member.user.first_name || member.user.username;

  const save = useMutation({
    mutationFn: () =>
      updateMember(member.id, {
        username: username.trim(),
        first_name: firstName.trim(),
        last_name: lastName.trim(),
      }),
    onSuccess: async () => {
      toast.success(t("admin.users.saved"));
      await queryClient.invalidateQueries({ queryKey: getListMembersQueryKey() });
      onDone();
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      if (Object.keys(found).length > 0) setErrors(found);
      else toast.error(t("admin.users.error"));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    save.mutate();
  };

  return (
    <DialogContent className="w-[min(480px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.users.editTitle", { name })}</DialogTitle>
      <DialogDescription>{t("admin.users.editDescription")}</DialogDescription>
      <form onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label={t("admin.users.username")} htmlFor={`${formId}-username`} error={errors.username}>
          <Input
            id={`${formId}-username`}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3 max-[520px]:grid-cols-1">
          <Field label={t("admin.users.firstName")} htmlFor={`${formId}-first`} error={errors.first_name}>
            <Input id={`${formId}-first`} value={firstName} onChange={(event) => setFirstName(event.target.value)} />
          </Field>
          <Field label={t("admin.users.lastName")} htmlFor={`${formId}-last`} error={errors.last_name}>
            <Input id={`${formId}-last`} value={lastName} onChange={(event) => setLastName(event.target.value)} />
          </Field>
        </div>
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

function DeleteMemberDialog({ member, onDone }: { member: Member; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const name = member.user.first_name || member.user.username;

  const remove = useMutation({
    mutationFn: () => deleteMember(member.id),
    onSuccess: async () => {
      toast.success(t("admin.users.removed"));
      await queryClient.invalidateQueries({ queryKey: getListMembersQueryKey() });
      onDone();
    },
    onError: (failure) => toast.error(errorText(failure, t("admin.users.error"))),
  });

  return (
    <DialogContent className="w-[min(440px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.users.removeTitle", { name })}</DialogTitle>
      <DialogDescription>{t("admin.users.removeDescription")}</DialogDescription>
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          {t("admin.users.cancel")}
        </Button>
        <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
          {t("admin.users.removeConfirm")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function MemberRow({ member, isMe }: { member: Member; isMe: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [resetting, setResetting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [accessOpen, setAccessOpen] = useState(false);
  const customRoles = useListCustomRoles();
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListMembersQueryKey() });
  const ownLevels = Object.keys(member.access_overrides).length;
  // The owner has everything and a driver works on the phone: neither takes levels of their own (D-306).
  const takesOwnLevels = member.role !== "owner" && member.role !== "driver";

  const changeRole = useMutation({
    mutationFn: (next: RoleChoice) => setMemberRole(member.id, next),
    onSuccess: async () => {
      toast.success(t("admin.users.roleChanged"));
      await refresh();
    },
    onError: (failure) => toast.error(errorText(failure, t("admin.users.error"))),
  });

  const changeCanBuy = useMutation({
    mutationFn: (canBuy: boolean) => setMemberCanBuy(member.id, { can_buy: canBuy }),
    onSuccess: async (saved) => {
      toast.success(t(saved.can_buy ? "admin.users.canBuyOn" : "admin.users.canBuyOff"));
      await refresh();
    },
    onError: (failure) => toast.error(errorText(failure, t("admin.users.error"))),
  });

  const toggleActive = useMutation({
    mutationFn: () => (member.is_active ? deactivateMember(member.id) : reactivateMember(member.id)),
    onSuccess: async () => {
      toast.success(t(member.is_active ? "admin.users.deactivated" : "admin.users.reactivated"));
      await refresh();
    },
    onError: (failure) => toast.error(errorText(failure, t("admin.users.error"))),
  });

  const fullName = `${member.user.first_name} ${member.user.last_name}`.trim() || member.user.username;

  return (
    <tr>
      <Td>
        <div className="flex items-center gap-2.5">
          {member.user.avatar_url ? (
            <img src={member.user.avatar_url} alt="" className="size-[30px] flex-none rounded-full object-cover" />
          ) : (
            <div className="grid size-[30px] flex-none place-items-center rounded-full bg-sea-soft text-[0.75rem] font-bold text-sea">
              {fullName.charAt(0).toUpperCase()}
            </div>
          )}
          <div className="leading-tight">
            <div className="font-semibold">
              {fullName}
              {isMe && <span className="ms-2 text-[0.75rem] text-ink-2">({t("admin.users.you")})</span>}
            </div>
            <div className="text-[0.8rem] text-ink-2">{member.user.username}</div>
          </div>
        </div>
      </Td>
      <Td>
        <Select
          value={choiceValue({ role: member.role, custom_role: member.custom_role?.id ?? null })}
          onValueChange={(value) => changeRole.mutate(parseChoice(value))}
          disabled={isMe || changeRole.isPending}
        >
          <SelectTrigger aria-label={t("admin.users.role")} className="min-w-[160px]">
            <SelectValue placeholder={memberRoleLabel(member, t(`roles.${member.role}`))} />
          </SelectTrigger>
          <SelectContent>
            <RoleOptions customRoles={customRoles.data ?? []} />
          </SelectContent>
        </Select>
        {takesOwnLevels && ownLevels > 0 && (
          <div className="mt-1.5">
            <Pill tone="warn">{t("admin.users.ownLevels", { count: ownLevels })}</Pill>
          </div>
        )}
        {member.role === "driver" && (
          // Buying at the port from the phone (D-158): only the drivers the owner chooses.
          <label className="mt-1.5 flex items-center gap-2 text-[0.85rem]">
            <input
              type="checkbox"
              checked={member.can_buy}
              disabled={changeCanBuy.isPending}
              onChange={(event) => changeCanBuy.mutate(event.target.checked)}
              className="size-4 accent-coral"
            />
            {t("admin.users.canBuy")}
          </label>
        )}
      </Td>
      <Td>
        {member.is_active ? (
          <Pill tone="good">{t("admin.users.active")}</Pill>
        ) : (
          <Pill tone="neutral">{t("admin.users.inactive")}</Pill>
        )}
      </Td>
      <Td>
        <div className="flex flex-wrap justify-end gap-1.5">
          <Button variant="ghost" onClick={() => setEditing(true)}>
            {t("admin.users.edit")}
          </Button>
          {takesOwnLevels && (
            <Button variant="ghost" onClick={() => setAccessOpen(true)}>
              {t("admin.users.access")}
            </Button>
          )}
          <Button variant="ghost" onClick={() => setResetting(true)}>
            <Icon name="lock" />
            {t("admin.users.resetPassword")}
          </Button>
          {!isMe && (
            <Button variant="ghost" disabled={toggleActive.isPending} onClick={() => toggleActive.mutate()}>
              {member.is_active ? t("admin.users.deactivate") : t("admin.users.reactivate")}
            </Button>
          )}
          {!isMe && (
            <Button variant="ghost" onClick={() => setRemoving(true)}>
              <Icon name="trash" />
              {t("admin.users.remove")}
            </Button>
          )}
        </div>
        <Dialog open={editing} onOpenChange={(open) => !open && setEditing(false)}>
          {editing && <EditMemberDialog member={member} onDone={() => setEditing(false)} />}
        </Dialog>
        <Dialog open={accessOpen} onOpenChange={(open) => !open && setAccessOpen(false)}>
          {accessOpen && <AccessDialog member={member} onDone={() => setAccessOpen(false)} />}
        </Dialog>
        <Dialog open={resetting} onOpenChange={(open) => !open && setResetting(false)}>
          {resetting && <ResetPasswordDialog member={member} onDone={() => setResetting(false)} />}
        </Dialog>
        <Dialog open={removing} onOpenChange={(open) => !open && setRemoving(false)}>
          {removing && <DeleteMemberDialog member={member} onDone={() => setRemoving(false)} />}
        </Dialog>
      </Td>
    </tr>
  );
}

/** "Utilisateurs" in Paramètres: who logs in, with which role. Owner only; the server checks it too (D-123). */
export function UsersPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const query = useListMembers();
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHeader eyebrow={t("admin.settings.title")} title={t("admin.users.title")}>
        <Button variant="primary" onClick={() => setAdding(true)}>
          <Icon name="plus" />
          {t("admin.users.add")}
        </Button>
      </PageHeader>
      {query.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : query.data ? (
        query.data.length === 0 ? (
          <p className="text-ink-2">{t("admin.users.empty")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.users.columns.user")}</Th>
                <Th>{t("admin.users.columns.role")}</Th>
                <Th>{t("admin.users.columns.status")}</Th>
                <Th>{t("admin.users.columns.actions")}</Th>
              </tr>
            </thead>
            <tbody>
              {query.data.map((member) => (
                <MemberRow key={member.id} member={member} isMe={member.user.id === session.user.id} />
              ))}
            </tbody>
          </Table>
        )
      ) : (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      )}
      <Dialog open={adding} onOpenChange={(open) => !open && setAdding(false)}>
        {adding && <AddMemberDialog onDone={() => setAdding(false)} />}
      </Dialog>
    </>
  );
}
