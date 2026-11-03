import { useGetPartnership, useListPartnerships } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, Dialog, Pill, Table, Td, Th } from "@frutti/ui";
import { type ReactNode, useState } from "react";

import { PdfButton } from "../lib/PdfButton";
import { AdvanceDialog, CancelPartnershipDialog, PartnershipDialog } from "./PartnershipDialogs";
import { canWriteResults, formatRate, STATUS_TONE } from "./shared";

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className="num font-semibold">{children}</dd>
    </div>
  );
}

/** The lot's partnership (P6-T01): the partner, what each side put in, the two rates and the partner's
 * capital ledger in this lot. The owner sets it before the lot's first sale. */
export function PartnershipSection({
  batch,
  session,
}: {
  batch: {
    id: number;
    number: string;
    origin?: { supplier: string; quantity: string; unitCost: string; total: string };
  };
  session: Session;
}) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<"create" | "edit" | "cancel" | "advance" | null>(null);
  const listed = useListPartnerships({ batch: batch.id });
  const summary = listed.data?.results[0];
  const detail = useGetPartnership(summary?.id ?? 0, { query: { enabled: summary !== undefined } });
  const partnership = summary ? detail.data : undefined;
  const canWrite = canWriteResults(session);
  // Terms change until the lot is closed, even after sales (D-163).
  const editable = partnership !== undefined && partnership.status === "open";
  // An advance comes out of the capital still in, while the lot is open or closed (not yet settled).
  const advanceable =
    partnership !== undefined &&
    (partnership.status === "open" || partnership.status === "closed") &&
    Number(partnership.capital) > 0;

  return (
    <section aria-labelledby="lot-partnership" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="lot-partnership" className="me-auto">
          {t("admin.partnerships.section.title")}
        </h2>
        {partnership && partnership.status !== "cancelled" && (
          <PdfButton kind="partner_statement" id={partnership.id} label={t("admin.documents.statement")} />
        )}
        {canWrite && listed.data && !summary && (
          <Button onClick={() => setDialog("create")}>{t("admin.partnerships.section.add")}</Button>
        )}
        {canWrite && advanceable && (
          <Button onClick={() => setDialog("advance")}>{t("admin.partnerships.section.advance")}</Button>
        )}
        {canWrite && editable && (
          <>
            <Button onClick={() => setDialog("edit")}>{t("admin.partnerships.section.edit")}</Button>
            <Button variant="ghost" onClick={() => setDialog("cancel")}>
              {t("admin.partnerships.section.cancel")}
            </Button>
          </>
        )}
      </div>
      <Card className="flex flex-col gap-4 p-4">
        {listed.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : !summary ? (
          <p className="text-ink-2">
            {t("admin.partnerships.section.none")} {canWrite && t("admin.partnerships.section.addHint")}
          </p>
        ) : !partnership ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : (
          <>
            <dl className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(10rem,1fr))]">
              <Detail label={t("admin.partnerships.section.partner")}>
                {partnership.partner.name}{" "}
                <Pill tone={STATUS_TONE[partnership.status]}>
                  {t(`admin.partnerships.statuses.${partnership.status}`)}
                </Pill>
                {partnership.terms_pending && <Pill tone="warn">{t("admin.partnerships.section.pending")}</Pill>}
              </Detail>
              <Detail label={t("admin.partnerships.section.ownerCapital")}>
                {formatMoney(partnership.owner_capital)}
              </Detail>
              <Detail label={t("admin.partnerships.section.partnerCapital")}>
                {formatMoney(partnership.partner_capital)}
              </Detail>
              <Detail label={t("admin.partnerships.section.profitRate")}>
                {formatRate(partnership.profit_rate)} %
              </Detail>
              <Detail label={t("admin.partnerships.section.lossRate")}>{formatRate(partnership.loss_rate)} %</Detail>
              <Detail label={t("admin.partnerships.section.capitalNow")}>{formatMoney(partnership.capital)}</Detail>
            </dl>
            {partnership.terms_pending && (
              <p role="status" className="rounded-chip bg-warn-soft px-3 py-2 text-[0.88rem] font-semibold text-warn">
                {t("admin.partnerships.section.pendingHint")}
              </p>
            )}
            {partnership.notes && <p className="text-ink-2">{partnership.notes}</p>}
            {partnership.status !== "open" && (
              <p className="text-[0.85rem] text-ink-2">{t("admin.partnerships.section.fixed")}</p>
            )}
            <div className="flex flex-col gap-1">
              <h3 className="text-[0.95rem]">{t("admin.partnerships.section.ledger")}</h3>
              <p className="text-[0.85rem] text-ink-2">{t("admin.partnerships.section.ledgerHint")}</p>
              <Table>
                <thead>
                  <tr>
                    <Th>{t("admin.partnerships.section.entryColumns.date")}</Th>
                    <Th>{t("admin.partnerships.section.entryColumns.kind")}</Th>
                    <Th className="max-[720px]:hidden">{t("admin.partnerships.section.entryColumns.note")}</Th>
                    <Th numeric>{t("admin.partnerships.section.entryColumns.amount")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {partnership.capital_entries.map((entry) => (
                    <tr key={entry.id}>
                      <Td className="num whitespace-nowrap">{formatDate(entry.entry_date)}</Td>
                      <Td>{t(`admin.partnerships.section.entryKinds.${entry.kind}`)}</Td>
                      <Td className="max-[720px]:hidden text-ink-2">{entry.note}</Td>
                      <Td numeric className="whitespace-nowrap">
                        {formatMoney(entry.amount)}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          </>
        )}
      </Card>
      <Dialog open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        {dialog === "create" && <PartnershipDialog batch={batch} onDone={() => setDialog(null)} />}
        {dialog === "edit" && partnership && (
          <PartnershipDialog batch={batch} partnership={partnership} onDone={() => setDialog(null)} />
        )}
        {dialog === "cancel" && partnership && (
          <CancelPartnershipDialog partnership={partnership} onDone={() => setDialog(null)} />
        )}
        {dialog === "advance" && partnership && (
          <AdvanceDialog partnership={partnership} onDone={() => setDialog(null)} />
        )}
      </Dialog>
    </section>
  );
}
