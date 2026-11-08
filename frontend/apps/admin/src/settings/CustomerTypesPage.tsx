import {
  createCustomerType,
  type CustomerType,
  deleteCustomerType,
  getListCustomerTypesQueryKey,
  updateCustomerType,
  useListCustomerTypes,
} from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, Input, PageHeader, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { fieldErrors } from "../lib/errors";

/** One row: its label (renamed in place), how many customers have it, and its actions. */
function TypeRow({ type, onChanged }: { type: CustomerType; onChanged: () => Promise<void> }) {
  const { t } = useTranslation();
  const [label, setLabel] = useState(type.label);
  const [error, setError] = useState<string>();

  const save = useMutation({
    mutationFn: (fields: { label?: string; is_active?: boolean }) => updateCustomerType(type.id, fields),
    onSuccess: async () => {
      setError(undefined);
      toast.success(t("admin.customerTypes.saved"));
      await onChanged();
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      setError(found.label ?? found.detail ?? t("admin.customerTypes.error"));
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteCustomerType(type.id),
    onSuccess: async () => {
      toast.success(t("admin.customerTypes.removed"));
      await onChanged();
    },
    onError: (failure) => toast.error(fieldErrors(failure).detail ?? t("admin.customerTypes.error")),
  });
  const renamed = label.trim() !== type.label;

  return (
    <tr>
      <Td>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label={t("admin.customerTypes.label")}
            value={label}
            maxLength={60}
            className="w-56"
            aria-invalid={error ? true : undefined}
            onChange={(event) => setLabel(event.target.value)}
          />
          {renamed && (
            <Button disabled={save.isPending} onClick={() => save.mutate({ label: label.trim() })}>
              {t("admin.customerTypes.save")}
            </Button>
          )}
        </div>
        {error && (
          <p role="alert" className="mt-1 text-[0.8rem] text-bad">
            {error}
          </p>
        )}
      </Td>
      <Td numeric>{type.customer_count}</Td>
      <Td>
        <Pill tone={type.is_active ? "good" : "neutral"}>
          {type.is_active ? t("admin.customerTypes.active") : t("admin.customerTypes.inactive")}
        </Pill>
      </Td>
      <Td className="text-end whitespace-nowrap">
        <Button variant="ghost" disabled={save.isPending} onClick={() => save.mutate({ is_active: !type.is_active })}>
          {type.is_active ? t("admin.customerTypes.deactivate") : t("admin.customerTypes.activate")}
        </Button>
        <Button
          variant="ghost"
          disabled={remove.isPending || type.customer_count > 0}
          title={type.customer_count > 0 ? t("admin.customerTypes.removeBlocked") : undefined}
          onClick={() => remove.mutate()}
        >
          {t("admin.customerTypes.remove")}
        </Button>
      </Td>
    </tr>
  );
}

/** "Paramètres › Types de clients" (D-283): the list the customer form and the customers filter offer. */
export function CustomerTypesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const query = useListCustomerTypes();
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string>();
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListCustomerTypesQueryKey() });

  const create = useMutation({
    mutationFn: () => createCustomerType({ label: label.trim() }),
    onSuccess: async () => {
      setLabel("");
      setError(undefined);
      toast.success(t("admin.customerTypes.created"));
      await refresh();
    },
    onError: (failure) => setError(fieldErrors(failure).label ?? t("admin.customerTypes.error")),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (label.trim()) create.mutate();
  };

  return (
    <>
      <PageHeader eyebrow={t("admin.settings.company")} title={t("admin.customerTypes.title")} />
      <p className="text-ink-2">{t("admin.customerTypes.intro")}</p>
      <Link to="/parametres" className="mb-4 inline-block text-[0.9rem] font-semibold text-sea hover:underline">
        {t("admin.customerTypes.back")}
      </Link>
      <Card className="flex flex-col gap-4">
        <form onSubmit={submit} className="flex flex-wrap items-start gap-2">
          <div>
            <Input
              aria-label={t("admin.customerTypes.newLabel")}
              placeholder={t("admin.customerTypes.newLabel")}
              value={label}
              maxLength={60}
              className="w-64"
              aria-invalid={error ? true : undefined}
              onChange={(event) => setLabel(event.target.value)}
            />
            {error && (
              <p role="alert" className="mt-1 text-[0.8rem] text-bad">
                {error}
              </p>
            )}
          </div>
          <Button type="submit" variant="primary" disabled={!label.trim() || create.isPending}>
            {t("admin.customerTypes.add")}
          </Button>
        </form>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.customerTypes.label")}</Th>
              <Th numeric>{t("admin.customerTypes.customers")}</Th>
              <Th>{t("admin.customerTypes.status")}</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {(query.data ?? []).map((type) => (
              <TypeRow key={`${type.id}-${type.label}`} type={type} onChanged={refresh} />
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}
