import { getGetBooksLockQueryKey, setBooksLock, useGetBooksLock } from "@frutti/api";
import { formatDate, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Field, Input, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fieldErrors } from "../lib/errors";

/** The last day of the month before this one: what is usually declared and locked. */
function lastMonthEnd(): string {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), 0);
  const month = String(end.getMonth() + 1).padStart(2, "0");
  const day = String(end.getDate()).padStart(2, "0");
  return `${end.getFullYear()}-${month}-${day}`;
}

/** The period lock (D-315): once a month is declared to the tax office, no new entry is dated in it. The office
 * reads it; only the owner moves it, and opening a declared period again needs a reason. */
export function BooksLockCard({ canWrite }: { canWrite: boolean }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const query = useGetBooksLock();
  const current = query.data?.until ?? null;
  const [until, setUntil] = useState<string>("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const typed = until || current || lastMonthEnd();
  const reopening = current !== null && (typed === "" || typed < current);

  const save = useMutation({
    mutationFn: (value: string | null) => setBooksLock({ until: value, reason: reason.trim() }),
    onSuccess: (saved) => {
      setErrors({});
      setUntil("");
      setReason("");
      queryClient.setQueryData(getGetBooksLockQueryKey(), saved);
      toast.success(
        saved.until ? t("admin.booksLock.locked", { date: formatDate(saved.until) }) : t("admin.booksLock.unlocked"),
      );
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      setErrors(Object.keys(found).length > 0 ? found : { detail: t("admin.booksLock.error") });
    },
  });

  return (
    <Card>
      <CardTitle>{t("admin.booksLock.title")}</CardTitle>
      <p className="mb-3 text-[0.85rem] text-ink-2">{t("admin.booksLock.hint")}</p>
      <p className="mb-4 text-[0.9rem] font-semibold">
        {current ? t("admin.booksLock.current", { date: formatDate(current) }) : t("admin.booksLock.none")}
      </p>
      {canWrite && (
        <form
          className="flex flex-col gap-3"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(typed);
          }}
        >
          <Field label={t("admin.booksLock.until")} htmlFor={`${formId}-until`} error={errors.until}>
            <Input
              id={`${formId}-until`}
              type="date"
              value={typed}
              onChange={(event) => setUntil(event.target.value)}
            />
          </Field>
          {(reopening || current !== null) && (
            <Field label={t("admin.booksLock.reason")} htmlFor={`${formId}-reason`} error={errors.reason}>
              <Input
                id={`${formId}-reason`}
                maxLength={255}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                autoComplete="off"
              />
            </Field>
          )}
          {errors.detail && (
            <p role="alert" className="text-[0.85rem] font-semibold text-bad">
              {errors.detail}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" disabled={save.isPending}>
              {t("admin.booksLock.save")}
            </Button>
            {current !== null && (
              <Button type="button" variant="ghost" disabled={save.isPending} onClick={() => save.mutate(null)}>
                {t("admin.booksLock.remove")}
              </Button>
            )}
          </div>
        </form>
      )}
    </Card>
  );
}
