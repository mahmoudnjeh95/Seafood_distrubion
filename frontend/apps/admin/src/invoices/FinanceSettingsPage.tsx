import {
  type CreditPolicyEnum,
  type FinanceSettingsOverview,
  saveFinanceSettings,
  useGetFinanceSettings,
} from "@frutti/api";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Field,
  Input,
  MoneyInput,
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router";

import { fieldErrors } from "../lib/errors";
import { plainRate, toInput } from "./shared";

function SettingsForm({ overview }: { overview: FinanceSettingsOverview }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const current = overview.in_force;
  const [vatRate, setVatRate] = useState(toInput(current.vat_rate));
  const [stamp, setStamp] = useState(toInput(current.fiscal_stamp));
  const [withholding, setWithholding] = useState(toInput(current.withholding_rate));
  const [includeVat, setIncludeVat] = useState(current.prices_include_vat);
  const [creditPolicy, setCreditPolicy] = useState<CreditPolicyEnum>(current.credit_policy);
  const [validFrom, setValidFrom] = useState("");
  const [legalName, setLegalName] = useState(current.legal_name);
  const [address, setAddress] = useState(current.address);
  const [phone, setPhone] = useState(current.phone);
  const [taxId, setTaxId] = useState(current.tax_id);
  const [tradeRegister, setTradeRegister] = useState(current.trade_register);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () => {
      const found: Record<string, string> = {};
      const rate = parseDecimalInput(vatRate, 2);
      const rateWithholding = parseDecimalInput(withholding, 2);
      const stampValue = parseDecimalInput(stamp, 3);
      if (rate === null) found.vat_rate = t("admin.financeSettings.rateError");
      if (rateWithholding === null) found.withholding_rate = t("admin.financeSettings.rateError");
      if (stampValue === null) found.fiscal_stamp = t("admin.financeSettings.moneyError");
      if (Object.keys(found).length > 0 || rate === null || rateWithholding === null || stampValue === null) {
        setErrors(found);
        return Promise.reject(new Error("invalid"));
      }
      return saveFinanceSettings({
        valid_from: validFrom || null,
        vat_rate: rate,
        fiscal_stamp: stampValue,
        prices_include_vat: includeVat,
        withholding_rate: rateWithholding,
        credit_policy: creditPolicy,
        legal_name: legalName.trim(),
        address: address.trim(),
        phone: phone.trim(),
        tax_id: taxId.trim(),
        trade_register: tradeRegister.trim(),
      });
    },
    onSuccess: async () => {
      setErrors({});
      setValidFrom("");
      toast.success(t("admin.financeSettings.saved"));
      await queryClient.invalidateQueries({
        predicate: (query) =>
          typeof query.queryKey[0] === "string" && query.queryKey[0].startsWith("/api/v1/finance-settings"),
      });
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      if (Object.keys(fromServer).length > 0) setErrors(fromServer);
      else if (!(failure instanceof Error && failure.message === "invalid"))
        toast.error(t("admin.financeSettings.error"));
    },
  });

  const mayEdit = overview.may_edit;
  const field = (key: string, label: string, value: string, set: (value: string) => void, hint?: string) => {
    const Control = key === "fiscal_stamp" ? MoneyInput : Input;
    return (
      <Field label={label} htmlFor={`${formId}-${key}`} error={errors[key]}>
        <Control
          id={`${formId}-${key}`}
          value={value}
          disabled={!mayEdit}
          inputMode={["vat_rate", "fiscal_stamp", "withholding_rate"].includes(key) ? "decimal" : undefined}
          onChange={(event) => set(event.target.value)}
          aria-invalid={errors[key] ? true : undefined}
          autoComplete="off"
        />
        {hint && <p className="text-[0.78rem] text-ink-2">{hint}</p>}
      </Field>
    );
  };

  return (
    <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] items-start gap-4 max-[1000px]:grid-cols-1">
      <Card>
        <CardTitle>{t("admin.financeSettings.rules")}</CardTitle>
        {!mayEdit && <p className="mb-3 text-[0.9rem] text-ink-2">{t("admin.financeSettings.readOnly")}</p>}
        <div className="flex flex-col gap-4">
          {field(
            "vat_rate",
            t("admin.financeSettings.vatRate"),
            vatRate,
            setVatRate,
            t("admin.financeSettings.vatHint"),
          )}
          {field(
            "fiscal_stamp",
            t("admin.financeSettings.stamp"),
            stamp,
            setStamp,
            t("admin.financeSettings.stampHint"),
          )}
          <label className="flex items-start gap-2.5">
            <input
              type="checkbox"
              className="mt-1 size-4 accent-sea"
              checked={includeVat}
              disabled={!mayEdit}
              onChange={(event) => setIncludeVat(event.target.checked)}
            />
            <span>
              <span className="font-semibold">{t("admin.financeSettings.pricesIncludeVat")}</span>
              <span className="block text-[0.82rem] text-ink-2">{t("admin.financeSettings.pricesHint")}</span>
            </span>
          </label>
          {field(
            "withholding_rate",
            t("admin.financeSettings.withholdingRate"),
            withholding,
            setWithholding,
            t("admin.financeSettings.withholdingHint"),
          )}
          <Field
            label={t("admin.payments.policy.label")}
            htmlFor={`${formId}-credit-policy`}
            error={errors.credit_policy}
          >
            <Select
              value={creditPolicy}
              onValueChange={(value) => setCreditPolicy(value as CreditPolicyEnum)}
              disabled={!mayEdit}
            >
              <SelectTrigger id={`${formId}-credit-policy`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(["block", "approval", "warn"] as const).map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`admin.payments.policy.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[0.78rem] text-ink-2">{t("admin.payments.policy.hint")}</p>
          </Field>
          <hr className="border-line" />
          <p className="text-[0.85rem] font-semibold">{t("admin.financeSettings.seller")}</p>
          {field("legal_name", t("admin.financeSettings.legalName"), legalName, setLegalName)}
          {field("address", t("admin.financeSettings.address"), address, setAddress)}
          {field("phone", t("admin.financeSettings.phone"), phone, setPhone)}
          {field("tax_id", t("admin.financeSettings.taxId"), taxId, setTaxId)}
          {field("trade_register", t("admin.financeSettings.tradeRegister"), tradeRegister, setTradeRegister)}
          <Field
            label={t("admin.financeSettings.validFrom")}
            htmlFor={`${formId}-valid-from`}
            error={errors.valid_from}
          >
            <Input
              id={`${formId}-valid-from`}
              type="date"
              value={validFrom}
              disabled={!mayEdit}
              onChange={(event) => setValidFrom(event.target.value)}
            />
            <p className="text-[0.78rem] text-ink-2">{t("admin.financeSettings.validFromHint")}</p>
          </Field>
          {mayEdit && (
            <div>
              <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>
                {save.isPending ? t("admin.financeSettings.saving") : t("admin.financeSettings.save")}
              </Button>
            </div>
          )}
        </div>
      </Card>

      <Card>
        <CardTitle>{t("admin.financeSettings.history")}</CardTitle>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.financeSettings.from")}</Th>
              <Th numeric>{t("admin.financeSettings.columnVat")}</Th>
              <Th numeric>{t("admin.financeSettings.columnStamp")}</Th>
              <Th numeric>{t("admin.financeSettings.columnWithholding")}</Th>
            </tr>
          </thead>
          <tbody>
            {overview.history.map((version) => (
              <tr key={version.id}>
                <Td className="num whitespace-nowrap">
                  {formatDate(version.valid_from)}
                  {version.id === current.id && (
                    <span className="block text-[0.75rem] text-ink-2">{t("admin.financeSettings.inForce")}</span>
                  )}
                </Td>
                <Td numeric>
                  {plainRate(version.vat_rate)} %
                  <span className="block text-[0.75rem] text-ink-2">
                    {version.prices_include_vat
                      ? t("admin.financeSettings.included")
                      : t("admin.financeSettings.onTop")}
                  </span>
                </Td>
                <Td numeric className="whitespace-nowrap">
                  {formatMoney(version.fiscal_stamp)}
                </Td>
                <Td numeric>{plainRate(version.withholding_rate)} %</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}

/** "Paramètres financiers": VAT, fiscal stamp, withholding and the seller printed on invoices. Owner edits. */
export function FinanceSettingsPage() {
  const { t } = useTranslation();
  const query = useGetFinanceSettings();
  return (
    <>
      <Link to="/factures" className="text-[0.85rem] font-semibold text-sea hover:underline">
        {t("admin.invoices.back")}
      </Link>
      <PageHeader eyebrow={t("admin.invoices.title")} title={t("admin.financeSettings.title")} />
      <p className="text-ink-2">{t("admin.financeSettings.intro")}</p>
      {query.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : query.data ? (
        <SettingsForm overview={query.data} />
      ) : (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      )}
    </>
  );
}
