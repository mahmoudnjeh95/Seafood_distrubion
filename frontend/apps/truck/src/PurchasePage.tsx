import {
  ApiError,
  changeMyFieldPurchase,
  type MyFieldPurchase,
  type MyFieldPurchaseCreate,
  addMyFieldPurchasePaper,
  type PaymentTermsEnum,
  useListMyFieldPurchases,
  useListMyPurchaseCosts,
  useListMySuppliers,
  useListProducts,
} from "@frutti/api";
import { useSession } from "@frutti/auth";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  ConfirmButton,
  EmptyState,
  Field,
  Input,
  MoneyInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { useOnline } from "./offline";
import { PaidNow } from "./PaidNow";
import { blankPayLine, effectiveLines, hasPaper, type PaidMode, type PayLine } from "./purchasePay";
import { PaperPhotoInput } from "./PaperPhotoInput";
import { dueDateOn, lineAmount, purchaseTotals } from "./purchase";
import { sendError } from "./sendError";
import { sendOrKeep } from "./sendOrKeep";
import { sendPurchase } from "./sendPurchase";
import { StickyAction } from "./StickyAction";
import { sendWaiting } from "./sync";
import { newUuid } from "./uuid";

type Line = { key: number; product: string; newName: string; kilos: string; price: string; isNew: boolean };

let nextKey = 0;
const blankLine = (): Line => {
  nextKey += 1;
  return { key: nextKey, product: "", newName: "", kilos: "", price: "", isNew: false };
};
// The API writes "20.250"; people here write "20,250". Both are read back by parseDecimalInput.
const asTyped = (value: string) => value.replace(".", ",");
const TERMS: PaymentTermsEnum[] = ["cash", "days", "month_end"];

function todayInTunis(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Tunis" }).format(new Date());
}

/** "Achat au port": a new purchase, or one already sent (`/achats/:id`) the office has not decided yet. */
export function PurchasePage() {
  const { t } = useTranslation();
  const session = useSession();
  const { purchaseId } = useParams();
  const purchases = useListMyFieldPurchases({ query: { enabled: purchaseId !== undefined } });
  if (session.data?.can_buy !== true) {
    return <EmptyState illustration="fish" title={t("truck.purchase.notAllowed")} />;
  }
  if (purchaseId === undefined) return <PurchaseForm />;
  if (purchases.isLoading) return null;
  const purchase = purchases.data?.find((one) => String(one.id) === purchaseId);
  if (purchase === undefined || purchase.status !== "submitted") {
    return <EmptyState illustration="fish" title={t("truck.purchase.empty")} />;
  }
  return <PurchaseForm key={purchase.revision} purchase={purchase} />;
}

function PurchaseForm({ purchase }: { purchase?: MyFieldPurchase }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const online = useOnline();
  const suppliers = useListMySuppliers();
  const products = useListProducts({ status: "active" });

  const [supplier, setSupplier] = useState(purchase?.supplier ? String(purchase.supplier.id) : "");
  const [newSupplier, setNewSupplier] = useState(purchase !== undefined && purchase.supplier === null);
  const [supplierName, setSupplierName] = useState(purchase?.proposed_supplier ?? "");
  const [supplierPhone, setSupplierPhone] = useState(purchase?.proposed_supplier_phone ?? "");
  const [terms, setTerms] = useState<PaymentTermsEnum>(purchase?.terms ?? "cash");
  const [days, setDays] = useState(purchase && purchase.due_days > 0 ? String(purchase.due_days) : "");
  const [lines, setLines] = useState<Line[]>(() =>
    purchase
      ? purchase.lines.map((line) => ({
          ...blankLine(),
          product: line.product ? String(line.product.id) : "",
          newName: line.proposed_product,
          isNew: line.product === null,
          kilos: asTyped(line.declared_quantity),
          price: asTyped(line.unit_cost),
        }))
      : [blankLine()],
  );
  // What was given now (D-192): none, a part (typed lines) or all (one line for the total).
  const [payLines, setPayLines] = useState<PayLine[]>(() =>
    (purchase?.payments ?? []).map((payment) => ({
      ...blankPayLine(payment.method, asTyped(payment.amount)),
      reference: payment.reference,
      cashOn: payment.cash_on ?? "",
    })),
  );
  const [payMode, setPayMode] = useState<PaidMode>(() => {
    if (purchase === undefined || purchase.payments.length === 0) return "none";
    const sum = purchase.payments.reduce((acc, payment) => acc + Number(payment.amount), 0);
    const total = purchase.lines.reduce(
      (acc, line) => acc + Number(line.declared_quantity) * Number(line.unit_cost),
      0,
    );
    return purchase.payments.length === 1 && Math.abs(sum - total) < 0.0005 ? "all" : "part";
  });
  const [paper, setPaper] = useState(purchase?.supplier_reference ?? "");
  const [note, setNote] = useState(purchase?.notes ?? "");
  // A photo of the supplier's paper (optional, D-159); on a purchase already sent, a new one replaces it.
  const [paperPhoto, setPaperPhoto] = useState<File | undefined>(undefined);
  const [uuid, setUuid] = useState(newUuid);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const costs = useListMyPurchaseCosts(
    { supplier: Number(supplier) },
    { query: { enabled: supplier !== "" && !newSupplier } },
  );
  const lastPrice = (productId: string) =>
    costs.data?.find((cost) => String(cost.product_id) === productId)?.unit_cost ?? null;

  const setLine = (key: number, change: Partial<Line>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...change } : line)));

  const dayCount = terms === "cash" ? 0 : Number(days || "0");
  const lineSums = lines.map((line) => ({ kilos: line.kilos, price: line.price }));
  const purchaseTotal = purchaseTotals(lineSums, []).total;
  const given = effectiveLines(payMode, payLines, purchaseTotal);
  const totals = purchaseTotals(
    lineSums,
    given.map((line) => line.amount),
  );
  const supplierReady = newSupplier ? supplierName.trim() !== "" : supplier !== "";
  const linesReady =
    lines.length > 0 &&
    lines.every(
      (line) =>
        (line.isNew ? line.newName.trim() !== "" : line.product !== "") && lineAmount(line.kilos, line.price) !== null,
    );
  const moneyReady = given.every(
    (line) =>
      parseDecimalInput(line.amount.trim(), 3) !== null &&
      Number(parseDecimalInput(line.amount.trim(), 3)) > 0 &&
      (!hasPaper(line.method) || (line.reference.trim() !== "" && line.cashOn !== "")),
  );
  const daysReady = terms === "cash" || (Number.isInteger(dayCount) && dayCount >= (terms === "days" ? 1 : 0));
  const ready =
    supplierReady &&
    linesReady &&
    moneyReady &&
    !totals.overpaid &&
    daysReady &&
    !saving &&
    (purchase === undefined || online);

  /** What the purchase says, without the `client_uuid` that only a new one carries. */
  function payload(): Omit<MyFieldPurchaseCreate, "client_uuid"> {
    // Same payload shape as before: one line per sum given. The rest is left to the office (D-192).
    const payments: MyFieldPurchaseCreate["payments"] = given.map((line) => ({
      method: line.method,
      amount: parseDecimalInput(line.amount.trim(), 3) ?? "",
      ...(hasPaper(line.method) ? { reference: line.reference.trim(), cash_on: line.cashOn || null } : {}),
    }));
    return {
      supplier: newSupplier ? null : Number(supplier),
      proposed_supplier: newSupplier ? supplierName.trim() : "",
      proposed_supplier_phone: newSupplier ? supplierPhone.trim() : "",
      terms,
      due_days: dayCount,
      supplier_reference: paper.trim(),
      notes: note.trim(),
      lines: lines.map((line) => ({
        product: line.isNew ? null : Number(line.product),
        proposed_product: line.isNew ? line.newName.trim() : "",
        declared_quantity: parseDecimalInput(line.kilos.trim(), 3) ?? "",
        unit_cost: parseDecimalInput(line.price.trim(), 3) ?? "",
      })),
      payments,
    };
  }

  const label = () =>
    newSupplier ? supplierName.trim() : (suppliers.data?.find((one) => String(one.id) === supplier)?.name ?? "");

  const save = async () => {
    setSaving(true);
    setError("");
    const changes = payload();
    try {
      if (purchase) {
        await changeMyFieldPurchase(purchase.id, { ...changes, revision: purchase.revision });
        if (paperPhoto) await addMyFieldPurchasePaper(purchase.id, { paper: paperPhoto });
        toast.success(t("truck.purchase.changed"));
      } else {
        const data: MyFieldPurchaseCreate = { ...changes, client_uuid: uuid };
        const outcome = await sendOrKeep(
          {
            kind: "purchase",
            uuid,
            createdAt: new Date().toISOString(),
            label: label(),
            data,
            paper: paperPhoto,
            status: "pending",
            error: "",
          },
          () => sendPurchase(data, paperPhoto),
        );
        toast.success(t(outcome.kept ? "truck.purchase.kept" : "truck.purchase.sent"));
        setUuid(newUuid());
        void sendWaiting(queryClient);
      }
      void queryClient.invalidateQueries();
      void navigate("/achats");
    } catch (failure) {
      const conflict = failure instanceof ApiError && JSON.stringify(failure.body ?? "").includes("revision");
      setError(
        conflict
          ? t("truck.purchase.conflict")
          : t("truck.purchase.failed", { why: sendError(failure, t("truck.closing.failed")) }),
      );
    } finally {
      setSaving(false);
    }
  };

  const select = (
    id: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    options: { value: string; label: string }[],
  ) => (
    <Field label={label} htmlFor={id}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className="text-lg">
          <SelectValue placeholder={t("truck.purchase.choose")} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );

  return (
    <div className="space-y-4">
      <h2>{purchase ? t("truck.purchase.editTitle", { number: purchase.number }) : t("truck.purchase.title")}</h2>

      <Card className="space-y-3">
        {newSupplier ? (
          <>
            <Field label={t("truck.purchase.supplierName")} htmlFor="purchase-supplier-name">
              <Input
                id="purchase-supplier-name"
                className="text-lg"
                value={supplierName}
                onChange={(event) => setSupplierName(event.target.value)}
              />
            </Field>
            <Field label={t("truck.purchase.supplierPhone")} htmlFor="purchase-supplier-phone">
              <Input
                id="purchase-supplier-phone"
                inputMode="tel"
                value={supplierPhone}
                onChange={(event) => setSupplierPhone(event.target.value)}
              />
            </Field>
          </>
        ) : (
          select(
            "purchase-supplier",
            t("truck.purchase.supplier"),
            supplier,
            setSupplier,
            (suppliers.data ?? []).map((one) => ({ value: String(one.id), label: one.name })),
          )
        )}
        <Button variant="ghost" onClick={() => setNewSupplier(!newSupplier)}>
          {newSupplier ? t("truck.purchase.fromList") : t("truck.purchase.newSupplier")}
        </Button>
      </Card>

      <Card className="space-y-4">
        <h2>{t("truck.purchase.products")}</h2>
        {lines.map((line, index) => {
          const amount = lineAmount(line.kilos, line.price);
          const last = line.isNew || line.product === "" ? null : lastPrice(line.product);
          return (
            <div
              key={line.key}
              role="group"
              aria-label={`${t("truck.purchase.product")} ${index + 1}`}
              className="space-y-2 border-b border-line pb-4"
            >
              {line.isNew ? (
                <Field label={t("truck.purchase.productName")} htmlFor={`purchase-new-${line.key}`}>
                  <Input
                    id={`purchase-new-${line.key}`}
                    className="text-lg"
                    value={line.newName}
                    onChange={(event) => setLine(line.key, { newName: event.target.value })}
                  />
                </Field>
              ) : (
                select(
                  `purchase-product-${line.key}`,
                  t("truck.purchase.product"),
                  line.product,
                  (value) => setLine(line.key, { product: value }),
                  (products.data ?? []).map((product) => ({ value: String(product.id), label: product.name })),
                )
              )}
              <Button variant="ghost" onClick={() => setLine(line.key, { isNew: !line.isNew })}>
                {line.isNew ? t("truck.purchase.fromList") : t("truck.purchase.newProduct")}
              </Button>
              <div className="grid grid-cols-2 gap-3">
                <Field label={t("truck.purchase.kilos")} htmlFor={`purchase-kilos-${line.key}`}>
                  <Input
                    id={`purchase-kilos-${line.key}`}
                    inputMode="decimal"
                    className="text-xl"
                    value={line.kilos}
                    onChange={(event) => setLine(line.key, { kilos: event.target.value })}
                  />
                </Field>
                <Field label={t("truck.purchase.price")} htmlFor={`purchase-price-${line.key}`}>
                  <MoneyInput
                    id={`purchase-price-${line.key}`}
                    inputMode="decimal"
                    className="text-xl"
                    value={line.price}
                    onChange={(event) => setLine(line.key, { price: event.target.value })}
                  />
                </Field>
              </div>
              {last === null ? null : (
                <p className="text-sm text-ink-2">{t("truck.purchase.lastPrice", { price: formatMoney(last) })}</p>
              )}
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold">
                  {amount === null ? "" : t("truck.purchase.lineAmount", { amount: formatMoney(amount) })}
                </span>
                {lines.length > 1 ? (
                  <Button
                    variant="ghost"
                    onClick={() => setLines((current) => current.filter((other) => other.key !== line.key))}
                  >
                    {t("truck.purchase.removeProduct")}
                  </Button>
                ) : null}
              </div>
            </div>
          );
        })}
        <Button size="lg" onClick={() => setLines((current) => [...current, blankLine()])}>
          {t("truck.purchase.addProduct")}
        </Button>
      </Card>

      <Card className="space-y-3">
        <h2>{t("truck.purchase.deal")}</h2>
        <div className="grid grid-cols-3 gap-2">
          {TERMS.map((choice) => (
            <Button
              key={choice}
              variant={terms === choice ? "primary" : "secondary"}
              className="py-3"
              onClick={() => setTerms(choice)}
            >
              {t(`truck.purchase.terms.${choice}`)}
            </Button>
          ))}
        </div>
        {terms === "cash" ? null : (
          <Field label={t("truck.purchase.days")} htmlFor="purchase-days">
            <Input
              id="purchase-days"
              inputMode="numeric"
              className="text-xl"
              value={days}
              onChange={(event) => setDays(event.target.value)}
            />
          </Field>
        )}
        {daysReady ? (
          <p className="font-semibold text-ink-2">
            {t("truck.purchase.due", {
              date: formatDate(dueDateOn(purchase?.bought_on ?? todayInTunis(), terms, dayCount)),
            })}
          </p>
        ) : null}
      </Card>

      <PaidNow
        mode={payMode}
        lines={payLines}
        total={totals.total}
        paid={totals.paid}
        rest={totals.rest}
        overpaid={totals.overpaid}
        onMode={setPayMode}
        onLines={setPayLines}
      />

      <Card className="space-y-3">
        <Field label={t("truck.purchase.paper")} htmlFor="purchase-paper">
          <Input id="purchase-paper" value={paper} onChange={(event) => setPaper(event.target.value)} />
        </Field>
        <PaperPhotoInput value={paperPhoto} onChange={setPaperPhoto} alreadyJoined={purchase?.has_paper === true} />
        <Field label={t("truck.purchase.note")} htmlFor="purchase-note">
          <Input id="purchase-note" value={note} onChange={(event) => setNote(event.target.value)} />
        </Field>
      </Card>

      {purchase !== undefined && !online ? <p className="text-warn">{t("truck.purchase.needNetwork")}</p> : null}
      {error === "" ? null : <p className="text-bad">{error}</p>}
      <StickyAction>
        <ConfirmButton
          size="lg"
          variant="primary"
          className="py-4 text-lg"
          disabled={!ready}
          rows={[
            [t("truck.purchase.total"), formatMoney(totals.total)],
            [t("truck.purchase.paid"), formatMoney(totals.paid)],
            [t("truck.purchase.rest"), formatMoney(totals.rest)],
          ]}
          onConfirm={() => void save()}
        >
          {purchase ? t("truck.purchase.save") : t("truck.purchase.send")}
        </ConfirmButton>
      </StickyAction>
    </div>
  );
}
