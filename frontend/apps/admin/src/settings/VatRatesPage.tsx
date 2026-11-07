import {
  createVatRate,
  deleteVatRate,
  getListVatRatesQueryKey,
  updateVatRate,
  useListVatRates,
  type VatRate,
} from "@frutti/api";
import { parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, Input, PageHeader, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { fieldErrors } from "../lib/errors";
import { rateAsTyped } from "../lib/lines";

function RateRow({ rate, onChanged }: { rate: VatRate; onChanged: () => Promise<void> }) {
  const { t } = useTranslation();
  const save = useMutation({
    mutationFn: (fields: { is_active: boolean }) => updateVatRate(rate.id, fields),
    onSuccess: async () => {
      toast.success(t("admin.vatRates.saved"));
      await onChanged();
    },
    onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.vatRates.error")),
  });
  const remove = useMutation({
    mutationFn: () => deleteVatRate(rate.id),
    onSuccess: async () => {
      toast.success(t("admin.vatRates.removed"));
      await onChanged();
    },
    onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.vatRates.error")),
  });
  return (
    <tr>
      <Td numeric className="font-semibold">
        {rateAsTyped(rate.rate)} %
      </Td>
      <Td>{rate.label || "—"}</Td>
      <Td>
        <Pill tone={rate.is_active ? "good" : "neutral"}>
          {rate.is_active ? t("admin.vatRates.active") : t("admin.vatRates.inactive")}
        </Pill>
      </Td>
      <Td className="text-ink-2">{rate.in_use ? t("admin.vatRates.used") : t("admin.vatRates.unused")}</Td>
      <Td className="text-end whitespace-nowrap">
        <Button variant="ghost" disabled={save.isPending} onClick={() => save.mutate({ is_active: !rate.is_active })}>
          {rate.is_active ? t("admin.vatRates.deactivate") : t("admin.vatRates.activate")}
        </Button>
        {!rate.in_use && (
          <Button variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("admin.vatRates.remove")}
          </Button>
        )}
      </Td>
    </tr>
  );
}

/** "Paramètres › TVA" (D-283): the VAT rates the product form offers. Saved documents keep their own rates. */
export function VatRatesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const query = useListVatRates();
  const [rate, setRate] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string>();
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListVatRatesQueryKey() });

  const create = useMutation({
    mutationFn: (value: string) => createVatRate({ rate: value, label: label.trim() }),
    onSuccess: async () => {
      setRate("");
      setLabel("");
      setError(undefined);
      toast.success(t("admin.vatRates.created"));
      await refresh();
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.vatRates.error")),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = parseDecimalInput(rate.trim(), 2);
    if (!value) {
      setError(t("admin.vatRates.error"));
      return;
    }
    create.mutate(value);
  };

  return (
    <>
      <PageHeader eyebrow={t("admin.settings.company")} title={t("admin.vatRates.title")} />
      <p className="text-ink-2">{t("admin.vatRates.intro")}</p>
      <Link to="/parametres" className="mb-4 inline-block text-[0.9rem] font-semibold text-sea hover:underline">
        {t("admin.vatRates.back")}
      </Link>
      <Card className="flex flex-col gap-4">
        <form onSubmit={submit} className="flex flex-wrap items-start gap-2">
          <Input
            aria-label={t("admin.vatRates.newRate")}
            placeholder={t("admin.vatRates.newRate")}
            inputMode="decimal"
            value={rate}
            className="w-40"
            aria-invalid={error ? true : undefined}
            onChange={(event) => setRate(event.target.value)}
          />
          <Input
            aria-label={t("admin.vatRates.newLabel")}
            placeholder={t("admin.vatRates.newLabel")}
            value={label}
            maxLength={60}
            className="w-64"
            onChange={(event) => setLabel(event.target.value)}
          />
          <Button type="submit" variant="primary" disabled={!rate.trim() || create.isPending}>
            {t("admin.vatRates.add")}
          </Button>
          {error && (
            <p role="alert" className="basis-full text-[0.8rem] text-bad">
              {error}
            </p>
          )}
        </form>
        <Table>
          <thead>
            <tr>
              <Th numeric>{t("admin.vatRates.rate")}</Th>
              <Th>{t("admin.vatRates.label")}</Th>
              <Th>{t("admin.vatRates.status")}</Th>
              <Th>{t("admin.vatRates.usage")}</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {(query.data ?? []).map((row) => (
              <RateRow key={row.id} rate={row} onChanged={refresh} />
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}
