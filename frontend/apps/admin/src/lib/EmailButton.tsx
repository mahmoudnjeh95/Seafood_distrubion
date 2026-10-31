import { sendDocumentEmail, useGetDocumentEmailDraft } from "@frutti/api";
import { formatDateTime, useTranslation } from "@frutti/i18n";
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  toast,
} from "@frutti/ui";
import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fieldErrors } from "./errors";
import type { PdfKind } from "./pdf";

const isEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

/** The window, opened with the proposed address, subject and message already in (D-206). */
function EmailForm({ kind, id, onDone }: { kind: PdfKind; id: number; onDone: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const draft = useGetDocumentEmailDraft(kind, id);
  const [to, setTo] = useState<string | null>(null);
  const [subject, setSubject] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  // The typed values win; until something is typed, the server's proposal shows.
  const shownTo = to ?? draft.data?.to ?? "";
  const shownSubject = subject ?? draft.data?.subject ?? "";
  const shownBody = body ?? draft.data?.body ?? "";
  const addresses = shownTo
    .split(/[,;\s]+/)
    .map((value) => value.trim())
    .filter(Boolean);
  const send = useMutation({
    mutationFn: () => sendDocumentEmail(kind, id, { to: addresses, subject: shownSubject, body: shownBody }),
    onSuccess: () => {
      toast.success(t("admin.documents.email.sent", { to: addresses.join(", ") }));
      onDone();
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      setErrors(Object.keys(found).length > 0 ? found : { detail: t("admin.documents.email.failed") });
    },
  });
  const submit = () => {
    const found: Record<string, string> = {};
    if (addresses.length === 0 || !addresses.every(isEmail)) found.to = t("admin.documents.email.badAddress");
    if (!shownSubject.trim()) found.subject = t("admin.documents.email.required");
    setErrors(found);
    if (Object.keys(found).length === 0) send.mutate();
  };
  const sent = draft.data?.sent ?? [];
  return (
    <DialogContent className="w-[min(640px,calc(100vw-2rem))] max-w-none">
      <DialogTitle>{t("admin.documents.email.title")}</DialogTitle>
      <DialogDescription>{t("admin.documents.email.intro")}</DialogDescription>
      {draft.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : (
        <div className="flex flex-col gap-3">
          <Field label={t("admin.documents.email.to")} htmlFor={`${formId}-to`} error={errors.to}>
            <Input
              id={`${formId}-to`}
              type="email"
              multiple
              value={shownTo}
              placeholder="client@exemple.tn"
              onChange={(event) => setTo(event.target.value)}
            />
          </Field>
          <Field label={t("admin.documents.email.subject")} htmlFor={`${formId}-subject`} error={errors.subject}>
            <Input id={`${formId}-subject`} value={shownSubject} onChange={(event) => setSubject(event.target.value)} />
          </Field>
          <Field label={t("admin.documents.email.body")} htmlFor={`${formId}-body`} error={errors.body}>
            <textarea
              id={`${formId}-body`}
              rows={7}
              value={shownBody}
              onChange={(event) => setBody(event.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
            />
          </Field>
          <p className="text-[0.85rem] text-ink-2">{t("admin.documents.email.attached")}</p>
          {sent.length > 0 && (
            <div className="text-[0.85rem]">
              <p className="font-semibold">{t("admin.documents.email.history")}</p>
              <ul>
                {sent.map((row) => (
                  <li key={`${row.sent_at}-${row.to}`} className={row.error ? "text-bad" : "text-ink-2"}>
                    {formatDateTime(row.sent_at)} · {row.to}
                    {row.error ? ` · ${t("admin.documents.email.notSent")}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {errors.detail && (
            <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
              {errors.detail}
            </p>
          )}
        </div>
      )}
      <DialogFooter>
        <DialogClose asChild>
          <Button>{t("common.cancel")}</Button>
        </DialogClose>
        <Button variant="primary" disabled={send.isPending || draft.isPending} onClick={submit}>
          {send.isPending ? t("admin.documents.email.sending") : t("admin.documents.email.send")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** "E-mail": sends the document's PDF from the company address, with a clear subject and message (D-206). */
export function EmailButton({ kind, id, className }: { kind: PdfKind; id: number; className?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="ghost" className={className} onClick={() => setOpen(true)}>
        {t("admin.documents.email.button")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        {open && <EmailForm kind={kind} id={id} onDone={() => setOpen(false)} />}
      </Dialog>
    </>
  );
}
