import {
  ApiError,
  getGetWebRequestQueryKey,
  getListWebRequestsQueryKey,
  setWebRequestStatus,
  useGetWebRequest,
  type WebRequest,
  type WebRequestStatusEnum,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatDateTime, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, cn, EmptyState, Field, PageHeader, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { NewDocumentDialog } from "../doclist/NewDocumentDialog";
import { lineTotal, sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { canWriteQuotes } from "../quotes/shared";
import { canRecordReceipts } from "../receipts/shared";
import { KIND_TONE, STATUS_TONE } from "./shared";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

/** One quote request or order from the public site (D-186): call the visitor, then close it with a note. */
export function WebRequestPage() {
  const { t } = useTranslation();
  const { requestId } = useParams();
  const id = Number(requestId);
  const validId = Number.isInteger(id) && id > 0;
  const request = useGetWebRequest(id, { query: { enabled: validId, retry: false } });

  const back = (
    <Link to="/demandes-site" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.webRequests.back")}
    </Link>
  );
  if (!validId || (request.error instanceof ApiError && request.error.status === 404)) {
    return (
      <>
        {back}
        <EmptyState illustration="mix" title={t("admin.webRequests.notFound")} />
      </>
    );
  }
  if (request.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (request.isError) {
    return (
      <p role="alert" className="text-bad">
        {t("common.serverUnreachable")}
      </p>
    );
  }
  return <WebRequestView request={request.data} back={back} />;
}

function WebRequestView({ request, back }: { request: WebRequest; back: ReactNode }) {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canHandle = canRecordReceipts(session);
  const canQuote = canWriteQuotes(session);
  const none = "—";
  const priced = request.lines.filter((line) => line.web_price !== null);
  const estimate =
    priced.length > 0 ? sum(priced.map((line) => lineTotal(line.quantity, line.web_price ?? "0"))) : null;

  return (
    <>
      {back}
      <PageHeader
        eyebrow={t(`admin.webRequests.kind.${request.kind}`)}
        title={`${request.number} · ${request.full_name}`}
      >
        <Pill tone={KIND_TONE[request.kind]}>{t(`admin.webRequests.kind.${request.kind}`)}</Pill>
        <Pill tone={STATUS_TONE[request.status]}>{t(`admin.webRequests.status.${request.status}`)}</Pill>
      </PageHeader>

      {/* The office's actions come first: they are what the person came to this page for (D-186). */}
      <OfficeCard request={request} canHandle={canHandle} canQuote={canQuote} />

      <Card>
        <CardTitle>{t("admin.webRequests.contact")}</CardTitle>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
          <Detail label={t("admin.webRequests.columns.phone")} numeric>
            <a href={`tel:${request.phone.replaceAll(" ", "")}`} className="font-semibold text-sea hover:underline">
              {request.phone}
            </a>
          </Detail>
          <Detail label={t("admin.webRequests.email")}>
            {request.email ? (
              <a href={`mailto:${request.email}`} className="text-sea hover:underline">
                {request.email}
              </a>
            ) : (
              none
            )}
          </Detail>
          <Detail label={t("admin.webRequests.company")}>{request.company || none}</Detail>
          <Detail label={t("admin.webRequests.city")}>{request.city || none}</Detail>
          <Detail label={t("admin.webRequests.address")}>{request.address || none}</Detail>
          <Detail label={t("admin.webRequests.wantedOn")} numeric>
            {request.wanted_on ? formatDate(request.wanted_on) : none}
          </Detail>
          <Detail label={t("admin.webRequests.columns.date")} numeric>
            {formatDateTime(request.created_at)}
          </Detail>
        </dl>
        {request.message && (
          <div className="mt-4">
            <div className="text-[0.78rem] font-semibold text-ink-2">{t("admin.webRequests.message")}</div>
            <p className="mt-1 whitespace-pre-line">{request.message}</p>
          </div>
        )}
      </Card>

      <Card className="p-2">
        <CardTitle className="px-2 pt-2">{t("admin.webRequests.lines")}</CardTitle>
        {request.lines.length === 0 ? (
          <p className="p-2 text-ink-2">{t("admin.webRequests.noLines")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.webRequests.product")}</Th>
                <Th numeric>{t("admin.webRequests.quantity")}</Th>
                <Th numeric>{t("admin.webRequests.webPrice")}</Th>
                <Th numeric>{t("admin.webRequests.lineTotal")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.webRequests.note")}</Th>
              </tr>
            </thead>
            <tbody>
              {request.lines.map((line) => (
                <tr key={line.id}>
                  <Td>
                    <span className="font-semibold">{line.product_name}</span>
                    <span className="num ms-2 text-[0.8rem] text-ink-2">{line.product_reference}</span>
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatQuantity(line.quantity)}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {line.web_price ? formatMoney(line.web_price) : t("admin.webRequests.onRequest")}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {line.web_price ? formatMoney(lineTotal(line.quantity, line.web_price)) : none}
                  </Td>
                  <Td className="max-[720px]:hidden">{line.note || none}</Td>
                </tr>
              ))}
            </tbody>
            {estimate && (
              <tfoot>
                <tr>
                  <Td colSpan={3} className="font-semibold">
                    {t("admin.webRequests.estimate")}
                  </Td>
                  <Td numeric className="font-semibold whitespace-nowrap">
                    {formatMoney(estimate)}
                  </Td>
                  <Td className="max-[720px]:hidden" />
                </tr>
              </tfoot>
            )}
          </Table>
        )}
      </Card>
    </>
  );
}

function OfficeCard({ request, canHandle, canQuote }: { request: WebRequest; canHandle: boolean; canQuote: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const noteId = useId();
  const [note, setNote] = useState(request.office_note);
  const [error, setError] = useState("");
  // The quote opens in a window over this page, its products already in; the page itself does not change (D-138).
  const [quoting, setQuoting] = useState(false);

  const change = useMutation({
    mutationFn: (status: WebRequestStatusEnum) => setWebRequestStatus(request.id, { status, office_note: note }),
    onSuccess: async (saved) => {
      setError("");
      toast.success(t("admin.webRequests.saved"));
      queryClient.setQueryData(getGetWebRequestQueryKey(request.id), saved);
      await queryClient.invalidateQueries({ queryKey: getListWebRequestsQueryKey() });
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setError(fromServer.office_note ?? fromServer.status ?? fromServer.detail ?? t("common.serverUnreachable"));
    },
  });

  return (
    <Card>
      <CardTitle>{t("admin.webRequests.office")}</CardTitle>
      {request.handled_by && request.handled_at && (
        <p className="mb-3 text-[0.9rem] text-ink-2">
          {t("admin.webRequests.handledBy", { name: request.handled_by, date: formatDateTime(request.handled_at) })}
        </p>
      )}
      {canHandle ? (
        <form
          noValidate
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            change.mutate(request.status);
          }}
        >
          <div className="flex flex-wrap gap-2">
            {request.status === "new" ? (
              <>
                <Button variant="primary" disabled={change.isPending} onClick={() => change.mutate("handled")}>
                  {t("admin.webRequests.markHandled")}
                </Button>
                <Button disabled={change.isPending} onClick={() => change.mutate("cancelled")}>
                  {t("admin.webRequests.markCancelled")}
                </Button>
              </>
            ) : (
              <Button disabled={change.isPending} onClick={() => change.mutate("new")}>
                {t("admin.webRequests.reopen")}
              </Button>
            )}
            <Button type="submit" variant="ghost" disabled={change.isPending}>
              {t("admin.webRequests.saveNote")}
            </Button>
            {canQuote && (
              <Button className="ms-auto" onClick={() => setQuoting(true)}>
                {t("admin.webRequests.newQuote")}
              </Button>
            )}
          </div>
          <Field label={t("admin.webRequests.officeNote")} htmlFor={noteId} error={error}>
            <textarea
              id={noteId}
              rows={3}
              maxLength={2000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
            />
          </Field>
        </form>
      ) : (
        <p className="whitespace-pre-line">{request.office_note || "—"}</p>
      )}
      {canQuote && (
        <NewDocumentDialog
          kind={quoting ? "quote" : null}
          title={t("admin.webRequests.newQuote")}
          fromRequest={request}
          onClose={() => setQuoting(false)}
        />
      )}
    </Card>
  );
}
