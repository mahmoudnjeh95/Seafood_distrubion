import { type Invoice, type SupplierInvoice, useListInvoices, useListSupplierInvoices } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, PageHeader, Pill, Table, Td, Th } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { Fragment } from "react";
import { Link } from "react-router";

import { subtract, sum } from "../lib/decimal";
import { todayInput } from "../payments/shared";
import { csvFile, csvMoney, downloadCsv } from "./csv";
import { TresorerieRibbon } from "./TresorerieRibbon";

const PAGE_SIZE = 200;

type Kind = "sales" | "purchases";
type Tone = "neutral" | "sea" | "good" | "warn" | "bad";
type StatusKey = "draft" | "issued" | "cancelled" | "posted" | "partly_paid" | "paid";

/** One line of the état, from either side: what is owed, what is paid, what remains. */
type Line = {
  id: number;
  number: string;
  href: string;
  date: string;
  due: string | null;
  total: string;
  paid: string;
  remaining: string;
  status: StatusKey;
  partyId: number;
  party: string;
};

const TONE: Record<StatusKey, Tone> = {
  draft: "neutral",
  issued: "sea",
  posted: "sea",
  partly_paid: "warn",
  paid: "good",
  cancelled: "bad",
};

function fromSale(invoice: Invoice): Line {
  return {
    id: invoice.id,
    number: invoice.number,
    href: `/factures/${invoice.id}`,
    date: invoice.issued_on ?? "",
    due: invoice.due_on,
    total: invoice.net_to_pay,
    paid: subtract(invoice.net_to_pay, invoice.remaining_to_pay),
    remaining: invoice.remaining_to_pay,
    status: invoice.status,
    partyId: invoice.customer.id,
    party: invoice.customer.name,
  };
}

function fromPurchase(invoice: SupplierInvoice): Line {
  return {
    id: invoice.id,
    number: invoice.number,
    href: `/achats/factures/${invoice.id}`,
    date: invoice.invoice_date,
    due: invoice.due_date,
    total: invoice.total,
    paid: invoice.paid_amount,
    remaining: invoice.outstanding,
    status: invoice.status,
    partyId: invoice.supplier.id,
    party: invoice.supplier.name,
  };
}

/** "Facture de vente" and "Facture d'achat" (P9-T08): every invoice grouped by customer or supplier, with what was
 * paid and what remains, as the treasury reads them. */
export function EtatsFacturesPage({ kind }: { kind: Kind }) {
  const { t } = useTranslation();
  const sales = useListInvoices(
    { limit: PAGE_SIZE },
    { query: { enabled: kind === "sales", placeholderData: keepPreviousData } },
  );
  const purchases = useListSupplierInvoices(
    { limit: PAGE_SIZE },
    { query: { enabled: kind === "purchases", placeholderData: keepPreviousData } },
  );

  const loading = kind === "sales" ? sales.isPending : purchases.isPending;
  const lines: Line[] =
    kind === "sales" ? (sales.data?.results ?? []).map(fromSale) : (purchases.data?.results ?? []).map(fromPurchase);
  const count = kind === "sales" ? sales.data?.count : purchases.data?.count;

  const groups = new Map<number, { name: string; rows: Line[] }>();
  for (const line of lines) {
    const group = groups.get(line.partyId) ?? { name: line.party, rows: [] };
    group.rows.push(line);
    groups.set(line.partyId, group);
  }

  // The file holds the rows on screen, in the order they are shown (the current list of up to 200 invoices).
  const exportFile = () => {
    const ordered = [...groups.values()].flatMap((group) => group.rows);
    const rows: string[][] = [
      [
        kind === "sales" ? t("admin.treasury.etats.party.customer") : t("admin.treasury.etats.party.supplier"),
        t("admin.treasury.etats.columns.number"),
        t("admin.treasury.etats.columns.date"),
        t("admin.treasury.etats.columns.due"),
        t("admin.treasury.etats.columns.total"),
        t("admin.treasury.etats.columns.paid"),
        t("admin.treasury.etats.columns.remaining"),
        t("admin.treasury.etats.columns.state"),
      ],
      ...ordered.map((line) => [
        line.party,
        line.number,
        line.date ? formatDate(line.date) : "",
        line.due ? formatDate(line.due) : "",
        csvMoney(line.total),
        csvMoney(line.paid),
        csvMoney(line.remaining),
        t(`admin.treasury.etats.status.${line.status}`),
      ]),
      [
        t("admin.treasury.etats.total"),
        "",
        "",
        "",
        csvMoney(sum(lines.map((line) => line.total))),
        csvMoney(sum(lines.map((line) => line.paid))),
        csvMoney(sum(lines.map((line) => line.remaining))),
        "",
      ],
    ];
    downloadCsv(`${kind === "sales" ? "factures-vente" : "factures-achat"}-${todayInput()}.csv`, csvFile(rows));
  };

  return (
    <>
      <TresorerieRibbon active={kind === "sales" ? "factureVente" : "factureAchat"} />
      <PageHeader eyebrow={t("admin.groups.finance")} title={t(`admin.treasury.etats.${kind}.title`)}>
        <Button variant="secondary" disabled={lines.length === 0} onClick={exportFile}>
          {t("admin.treasury.etats.export")}
        </Button>
      </PageHeader>
      <p className="text-ink-2">{t(`admin.treasury.etats.${kind}.intro`)}</p>

      {loading ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : lines.length === 0 ? (
        <Card className="p-3 text-ink-2">{t("admin.treasury.etats.empty")}</Card>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.treasury.etats.columns.number")}</Th>
                <Th>{t("admin.treasury.etats.columns.date")}</Th>
                <Th>{t("admin.treasury.etats.columns.due")}</Th>
                <Th numeric>{t("admin.treasury.etats.columns.total")}</Th>
                <Th numeric>{t("admin.treasury.etats.columns.paid")}</Th>
                <Th numeric>{t("admin.treasury.etats.columns.remaining")}</Th>
                <Th>{t("admin.treasury.etats.columns.state")}</Th>
              </tr>
            </thead>
            <tbody>
              {[...groups.entries()].map(([partyId, group]) => (
                <Fragment key={partyId}>
                  <tr className="bg-surface-2">
                    <Td colSpan={3} className="font-semibold">
                      {group.name}
                    </Td>
                    <Td numeric className="num font-semibold">
                      {formatMoney(sum(group.rows.map((line) => line.total)))}
                    </Td>
                    <Td numeric className="num font-semibold">
                      {formatMoney(sum(group.rows.map((line) => line.paid)))}
                    </Td>
                    <Td numeric className="num font-semibold">
                      {formatMoney(sum(group.rows.map((line) => line.remaining)))}
                    </Td>
                    <Td>{null}</Td>
                  </tr>
                  {group.rows.map((line) => (
                    <tr key={line.id}>
                      <Td className="num">
                        <Link to={line.href} className="font-semibold text-ink hover:underline">
                          {line.number}
                        </Link>
                      </Td>
                      <Td className="num">{line.date ? formatDate(line.date) : "—"}</Td>
                      <Td className="num">{line.due ? formatDate(line.due) : "—"}</Td>
                      <Td numeric className="num">
                        {formatMoney(line.total)}
                      </Td>
                      <Td numeric className="num">
                        {formatMoney(line.paid)}
                      </Td>
                      <Td numeric className="num">
                        {formatMoney(line.remaining)}
                      </Td>
                      <Td>
                        <Pill tone={TONE[line.status]}>{t(`admin.treasury.etats.status.${line.status}`)}</Pill>
                      </Td>
                    </tr>
                  ))}
                </Fragment>
              ))}
              <tr className="font-semibold">
                <Td colSpan={3}>{t("admin.treasury.etats.total")}</Td>
                <Td numeric className="num">
                  {formatMoney(sum(lines.map((line) => line.total)))}
                </Td>
                <Td numeric className="num">
                  {formatMoney(sum(lines.map((line) => line.paid)))}
                </Td>
                <Td numeric className="num">
                  {formatMoney(sum(lines.map((line) => line.remaining)))}
                </Td>
                <Td>{null}</Td>
              </tr>
            </tbody>
          </Table>
          {count !== undefined && count > lines.length && (
            <p className="px-2 pt-2 text-[0.9rem] text-ink-2">
              {t("admin.treasury.etats.truncated", { shown: lines.length, count })}
            </p>
          )}
        </Card>
      )}
    </>
  );
}
