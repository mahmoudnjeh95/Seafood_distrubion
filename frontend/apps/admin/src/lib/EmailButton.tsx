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
import { addTyped, chosenAddresses, MAX_RECIPIENTS, sameAddress, setTicked, typedAddresses } from "./emailRecipients";
import type { PdfKind } from "./pdf";

/** The window, opened with the party's addresses, subject and message already in (D-206, D-222). */
function EmailForm({ kind, id, onDone }: { kind: PdfKind; id: number; onDone: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const draft = useGetDocumentEmailDraft(kind, id);
  // Every address the party has is ticked; unticking one only leaves it out of this send.
  const [unticked, setUnticked] = useState<string[]>([]);
  // Addresses typed for this send only; the party itself is not changed.
  const [added, setAdded] = useState<string[]>([]);
  const [typed, setTyped] = useState("");
  const [subject, setSubject] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  // The typed values win; until something is typed, the server's proposal shows.
  const shownSubject = subject ?? draft.data?.subject ?? "";
  const shownBody = body ?? draft.data?.body ?? "";
  const offered = [...(draft.data?.to ?? []), ...added];
  const chosen = chosenAddresses(offered, unticked);
  const send = useMutation({
    mutationFn: () => sendDocumentEmail(kind, id, { to: chosen, subject: shownSubject, body: shownBody }),
    onSuccess: () => {
      toast.success(t("admin.documents.email.sent", { to: chosen.join(", ") }));
      onDone();
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      setErrors(Object.keys(found).length > 0 ? found : { detail: t("admin.documents.email.failed") });
    },
  });
  const addTypedAddresses = () => {
    const values = typedAddresses(typed);
    if (values === null) {
      setErrors({ to: t("admin.documents.email.badAddress") });
      return;
    }
    if (values.length === 0) return;
    const next = addTyped(added, offered, unticked, values);
    setAdded(next.added);
    setUnticked(next.unticked);
    setTyped("");
    setErrors({});
  };
  const submit = () => {
    const found: Record<string, string> = {};
    if (chosen.length === 0) found.to = t("admin.documents.email.none");
    else if (chosen.length > MAX_RECIPIENTS) found.to = t("admin.documents.email.tooMany");
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
          <Field label={t("admin.documents.email.to")} htmlFor={`${formId}-add`} error={errors.to}>
            <div className="flex flex-col gap-2">
              {offered.length === 0 && (
                <p className="text-[0.85rem] text-ink-2">{t("admin.documents.email.noAddress")}</p>
              )}
              {offered.map((address) => (
                <div key={address} className="flex items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-[0.95rem]">
                    <input
                      type="checkbox"
                      className="size-4 accent-sea"
                      checked={chosen.some((other) => sameAddress(other, address))}
                      onChange={(event) => setUnticked(setTicked(unticked, address, event.target.checked))}
                    />
                    {address}
                  </label>
                  {added.some((other) => sameAddress(other, address)) && (
                    <button
                      type="button"
                      className="text-[0.85rem] text-ink-2 underline"
                      onClick={() => setAdded(added.filter((other) => !sameAddress(other, address)))}
                    >
                      {t("admin.documents.email.remove")}
                    </button>
                  )}
                </div>
              ))}
              <div className="flex gap-2 pt-1">
                <Input
                  id={`${formId}-add`}
                  type="email"
                  value={typed}
                  placeholder="client@exemple.tn"
                  aria-label={t("admin.documents.email.addLabel")}
                  onChange={(event) => setTyped(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addTypedAddresses();
                    }
                  }}
                />
                <Button onClick={addTypedAddresses}>{t("admin.documents.email.add")}</Button>
              </div>
            </div>
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
