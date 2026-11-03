import type { Session } from "@frutti/auth";
import { changeMyPassword, removeMyAvatar, updateMyProfile, uploadMyAvatar } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Field, Icon, Input, PageHeader, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useRef, useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { ListDisplayCard } from "./ListDisplayCard";

function PhotoCard({ session }: { session: Session }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const user = session.user;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["session"] });
  const initials = `${user.first_name.charAt(0)}${user.last_name.charAt(0)}`.toUpperCase() || user.username.charAt(0);

  const upload = useMutation({
    mutationFn: (photo: File) => uploadMyAvatar({ photo }),
    onSuccess: async () => {
      toast.success(t("admin.profile.photoSaved"));
      await refresh();
    },
    onError: (failure) => toast.error(fieldErrors(failure).avatar ?? t("admin.profile.photoError")),
  });

  const remove = useMutation({
    mutationFn: () => removeMyAvatar(),
    onSuccess: async () => {
      toast.success(t("admin.profile.photoRemoved"));
      await refresh();
    },
    onError: () => toast.error(t("admin.profile.photoError")),
  });

  return (
    <Card>
      <CardTitle>{t("admin.profile.photo")}</CardTitle>
      <div className="flex flex-wrap items-center gap-5">
        {user.avatar_url ? (
          <img src={user.avatar_url} alt="" className="size-[104px] flex-none rounded-full object-cover" />
        ) : (
          <div className="grid size-[104px] flex-none place-items-center rounded-full bg-sea-soft text-[1.6rem] font-bold text-sea">
            {initials}
          </div>
        )}
        <div className="flex flex-col items-start gap-2">
          <p className="text-[0.82rem] text-ink-2">{t("admin.profile.photoHint")}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" disabled={upload.isPending} onClick={() => fileInput.current?.click()}>
              <Icon name="plus" />
              {t("admin.profile.photoChange")}
            </Button>
            {user.avatar_url && (
              <Button variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
                {t("admin.profile.photoRemove")}
              </Button>
            )}
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={(event) => {
              const photo = event.target.files?.[0];
              event.target.value = "";
              if (photo) upload.mutate(photo);
            }}
          />
        </div>
      </div>
    </Card>
  );
}

function IdentityCard({ session }: { session: Session }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [firstName, setFirstName] = useState(session.user.first_name);
  const [lastName, setLastName] = useState(session.user.last_name);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () => updateMyProfile({ first_name: firstName.trim(), last_name: lastName.trim() }),
    onSuccess: async () => {
      setErrors({});
      toast.success(t("admin.profile.saved"));
      await queryClient.invalidateQueries({ queryKey: ["session"] });
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      if (Object.keys(found).length > 0) setErrors(found);
      else toast.error(t("admin.profile.error"));
    },
  });

  return (
    <Card>
      <CardTitle>{t("admin.profile.identity")}</CardTitle>
      <form
        className="flex flex-col gap-3.5"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid grid-cols-2 gap-3 max-[520px]:grid-cols-1">
          <Field label={t("admin.users.firstName")} htmlFor={`${formId}-first`} error={errors.first_name}>
            <Input id={`${formId}-first`} value={firstName} onChange={(event) => setFirstName(event.target.value)} />
          </Field>
          <Field label={t("admin.users.lastName")} htmlFor={`${formId}-last`} error={errors.last_name}>
            <Input id={`${formId}-last`} value={lastName} onChange={(event) => setLastName(event.target.value)} />
          </Field>
        </div>
        <div>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.profile.save")}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function PasswordCard() {
  const { t } = useTranslation();
  const formId = useId();
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const change = useMutation({
    mutationFn: () => changeMyPassword({ old_password: oldPassword, new_password: newPassword }),
    onSuccess: () => {
      setErrors({});
      setOldPassword("");
      setNewPassword("");
      setConfirmation("");
      toast.success(t("admin.profile.passwordChanged"));
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      if (Object.keys(found).length > 0) setErrors(found);
      else toast.error(t("admin.profile.passwordError"));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (newPassword !== confirmation) {
      setErrors({ confirm: t("admin.profile.mismatch") });
      return;
    }
    setErrors({});
    change.mutate();
  };

  return (
    <Card>
      <CardTitle>{t("admin.profile.password")}</CardTitle>
      <form className="flex flex-col gap-3.5" onSubmit={submit}>
        <Field label={t("admin.profile.oldPassword")} htmlFor={`${formId}-old`} error={errors.old_password}>
          <Input
            id={`${formId}-old`}
            type="password"
            value={oldPassword}
            onChange={(event) => setOldPassword(event.target.value)}
            autoComplete="current-password"
          />
        </Field>
        <Field label={t("admin.profile.newPassword")} htmlFor={`${formId}-new`} error={errors.new_password}>
          <Input
            id={`${formId}-new`}
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
          />
        </Field>
        <Field label={t("admin.profile.confirmPassword")} htmlFor={`${formId}-confirm`} error={errors.confirm}>
          <Input
            id={`${formId}-confirm`}
            type="password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="new-password"
          />
        </Field>
        <div>
          <Button type="submit" variant="primary" disabled={change.isPending}>
            {t("admin.profile.changePassword")}
          </Button>
        </div>
      </form>
    </Card>
  );
}

/** "Mon profil": the person's own photo, name and password. Every role has one. */
export function ProfilePage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  return (
    <>
      <PageHeader eyebrow={session.organization.name} title={t("admin.profile.title")} />
      <div className="grid grid-cols-2 items-start gap-4 max-[900px]:grid-cols-1">
        <PhotoCard session={session} />
        <IdentityCard session={session} />
        <PasswordCard />
        <ListDisplayCard />
      </div>
    </>
  );
}
