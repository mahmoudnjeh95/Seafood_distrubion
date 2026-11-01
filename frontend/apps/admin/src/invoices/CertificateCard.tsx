import {
  addWithholdingCertificateFile,
  type InvoiceDetail,
  recordWithholdingCertificate,
  voidWithholdingCertificate,
} from "@frutti/api";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Field, Input, MoneyInput, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { refreshAfterPayment, todayInput } from "../payments/shared";

/** The withholding certificate the customer gave for what they kept on this invoice (D-063). */
export function CertificateCard({ invoice, canWrite }: { invoice: InvoiceDetail; canWrite: boolean }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const certificate = invoice.certificate;
  const [number, setNumber] = useState("");
  const [issuedOn, setIssuedOn] = useState(todayInput());
  const [amount, setAmount] = useState(invoice.withholding_amount.replace(".", ","));
  const [errors, setErrors] = useState<Record<string, string>>({});

  const onError = (failure: unknown) => {
    const fromServer = fieldErrors(failure);
    if (Object.keys(fromServer).length > 0) setErrors(fromServer);
    else if (!(failure instanceof Error && failure.message === "invalid")) toast.error(t("admin.payments.cert.error"));
  };
  const done = async (message: string) => {
    setErrors({});
    toast.success(message);
    await refreshAfterPayment(queryClient);
  };

  const record = useMutation({
    mutationFn: () => {
      const value = parseDecimalInput(amount, 3);
      if (value === null) {
        setErrors({ amount: t("admin.payments.dialog.amountError") });
        return Promise.reject(new Error("invalid"));
      }
      return recordWithholdingCertificate(invoice.id, { number: number.trim(), issued_on: issuedOn, amount: value });
    },
    onSuccess: () => done(t("admin.payments.cert.saved")),
    onError,
  });
  const upload = useMutation({
    mutationFn: (file: File) => addWithholdingCertificateFile(certificate?.id ?? 0, { file }),
    onSuccess: () => done(t("admin.payments.cert.fileSaved")),
    onError,
  });
  const cancel = useMutation({
    mutationFn: () => voidWithholdingCertificate(certificate?.id ?? 0, { reason: t("admin.payments.cert.voidReason") }),
    onSuccess: () => done(t("admin.payments.cert.voided")),
    onError,
  });

  if (invoice.status !== "issued") return null;
  if (!certificate && !canWrite && Number(invoice.withholding_amount) <= 0) return null;

  return (
    <Card className="print:hidden">
      <CardTitle>{t("admin.payments.cert.title")}</CardTitle>
      {certificate ? (
        <div className="flex flex-col gap-3">
          <dl className="grid grid-cols-2 gap-3 text-[0.9rem]">
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.payments.cert.number")}</dt>
              <dd className="num font-semibold">{certificate.number}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.payments.cert.date")}</dt>
              <dd className="num">{formatDate(certificate.issued_on)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.payments.cert.amount")}</dt>
              <dd className="num">{formatMoney(certificate.amount)}</dd>
            </div>
          </dl>
          {certificate.file_url ? (
            <a
              href={certificate.file_url}
              target="_blank"
              rel="noreferrer"
              className="font-semibold text-sea hover:underline"
            >
              {t("admin.payments.cert.openFile")}
            </a>
          ) : (
            <p className="text-[0.88rem] text-ink-2">{t("admin.payments.cert.noFile")}</p>
          )}
          {canWrite && (
            <div className="flex flex-wrap items-center gap-3">
              <label className="text-[0.88rem] font-semibold text-sea">
                <span className="cursor-pointer hover:underline">{t("admin.payments.cert.addFile")}</span>
                <input
                  type="file"
                  accept="image/*,application/pdf"
                  className="sr-only"
                  aria-label={t("admin.payments.cert.addFile")}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) upload.mutate(file);
                    event.target.value = "";
                  }}
                />
              </label>
              <Button variant="ghost" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
                {t("admin.payments.cert.void")}
              </Button>
            </div>
          )}
          {errors.file && (
            <p role="alert" className="text-[0.85rem] text-bad">
              {errors.file}
            </p>
          )}
        </div>
      ) : canWrite ? (
        <div className="flex flex-col gap-3">
          <p className="text-[0.88rem] text-ink-2">
            {t("admin.payments.cert.hint", { amount: formatMoney(invoice.withholding_amount) })}
          </p>
          <Field label={t("admin.payments.cert.number")} htmlFor={`${formId}-n`} error={errors.number}>
            <Input
              id={`${formId}-n`}
              value={number}
              maxLength={50}
              onChange={(event) => setNumber(event.target.value)}
            />
          </Field>
          <Field label={t("admin.payments.cert.date")} htmlFor={`${formId}-d`} error={errors.issued_on}>
            <Input
              id={`${formId}-d`}
              type="date"
              value={issuedOn}
              onChange={(event) => setIssuedOn(event.target.value)}
            />
          </Field>
          <Field label={t("admin.payments.cert.amountLabel")} htmlFor={`${formId}-a`} error={errors.amount}>
            <MoneyInput
              id={`${formId}-a`}
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </Field>
          <div>
            <Button variant="primary" disabled={record.isPending} onClick={() => record.mutate()}>
              {t("admin.payments.cert.save")}
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-[0.88rem] text-ink-2">{t("admin.payments.cert.missing")}</p>
      )}
    </Card>
  );
}
