import { useListSupplierCreditNotes, useListSupplierWeightGaps } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  EmptyState,
  Icon,
  Input,
  PageHeader,
  Pager,
  Table,
  Td,
  Th,
  useServerTable,
  useUrlState,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { Link, useNavigate, useOutletContext } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { PurchasingTabs } from "../purchasing/PurchasingTabs";
import { canRecordReceipts } from "../receipts/shared";

/** Achats › Avoirs fournisseurs (D-300): the credit notes, and the kilos suppliers invoiced but we never accepted. */
export function SupplierCreditNotesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordReceipts(session);
  const [search, setSearch] = useUrlState("q");
  const table = useServerTable();
  const query = useDebounced(search.trim());
  const notes = useListSupplierCreditNotes(
    { ...table.params, ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const gaps = useListSupplierWeightGaps();
  const list = notes.data?.results ?? [];

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.creditNotes.title")}>
        {canRecord && (
          <Button variant="primary" onClick={() => void navigate("/achats/avoirs/nouveau")}>
            <Icon name="plus" />
            {t("admin.creditNotes.add")}
          </Button>
        )}
      </PageHeader>

      <PurchasingTabs />

      {(gaps.data ?? []).length > 0 && (
        <Card className="p-2">
          <CardTitle className="px-2.5 pt-2">{t("admin.creditNotes.gaps.title")}</CardTitle>
          <p className="px-2.5 text-[0.88rem] text-ink-2">{t("admin.creditNotes.gaps.body")}</p>
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.creditNotes.gaps.supplier")}</Th>
                <Th numeric>{t("admin.creditNotes.gaps.lines")}</Th>
                <Th numeric>{t("admin.creditNotes.gaps.quantity")}</Th>
                <Th numeric>{t("admin.creditNotes.gaps.amount")}</Th>
                {canRecord && <Th />}
              </tr>
            </thead>
            <tbody>
              {(gaps.data ?? []).map((gap) => (
                <tr key={gap.supplier_id}>
                  <Td className="font-semibold">{gap.supplier_name}</Td>
                  <Td numeric>{gap.lines}</Td>
                  <Td numeric>{formatQuantity(gap.quantity)}</Td>
                  <Td numeric className="font-semibold">
                    {formatMoney(gap.amount)}
                  </Td>
                  {canRecord && (
                    <Td className="text-end">
                      <Link
                        to={`/achats/avoirs/nouveau?fournisseur=${gap.supplier_id}&motif=weight`}
                        className="font-semibold text-sea hover:underline"
                      >
                        {t("admin.creditNotes.gaps.claim")}
                      </Link>
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.creditNotes.search")}
          placeholder={t("admin.creditNotes.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
      </Card>

      {notes.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : notes.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        <EmptyState illustration="fish" title={t("admin.creditNotes.empty")}>
          {t("admin.creditNotes.emptyBody")}
        </EmptyState>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.creditNotes.columns.number")}</Th>
                <Th>{t("admin.creditNotes.columns.date")}</Th>
                <Th>{t("admin.creditNotes.columns.supplier")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.creditNotes.columns.invoice")}</Th>
                <Th numeric>{t("admin.creditNotes.columns.total")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((note) => (
                <tr
                  key={note.id}
                  onClick={() => void navigate(`/achats/avoirs/${note.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/achats/avoirs/${note.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {note.number}
                    </Link>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(note.credited_on)}</Td>
                  <Td className="font-semibold">{note.supplier.name}</Td>
                  <Td className="num max-[720px]:hidden">{note.invoice_number ?? "—"}</Td>
                  <Td numeric className="font-semibold whitespace-nowrap">
                    {formatMoney(note.total)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {notes.data && <Pager {...table.pager(notes.data.count)} />}
        </Card>
      )}
    </>
  );
}
