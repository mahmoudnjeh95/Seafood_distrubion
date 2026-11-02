import { type DocumentRow, type DocumentToneEnum, type DocumentTypeEnum, useListDocuments } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  EmptyState,
  Field,
  Icon,
  Input,
  PageHeader,
  Pager,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SortTh,
  Table,
  type TableSort,
  Td,
  Th,
  toast,
  useTableView,
} from "@frutti/ui";
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { openPdf, PdfError, type PdfKind } from "../lib/pdf";
import { useDebounced } from "../lib/useDebounced";
import { addDays } from "../purchasing/shared";
import { DeliverDialog } from "../quotes/DeliverDialog";
import { canWriteQuotes } from "../quotes/shared";
import { todayInTunis } from "../receipts/shared";
import { type DocumentAction, isDanger, isMain, planOf, type RunResult } from "./actions";
import { NewDocumentDialog, type NewDocumentKind } from "./NewDocumentDialog";
import { buildTree, detailPath, flatLines, parseKey, PURCHASE_TYPES, SALES_TYPES, type TreeLine } from "./tree";

type Period = "month" | "quarter" | "year" | "all";
const PERIODS: Period[] = ["month", "quarter", "year", "all"];
const TONES: DocumentToneEnum[] = ["draft", "waiting", "done", "cancelled"];
const PILL_TONE = { draft: "neutral", waiting: "sea", done: "good", cancelled: "bad" } as const satisfies Record<
  DocumentToneEnum,
  string
>;

function Head({
  sortKey,
  sort,
  onSort,
  children,
  ...props
}: {
  sortKey: string;
  sort?: TableSort;
  onSort?: (key: string) => void;
  numeric?: boolean;
  className?: string;
  children: string;
}) {
  return onSort ? (
    <SortTh sortKey={sortKey} sort={sort ?? null} onSort={onSort} {...props}>
      {children}
    </SortTh>
  ) : (
    <Th {...props}>{children}</Th>
  );
}

function periodStart(period: Period): string | undefined {
  const today = todayInTunis();
  if (period === "month") return addDays(today, -30);
  if (period === "quarter") return addDays(today, -90);
  if (period === "year") return `${today.slice(0, 4)}-01-01`;
  return undefined;
}

// An action waiting for the person to confirm it (and give a reason when the services want one).
interface Asking {
  row: DocumentRow;
  action: DocumentAction;
  reason: "none" | "optional" | "required";
  run: (reason: string) => Promise<RunResult>;
}

/** "Documents" (P2-T11, D-102): every sales and purchasing document as chains, with what can be done next. */
export function DocumentsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canWrite = canWriteQuotes(session);
  const reasonId = useId();

  const [type, setType] = useState<DocumentTypeEnum | "">("");
  const [tone, setTone] = useState<DocumentToneEnum | "">("");
  const [period, setPeriod] = useState<Period>("month");
  const [view, setView] = useState<"tree" | "list">("tree");
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const query = useDebounced(search.trim());

  const [asking, setAsking] = useState<Asking | null>(null);
  const [reason, setReason] = useState("");
  const [askError, setAskError] = useState("");
  const [converting, setConverting] = useState<DocumentRow | null>(null);

  const [creating, setCreating] = useState(false);
  // The creation form opened in a window over this list (D-138); null while closed.
  const [newKind, setNewKind] = useState<NewDocumentKind | null>(null);

  const start = periodStart(period);
  // Type and status are filtered here, so the chips can count every type of the period.
  const documents = useListDocuments(
    { ...(start ? { date_from: start } : {}), ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const all = useMemo(() => documents.data?.results ?? [], [documents.data]);
  const shown = useMemo(
    () => all.filter((row) => (!type || row.type === type) && (!tone || row.tone === tone)),
    [all, type, tone],
  );
  const filtering = type !== "" || tone !== "";
  const asTree = view === "tree" && !filtering;
  const lines: TreeLine[] = asTree ? buildTree(shown, collapsed) : flatLines(shown);
  // The flat list can be sorted and paged; the tree keeps documents under the one they come from.
  const table = useTableView(lines, {
    number: ({ row }) => row.number,
    type: ({ row }) => row.type,
    partner: ({ row }) => row.partner_name,
    date: ({ row }) => row.date,
    amount: ({ row }) => Number(row.amount),
    status: ({ row }) => row.status_label,
  });
  const shownLines = asTree ? lines : table.rows;
  const byKey = useMemo(() => new Map(all.map((row) => [row.key, row])), [all]);
  const childrenOf = useMemo(() => {
    const map = new Map<string, DocumentRow[]>();
    for (const row of all) {
      const parent = row.parents.find((key) => byKey.has(key));
      if (parent) map.set(parent, [...(map.get(parent) ?? []), row]);
    }
    return map;
  }, [all, byKey]);

  const refresh = () => queryClient.invalidateQueries();

  const finished = async (action: DocumentAction, done: RunResult) => {
    if (done.pendingCredit) toast.warning(t("admin.payments.sale.pendingToast"));
    else if (action === "to_invoice") toast.success(t("admin.docHub.done.to_invoice"));
    else if (action === "delete") toast.success(t("admin.docHub.done.delete"));
    else toast.success(t(`admin.docHub.done.${action as "send"}`, { number: done.number ?? "" }));
    await refresh();
    if (done.open) void navigate(done.open);
  };

  const run = useMutation({
    mutationFn: ({ ask, text }: { ask: Asking; text: string }) => ask.run(text),
    onSuccess: async (done, { ask }) => {
      setAsking(null);
      await finished(ask.action, done);
    },
    onError: (failure) => {
      setAskError(Object.values(fieldErrors(failure)).join(" ") || t("admin.docHub.failed"));
    },
  });

  const act = (row: DocumentRow, action: DocumentAction) => {
    const plan = planOf(row, action);
    if (plan === null) return;
    if (plan.kind === "page") void navigate(plan.to);
    else if (plan.kind === "to_sale") setConverting(row);
    else {
      setReason("");
      setAskError("");
      setAsking({ row, action, reason: plan.reason, run: plan.run });
    }
  };

  const confirmAsk = () => {
    if (!asking) return;
    const text = reason.trim();
    if (asking.reason === "required" && !text) {
      setAskError(t("admin.docHub.reasonRequired"));
      return;
    }
    run.mutate({ ask: asking, text });
  };

  const pdf = async (row: DocumentRow) => {
    try {
      await openPdf(row.pdf as PdfKind, row.id);
    } catch (error) {
      const message = error instanceof PdfError ? error.message : "";
      toast.error(
        message && !["timeout", "failed", "refused"].includes(message) && !message.startsWith("status ")
          ? message
          : t(message === "timeout" ? "admin.documents.slow" : "admin.documents.failed"),
      );
    }
  };

  const toggle = (key: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const numberOf = (row: DocumentRow) => row.number || t("admin.docHub.draftNumber");

  // Under the number: where the document came from, or (for a chain's start) what it became.
  const caption = (row: DocumentRow, depth: number) => {
    const parents = row.parents.map((key) => byKey.get(key)).filter((item) => item !== undefined);
    if (parents.length > 0 && (depth > 0 || !asTree)) {
      const others = depth > 0 ? parents.slice(1) : parents;
      if (others.length === 0) return null;
      return (
        <div className="text-[0.75rem] text-ink-2">
          {t("admin.docHub.fromSeveral", { list: others.map((item) => `${item.type} ${numberOf(item)}`).join(", ") })}
        </div>
      );
    }
    if (parents.length === 0 && row.parents.length > 0) {
      const [parentType] = parseKey(row.parents[0] ?? "");
      return (
        <div className="text-[0.75rem] text-ink-2">
          {t("admin.docHub.from", { type: parentType, number: t("admin.docHub.outside") })}
        </div>
      );
    }
    const kids = (childrenOf.get(row.key) ?? []).filter((kid) => kid.tone !== "cancelled");
    if (kids.length === 0) return null;
    const first = kids[0];
    return (
      <div className="text-[0.75rem] text-good">
        {t("admin.docHub.children", {
          type: first?.type ?? "",
          list: kids
            .slice(0, 3)
            .map((kid) => numberOf(kid))
            .join(", "),
        })}
      </div>
    );
  };

  const chip = (value: DocumentTypeEnum | "", label: string, count: number, hint?: string) => (
    <button
      key={value || "all"}
      type="button"
      aria-pressed={type === value}
      title={hint}
      onClick={() => setType(value)}
      className={cn(
        "inline-flex items-baseline gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-[0.85rem] text-ink",
        type === value && "border-sea bg-sea text-white",
      )}
    >
      <b className="font-bold">{value || label}</b>
      {value && <span className={cn("text-ink-2", type === value && "text-white/80")}>· {label}</span>}
      <span className={cn("num text-[0.75rem] text-ink-2", type === value && "text-white/80")}>{count}</span>
    </button>
  );
  const countOf = (value: DocumentTypeEnum) => all.filter((row) => row.type === value).length;

  const actionButton = (row: DocumentRow, action: DocumentAction) => (
    <button
      key={action}
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        act(row, action);
      }}
      className={cn(
        "rounded-[7px] border px-2.5 py-1 text-[0.8rem] font-semibold whitespace-nowrap",
        isMain(action)
          ? "border-sea bg-sea-soft text-sea hover:brightness-95"
          : isDanger(action)
            ? "border-line bg-surface text-bad hover:bg-bad-soft"
            : "border-line bg-surface text-ink-2 hover:bg-surface-2 hover:text-ink",
      )}
    >
      {t(`admin.docHub.actions.${action}`)}
    </button>
  );

  const newDocs: { key: NewDocumentKind; hint: string }[] = [
    { key: "quote", hint: "quoteHint" },
    { key: "sale", hint: "saleHint" },
    { key: "counter", hint: "counterHint" },
    { key: "order", hint: "orderHint" },
    { key: "receipt", hint: "receiptHint" },
    { key: "supplierInvoice", hint: "supplierInvoiceHint" },
  ];

  const askTitle =
    asking &&
    t(`admin.docHub.confirmTitle.${asking.action as "send"}`, {
      number: numberOf(asking.row),
    });
  const askBody =
    asking &&
    (asking.action === "cancel"
      ? t(asking.row.type === "BA" ? "admin.docHub.confirmBody.cancelOrder" : "admin.docHub.confirmBody.cancelSale")
      : t(`admin.docHub.confirmBody.${asking.action as "send"}`));

  // The tree keeps its own order, so only the flat list has sortable headers.
  const headProps = asTree ? {} : { sort: table.sort, onSort: table.toggleSort };

  return (
    <>
      <PageHeader eyebrow={session.organization.name} title={t("admin.docHub.title")}>
        {canWrite && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Icon name="plus" />
            {t("admin.docHub.add")}
          </Button>
        )}
      </PageHeader>
      <p className="text-ink-2">{canWrite ? t("admin.docHub.subtitle") : t("admin.docHub.readOnly")}</p>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">{chip("", t("admin.docHub.all"), all.length)}</div>
        <span className="text-[0.72rem] font-semibold tracking-[0.08em] text-ink-2 uppercase">
          {t("admin.docHub.salesGroup")}
        </span>
        <div className="flex flex-wrap gap-2">
          {SALES_TYPES.map((value) =>
            chip(value, t(`admin.docHub.shortTypes.${value}`), countOf(value), t(`admin.docHub.types.${value}`)),
          )}
        </div>
        <span className="text-[0.72rem] font-semibold tracking-[0.08em] text-ink-2 uppercase">
          {t("admin.docHub.purchasesGroup")}
        </span>
        <div className="flex flex-wrap gap-2">
          {PURCHASE_TYPES.map((value) =>
            chip(value, t(`admin.docHub.shortTypes.${value}`), countOf(value), t(`admin.docHub.types.${value}`)),
          )}
        </div>
      </div>

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.docHub.search")}
          placeholder={t("admin.docHub.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <Select
          value={tone || "all"}
          onValueChange={(value) => setTone(value === "all" ? "" : (value as DocumentToneEnum))}
        >
          <SelectTrigger aria-label={t("admin.docHub.toneFilter")} className="w-auto min-w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("admin.docHub.tones.all")}</SelectItem>
            {TONES.map((value) => (
              <SelectItem key={value} value={value}>
                {t(`admin.docHub.tones.${value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={period} onValueChange={(value) => setPeriod(value as Period)}>
          <SelectTrigger aria-label={t("admin.docHub.period")} className="w-auto min-w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((value) => (
              <SelectItem key={value} value={value}>
                {t(`admin.docHub.periods.${value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div role="group" aria-label={t("admin.docHub.view")} className="ms-auto flex rounded-control bg-surface-2 p-1">
          {(["tree", "list"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={view === value}
              onClick={() => setView(value)}
              className={cn(
                "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
                view === value && "bg-surface text-ink shadow-card",
              )}
            >
              {t(`admin.docHub.${value}`)}
            </button>
          ))}
        </div>
      </Card>

      {documents.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : documents.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : shown.length === 0 ? (
        filtering || query ? (
          <p className="text-ink-2">{t("admin.docHub.noMatch")}</p>
        ) : (
          <EmptyState illustration="fridge" title={t("admin.docHub.empty")}>
            {t("admin.docHub.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Head {...headProps} sortKey="number">
                  {t("admin.docHub.columns.number")}
                </Head>
                <Head {...headProps} sortKey="type">
                  {t("admin.docHub.columns.type")}
                </Head>
                <Head {...headProps} sortKey="partner">
                  {t("admin.docHub.columns.partner")}
                </Head>
                <Head {...headProps} sortKey="date" className="max-[720px]:hidden">
                  {t("admin.docHub.columns.date")}
                </Head>
                <Head {...headProps} sortKey="amount" numeric>
                  {t("admin.docHub.columns.amount")}
                </Head>
                <Head {...headProps} sortKey="status">
                  {t("admin.docHub.columns.status")}
                </Head>
                <Th>{t("admin.docHub.columns.actions")}</Th>
              </tr>
            </thead>
            <tbody>
              {shownLines.map(({ row, depth, childCount }) => (
                <tr key={row.key} className={cn("hover:bg-surface-2", depth > 0 && "bg-surface-2")}>
                  <Td className="whitespace-nowrap">
                    <div className="flex items-start gap-1.5" style={{ paddingInlineStart: `${depth * 1.4}rem` }}>
                      {depth > 0 ? (
                        <span aria-hidden className="mt-0.5 h-2.5 w-3 shrink-0 border-s border-b border-line" />
                      ) : asTree && childCount > 0 ? (
                        <button
                          type="button"
                          onClick={() => toggle(row.key)}
                          aria-expanded={!collapsed.has(row.key)}
                          aria-label={collapsed.has(row.key) ? t("admin.docHub.expand") : t("admin.docHub.collapse")}
                          className="w-3 text-[0.75rem] text-ink-2"
                        >
                          {collapsed.has(row.key) ? "▸" : "▾"}
                        </button>
                      ) : (
                        asTree && <span className="w-3" />
                      )}
                      <div>
                        <Link to={detailPath(row)} className="num font-semibold text-ink hover:underline">
                          {numberOf(row)}
                        </Link>
                        {caption(row, depth)}
                      </div>
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap">
                    <b>{row.type}</b>
                    <span className="ms-1 text-[0.85rem] text-ink-2 max-[720px]:hidden">
                      · {t(`admin.docHub.shortTypes.${row.type}`)}
                    </span>
                  </Td>
                  <Td>{row.partner_name}</Td>
                  <Td className="num whitespace-nowrap text-ink-2 max-[720px]:hidden">{formatDate(row.date)}</Td>
                  <Td numeric className="font-semibold whitespace-nowrap">
                    {formatMoney(row.amount)}
                  </Td>
                  <Td>
                    <Pill tone={PILL_TONE[row.tone]}>{row.status_label}</Pill>
                  </Td>
                  <Td>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {row.pdf && (
                        <button
                          type="button"
                          onClick={() => void pdf(row)}
                          aria-label={`${t("admin.documents.pdf")} ${numberOf(row)}`}
                          title={t("admin.documents.pdf")}
                          className="rounded-[7px] p-1 text-sea hover:bg-sea-soft"
                        >
                          <Icon name="receipt" />
                        </button>
                      )}
                      {(row.actions as DocumentAction[]).map((action) => actionButton(row, action))}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {!asTree && <Pager {...table.pager} />}
          <div className="flex flex-wrap justify-between gap-2 p-2 text-[0.82rem] text-ink-2">
            <span aria-live="polite">
              {t("admin.docHub.count", { count: shown.length })}
              {view === "tree" && filtering && ` · ${t("admin.docHub.treeNeedsAll")}`}
            </span>
            {documents.data?.truncated && (
              <span className="text-warn">
                {t("admin.docHub.truncated", { shown: all.length, count: documents.data.total })}
              </span>
            )}
          </div>
        </Card>
      )}

      <Dialog open={asking !== null} onOpenChange={(open) => !open && setAsking(null)}>
        <DialogContent>
          <DialogTitle>{askTitle}</DialogTitle>
          <DialogDescription>{askBody}</DialogDescription>
          {asking && asking.reason !== "none" && (
            <Field label={t("admin.docHub.reason")} htmlFor={reasonId}>
              <Input id={reasonId} value={reason} maxLength={255} onChange={(event) => setReason(event.target.value)} />
            </Field>
          )}
          {askError && (
            <p role="alert" className="text-[0.85rem] text-bad">
              {askError}
            </p>
          )}
          <DialogFooter>
            <Button onClick={() => setAsking(null)}>{t("admin.docHub.back")}</Button>
            <Button
              variant={asking && isDanger(asking.action) ? "danger" : "primary"}
              disabled={run.isPending}
              onClick={confirmAsk}
            >
              {asking ? t(`admin.docHub.actions.${asking.action}`) : t("admin.docHub.go")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DeliverDialog quoteId={converting?.id ?? null} onClose={() => setConverting(null)} />

      <NewDocumentDialog
        kind={newKind}
        title={newKind ? t(`admin.docHub.newDocs.${newKind as "quote"}`) : ""}
        onClose={() => setNewKind(null)}
      />

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogTitle>{t("admin.docHub.newTitle")}</DialogTitle>
          <DialogDescription>{t("admin.docHub.newBody")}</DialogDescription>
          <div className="flex flex-col gap-1.5">
            {newDocs.map((item, index) => (
              <div key={item.key} className="flex flex-col">
                {(index === 0 || index === 3) && (
                  <span className="mt-1 mb-1 text-[0.72rem] font-semibold tracking-[0.08em] text-ink-2 uppercase">
                    {t(index === 0 ? "admin.docHub.salesGroup" : "admin.docHub.purchasesGroup")}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setCreating(false);
                    setNewKind(item.key);
                  }}
                  className="flex flex-col items-start rounded-control border border-line bg-surface px-3 py-2 text-start hover:bg-surface-2"
                >
                  <span className="font-semibold">{t(`admin.docHub.newDocs.${item.key as "quote"}`)}</span>
                  <span className="text-[0.8rem] text-ink-2">
                    {t(`admin.docHub.newDocs.${item.hint as "quoteHint"}`)}
                  </span>
                </button>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
