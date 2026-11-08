import {
  addAttachment,
  type AttachmentKindEnum,
  getListAttachmentsQueryKey,
  removeAttachment,
  useListAttachments,
} from "@frutti/api";
import { formatDateTime, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Input, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fieldErrors } from "./errors";

/** "1,2 Mo" or "350 Ko": the size of a file, as people read it. */
function sizeOf(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;
  return `${Math.max(1, Math.round(bytes / 1024))} Ko`;
}

/** The files attached to one document (D-288, Perfaxis's "Documents associés"): a signed quote, the customer's order,
 * the supplier's delivery note or invoice scan. A PDF or a photo; the owner and the manager add and remove them. */
export function AttachmentsCard({
  kind,
  objectId,
  canWrite,
}: {
  kind: AttachmentKindEnum;
  objectId: number;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const inputId = useId();
  const params = { kind, object_id: objectId };
  const list = useListAttachments(params);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListAttachmentsQueryKey(params) });

  const upload = useMutation({
    mutationFn: (file: File) => addAttachment({ kind, object_id: objectId, file, note: note.trim() }),
    onSuccess: async (saved) => {
      setError(null);
      setNote("");
      toast.success(t("admin.attachments.added", { name: saved.name }));
      await refresh();
    },
    onError: (failure) => {
      const errors = fieldErrors(failure);
      setError(errors.file ?? errors.kind ?? errors.detail ?? t("admin.attachments.failed"));
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => removeAttachment(id),
    onSuccess: async () => {
      toast.success(t("admin.attachments.removed"));
      await refresh();
    },
    onError: () => toast.error(t("admin.attachments.failed")),
  });

  const rows = list.data ?? [];
  if (!canWrite && rows.length === 0) return null;
  return (
    <Card className="print:hidden">
      <CardTitle>{t("admin.attachments.title")}</CardTitle>
      {rows.length === 0 ? (
        <p className="text-[0.88rem] text-ink-2">{t("admin.attachments.none")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-wrap items-baseline gap-x-3 border-b border-line pb-2 last:border-0">
              <a
                href={row.file_url}
                target="_blank"
                rel="noreferrer"
                className="font-semibold text-sea hover:underline"
              >
                {row.name}
              </a>
              <span className="num text-[0.82rem] text-ink-2">{sizeOf(row.size)}</span>
              {canWrite && (
                <Button
                  variant="ghost"
                  className="ms-auto"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(row.id)}
                  aria-label={t("admin.attachments.removeLabel", { name: row.name })}
                >
                  {t("admin.attachments.remove")}
                </Button>
              )}
              <span className="w-full text-[0.82rem] text-ink-2">
                {[row.note, row.uploaded_by, formatDateTime(row.uploaded_at)].filter(Boolean).join(" · ")}
              </span>
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Input
            aria-label={t("admin.attachments.note")}
            placeholder={t("admin.attachments.note")}
            value={note}
            maxLength={255}
            onChange={(event) => setNote(event.target.value)}
            className="min-w-48 flex-1"
          />
          <label htmlFor={inputId} className="cursor-pointer text-[0.9rem] font-semibold text-sea hover:underline">
            {upload.isPending ? t("admin.attachments.sending") : t("admin.attachments.add")}
          </label>
          <input
            id={inputId}
            type="file"
            accept="image/jpeg,image/png,image/webp,application/pdf"
            className="sr-only"
            disabled={upload.isPending}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate(file);
              event.target.value = "";
            }}
          />
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 text-[0.82rem] font-semibold text-bad">
          {error}
        </p>
      )}
      {canWrite && <p className="mt-2 text-[0.8rem] text-ink-2">{t("admin.attachments.hint")}</p>}
    </Card>
  );
}
