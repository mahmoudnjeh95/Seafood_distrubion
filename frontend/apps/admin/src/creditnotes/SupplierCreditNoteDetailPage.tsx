import { ApiError, useGetSupplierCreditNote } from "@frutti/api";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Card, CardTitle, EmptyState, PageHeader, Pill, Table, Td, Th } from "@frutti/ui";
import { Link, useParams } from "react-router";

/** One avoir fournisseur (D-300): its lines, VAT, and the invoices it settled. Never edited. */
export function SupplierCreditNoteDetailPage() {
  const { t } = useTranslation();
  const { creditNoteId } = useParams();
  const id = Number(creditNoteId);
  const validId = Number.isInteger(id) && id > 0;
  const note = useGetSupplierCreditNote(id, { query: { enabled: validId, retry: false } });
  const back = (
    <Link to="/achats/avoirs" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.creditNotes.back")}
    </Link>
  );
  if (validId && note.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!note.data) {
    const missing = !validId || (note.error instanceof ApiError && note.error.status === 404);
    return (
      <>
        {back}
        <EmptyState
          illustration="fish"
          title={missing ? t("admin.creditNotes.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }
  const data = note.data;
  const left = Number(data.total) - Number(data.applied_amount);

  return (
    <>
      {back}
      <PageHeader eyebrow={`${formatDate(data.credited_on)} · ${data.supplier.name}`} title={data.number}>
        {left > 0 && (
          <Pill tone="warn">
            {t("admin.creditNotes.detail.waiting", { amount: formatMoney(String(left.toFixed(3))) })}
          </Pill>
        )}
      </PageHeader>
      <Card>
        <CardTitle>{t("admin.creditNotes.detail.title")}</CardTitle>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
          <div>
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.creditNotes.columns.supplier")}</dt>
            <dd>
              <Link to={`/fournisseurs/${data.supplier.id}`} className="font-semibold text-sea hover:underline">
                {data.supplier.name}
              </Link>
            </dd>
          </div>
          <div>
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.creditNotes.columns.invoice")}</dt>
            <dd className="num">
              {data.invoice ? (
                <Link to={`/achats/factures/${data.invoice}`} className="font-semibold text-sea hover:underline">
                  {data.invoice_number}
                </Link>
              ) : (
                "—"
              )}
            </dd>
          </div>
          <div>
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.creditNotes.form.supplierReference")}</dt>
            <dd className="num">{data.supplier_reference || "—"}</dd>
          </div>
          <div>
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.creditNotes.detail.createdBy")}</dt>
            <dd>{data.created_by || "—"}</dd>
          </div>
          <div className="col-span-full">
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.creditNotes.form.reason")}</dt>
            <dd className="whitespace-pre-line">{data.reason}</dd>
          </div>
        </dl>
      </Card>
      <Card className="p-2">
        <CardTitle className="px-2.5 pt-2">{t("admin.creditNotes.detail.lines")}</CardTitle>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.creditNotes.form.receipt")}</Th>
              <Th>{t("admin.creditNotes.form.lot")}</Th>
              <Th>{t("admin.creditNotes.form.kind")}</Th>
              <Th numeric>{t("admin.creditNotes.form.quantity")}</Th>
              <Th numeric>{t("admin.creditNotes.form.unitAmount")}</Th>
              <Th numeric>{t("admin.creditNotes.form.amount")}</Th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((line) => (
              <tr key={line.id}>
                <Td className="num">
                  <Link to={`/achats/${line.receipt_id}`} className="font-semibold text-sea hover:underline">
                    {line.receipt_number}
                  </Link>
                </Td>
                <Td>
                  {line.product_name} · <span className="num">{line.batch_number}</span>
                </Td>
                <Td>
                  {t(`admin.creditNotes.kinds.${line.kind}`)}
                  {line.from_location_name && <div className="text-[0.8rem] text-ink-2">{line.from_location_name}</div>}
                </Td>
                <Td numeric>{formatQuantity(line.quantity)}</Td>
                <Td numeric>{formatMoney(line.unit_amount)}</Td>
                <Td numeric className="font-semibold">
                  {formatMoney(line.amount)}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <dl className="ms-auto grid w-fit grid-cols-[auto_auto] gap-x-6 gap-y-1 p-3 text-[0.92rem]">
          <dt>{t("admin.creditNotes.detail.excl")}</dt>
          <dd className="num text-end">{formatMoney(data.total_excl_tax)}</dd>
          <dt>{t("admin.creditNotes.detail.vat")}</dt>
          <dd className="num text-end">{formatMoney(data.vat_total)}</dd>
          <dt className="font-semibold">{t("admin.creditNotes.detail.total")}</dt>
          <dd className="num text-end font-semibold">{formatMoney(data.total)}</dd>
        </dl>
      </Card>
      {data.allocations.length > 0 && (
        <Card>
          <CardTitle>{t("admin.creditNotes.detail.settled")}</CardTitle>
          <ul className="flex flex-col gap-1">
            {data.allocations.map((allocation) => (
              <li key={allocation.invoice} className="flex justify-between gap-4">
                <Link
                  to={`/achats/factures/${allocation.invoice}`}
                  className="num font-semibold text-sea hover:underline"
                >
                  {allocation.invoice_number}
                </Link>
                <span className="num">{formatMoney(allocation.amount)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
