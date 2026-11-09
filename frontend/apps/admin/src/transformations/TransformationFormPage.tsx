import {
  createTransformation,
  type TransformationWrite,
  useGetBatch,
  useListProductBatches,
  useListProducts,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Field,
  Input,
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { Link, Navigate, useNavigate, useOutletContext, useSearchParams } from "react-router";

import { fieldErrors } from "../lib/errors";
import { idFrom } from "../purchasing/shared";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";

type Errors = Record<string, string>;

/** The cost per kg of the new lot, as the server works it out: (kg taken × cost + fee) / kg obtained. */
function newCost(taken: string | null, cost: string | undefined, fee: string | null, obtained: string | null) {
  if (!taken || !cost || !obtained || Number(obtained) <= 0) return null;
  const value = (Number(taken) * Number(cost) + Number(fee ?? "0")) / Number(obtained);
  return Number.isFinite(value) ? value.toFixed(3) : null;
}

/** A new transformation (D-301): kilos of one lot cleaned, filleted or downgraded into a new lot. */
export function TransformationFormPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const formId = useId();
  const [params] = useSearchParams();
  const fromLot = idFrom(params.get("lot"));
  const given = useGetBatch(fromLot ?? 0, { query: { enabled: fromLot !== null } });
  const products = useListProducts({ status: "active" });
  const [sourceProduct, setSourceProduct] = useState("");
  const shownProduct = sourceProduct || (given.data ? String(given.data.product.id) : "");
  const lots = useListProductBatches(Number(shownProduct), { query: { enabled: shownProduct !== "" } });
  const [lotChoice, setLotChoice] = useState("");
  const firstOfGiven = (lots.data ?? []).find((row) => row.batch_id === fromLot);
  const shownLot = lotChoice || (firstOfGiven ? `${firstOfGiven.batch_id}-${firstOfGiven.location_id}` : "");
  const picked = (lots.data ?? []).find((row) => `${row.batch_id}-${row.location_id}` === shownLot);
  const [outputProduct, setOutputProduct] = useState("");
  const [taken, setTaken] = useState("");
  const [obtained, setObtained] = useState("");
  const [fee, setFee] = useState("");
  const [feeNote, setFeeNote] = useState("");
  const [useBy, setUseBy] = useState("");
  const [doneOn, setDoneOn] = useState(todayInTunis());
  const [errors, setErrors] = useState<Errors>({});
  const sourceCost = picked && given.data?.id === picked.batch_id ? given.data.unit_cost : undefined;
  const lotCost = useGetBatch(picked?.batch_id ?? 0, { query: { enabled: picked !== undefined } });
  const preview = newCost(
    parseDecimalInput(taken.trim(), 3),
    sourceCost ?? lotCost.data?.unit_cost,
    parseDecimalInput(fee.trim() || "0", 3),
    parseDecimalInput(obtained.trim(), 3),
  );

  const save = useMutation({
    mutationFn: (body: TransformationWrite) => createTransformation(body),
    onSuccess: async (made) => {
      toast.success(t("admin.transformations.form.saved", { number: made.number, lot: made.output_batch.number }));
      await queryClient.invalidateQueries({
        predicate: (query) =>
          ["/api/v1/stock", "/api/v1/batches", "/api/v1/transformations"].some((prefix) =>
            String(query.queryKey[0]).startsWith(prefix),
          ),
      });
      void navigate(`/stock/lots/${made.output_batch.id}`);
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      setErrors(Object.keys(found).length > 0 ? found : { detail: t("admin.transformations.form.error") });
    },
  });

  if (!canRecordReceipts(session)) return <Navigate to="/stock/transformations" replace />;

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!picked) found.source_batch = t("admin.transformations.form.required");
    if (!outputProduct) found.output_product = t("admin.transformations.form.required");
    setErrors(found);
    if (Object.keys(found).length > 0 || !picked) return;
    save.mutate({
      location: picked.location_id,
      source_batch: picked.batch_id,
      source_quantity: taken.trim().replace(",", "."),
      output_product: Number(outputProduct),
      output_quantity: obtained.trim().replace(",", "."),
      fee: fee.trim().replace(",", ".") || "0",
      fee_note: feeNote.trim(),
      use_by: useBy || null,
      done_on: doneOn,
    });
  }

  const id = (name: string) => `${formId}-${name}`;
  const productOptions = (products.data ?? []).map((one) => (
    <SelectItem key={one.id} value={String(one.id)}>
      {one.name}
    </SelectItem>
  ));

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.stock")} title={t("admin.transformations.form.title")} />
      <p className="text-[0.9rem] text-ink-2">{t("admin.transformations.form.hint")}</p>
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <Field label={t("admin.transformations.form.sourceProduct")} htmlFor={id("source_product")}>
            <Select
              value={shownProduct}
              onValueChange={(value) => {
                setSourceProduct(value);
                setLotChoice("");
              }}
            >
              <SelectTrigger id={id("source_product")}>
                <SelectValue placeholder={t("admin.transformations.form.choose")} />
              </SelectTrigger>
              <SelectContent>{productOptions}</SelectContent>
            </Select>
          </Field>
          <Field
            label={t("admin.transformations.form.lot")}
            htmlFor={id("lot")}
            error={errors.source_batch ?? errors.location}
          >
            <Select value={shownLot} onValueChange={setLotChoice}>
              <SelectTrigger id={id("lot")}>
                <SelectValue placeholder={t("admin.transformations.form.choose")} />
              </SelectTrigger>
              <SelectContent>
                {(lots.data ?? []).map((row) => (
                  <SelectItem key={`${row.batch_id}-${row.location_id}`} value={`${row.batch_id}-${row.location_id}`}>
                    {`${row.batch_number} · ${row.location_name} · ${row.supplier_name} · ${formatQuantity(row.quantity)}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.transformations.form.taken")} htmlFor={id("taken")} error={errors.source_quantity}>
            <Input
              id={id("taken")}
              inputMode="decimal"
              value={taken}
              onChange={(event) => setTaken(event.target.value)}
            />
          </Field>
          <Field label={t("admin.transformations.form.doneOn")} htmlFor={id("done_on")} error={errors.done_on}>
            <Input
              id={id("done_on")}
              type="date"
              max={todayInTunis()}
              value={doneOn}
              onChange={(event) => setDoneOn(event.target.value)}
            />
          </Field>
          <Field
            label={t("admin.transformations.form.outputProduct")}
            htmlFor={id("output_product")}
            error={errors.output_product}
          >
            <Select value={outputProduct} onValueChange={setOutputProduct}>
              <SelectTrigger id={id("output_product")}>
                <SelectValue placeholder={t("admin.transformations.form.choose")} />
              </SelectTrigger>
              <SelectContent>{productOptions}</SelectContent>
            </Select>
          </Field>
          <Field
            label={t("admin.transformations.form.obtained")}
            htmlFor={id("obtained")}
            error={errors.output_quantity}
          >
            <Input
              id={id("obtained")}
              inputMode="decimal"
              value={obtained}
              onChange={(event) => setObtained(event.target.value)}
            />
          </Field>
          <Field label={t("admin.transformations.form.fee")} htmlFor={id("fee")} error={errors.fee}>
            <Input
              id={id("fee")}
              inputMode="decimal"
              placeholder="0,000"
              value={fee}
              onChange={(event) => setFee(event.target.value)}
            />
          </Field>
          <Field label={t("admin.transformations.form.feeNote")} htmlFor={id("fee_note")}>
            <Input
              id={id("fee_note")}
              value={feeNote}
              maxLength={255}
              onChange={(event) => setFeeNote(event.target.value)}
            />
          </Field>
          <Field label={t("admin.transformations.form.useBy")} htmlFor={id("use_by")} error={errors.use_by}>
            <Input id={id("use_by")} type="date" value={useBy} onChange={(event) => setUseBy(event.target.value)} />
          </Field>
          <div className="flex flex-col justify-end">
            <p className="text-[0.78rem] font-semibold text-ink-2">{t("admin.transformations.form.newCost")}</p>
            <p className="num text-[1.2rem] font-bold">{preview ? `${formatMoney(preview)} / kg` : "—"}</p>
          </div>
        </Card>
        {errors.detail && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button asChild>
            <Link to="/stock/transformations">{t("admin.transformations.form.cancel")}</Link>
          </Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.transformations.form.save")}
          </Button>
        </div>
      </form>
    </>
  );
}
