import {
  createCustomer,
  type Customer,
  type CustomerContact,
  CustomerKindEnum,
  type CustomerWrite,
  updateCustomer,
} from "@frutti/api";
import { parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Icon,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { refreshCustomers } from "./shared";

type TextField =
  | "reference"
  | "name"
  | "tax_id"
  | "phone"
  | "email"
  | "address"
  | "city"
  | "notes"
  | "credit_limit"
  | "payment_terms_days";
type FormValues = Record<TextField, string> & { kind: CustomerKindEnum };
type ContactRow = Required<CustomerContact> & { key: number };
type Errors = Partial<Record<TextField | "kind" | "contacts" | "detail", string>>;

const EMPTY: FormValues = {
  reference: "",
  name: "",
  kind: CustomerKindEnum.restaurant,
  tax_id: "",
  phone: "",
  email: "",
  address: "",
  city: "",
  notes: "",
  credit_limit: "0",
  payment_terms_days: "0",
};

const CONTACT_FIELDS = [
  { field: "name", label: "admin.customers.form.contactName", placeholder: "admin.customers.form.name", type: "text" },
  {
    field: "role",
    label: "admin.customers.form.contactRole",
    placeholder: "admin.customers.form.contactRole",
    type: "text",
  },
  {
    field: "phone",
    label: "admin.customers.form.contactPhone",
    placeholder: "admin.customers.form.phone",
    type: "tel",
  },
  {
    field: "email",
    label: "admin.customers.form.contactEmail",
    placeholder: "admin.customers.form.email",
    type: "email",
  },
] as const;

// Gives each contact row a stable React key, also for rows not saved yet.
let nextKey = 0;
function contactRow(contact?: CustomerContact): ContactRow {
  nextKey += 1;
  return {
    key: nextKey,
    name: contact?.name ?? "",
    role: contact?.role ?? "",
    phone: contact?.phone ?? "",
    email: contact?.email ?? "",
  };
}

// The API writes "5000.000"; people here write "5000,000". Both are read back by parseDecimalInput.
const typed = (decimal: string) => decimal.replace(".", ",");

/** Create a customer (`customer` absent) or change one. Owners and managers only; the server checks it too. */
export function CustomerDialog({ customer, onDone }: { customer?: Customer; onDone: (saved?: Customer) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [values, setValues] = useState<FormValues>(
    customer
      ? {
          reference: customer.reference,
          name: customer.name,
          kind: customer.kind,
          tax_id: customer.tax_id,
          phone: customer.phone,
          email: customer.email,
          address: customer.address,
          city: customer.city,
          notes: customer.notes,
          credit_limit: typed(customer.credit_limit),
          payment_terms_days: String(customer.payment_terms_days),
        }
      : EMPTY,
  );
  const [contacts, setContacts] = useState<ContactRow[]>(() => customer?.contacts.map(contactRow) ?? []);
  const [errors, setErrors] = useState<Errors>({});

  const set = (field: TextField) => (value: string) => setValues((current) => ({ ...current, [field]: value }));
  const setContact = (key: number, field: keyof CustomerContact, value: string) =>
    setContacts((current) => current.map((row) => (row.key === key ? { ...row, [field]: value } : row)));

  const save = useMutation({
    mutationFn: (payload: CustomerWrite) => (customer ? updateCustomer(customer.id, payload) : createCustomer(payload)),
    onSuccess: async (saved) => {
      toast.success(t(customer ? "admin.customers.form.saved" : "admin.customers.form.created"));
      await refreshCustomers(queryClient);
      onDone(saved);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.customers.form.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!values.name.trim()) found.name = t("admin.customers.form.required");
    const limit = parseDecimalInput(values.credit_limit.trim() || "0", 3);
    if (limit === null || limit.startsWith("-")) found.credit_limit = t("admin.customers.form.invalidAmount");
    const days = parseDecimalInput(values.payment_terms_days.trim() || "0", 0);
    if (days === null || Number(days) < 0 || Number(days) > 365) {
      found.payment_terms_days = t("admin.customers.form.invalidDays");
    }
    // Blank rows are dropped; a row with something in it needs a name.
    const filled = contacts.filter((row) => row.name.trim() || row.role.trim() || row.phone.trim() || row.email.trim());
    if (filled.some((row) => !row.name.trim())) found.contacts = t("admin.customers.form.required");
    setErrors(found);
    if (Object.keys(found).length > 0 || limit === null || days === null) return;
    const trimmed = (field: TextField) => values[field].trim();
    const payload: CustomerWrite = {
      reference: trimmed("reference"),
      name: trimmed("name"),
      kind: values.kind,
      tax_id: trimmed("tax_id"),
      phone: trimmed("phone"),
      email: trimmed("email"),
      address: trimmed("address"),
      city: trimmed("city"),
      notes: trimmed("notes"),
      credit_limit: limit,
      payment_terms_days: Number(days),
      contacts: filled.map(({ name, role, phone, email }) => ({
        name: name.trim(),
        role: role.trim(),
        phone: phone.trim(),
        email: email.trim(),
      })),
    };
    save.mutate(payload);
  }

  function input(
    name: TextField,
    label: string,
    options: {
      hint?: string;
      type?: string;
      inputMode?: "decimal" | "numeric";
      className?: string;
      disabled?: boolean;
    } = {},
  ) {
    const id = `${formId}-${name}`;
    return (
      <Field label={label} htmlFor={id} error={errors[name]} className={options.className}>
        <Input
          id={id}
          name={name}
          type={options.type ?? "text"}
          inputMode={options.inputMode}
          value={values[name]}
          onChange={(event) => set(name)(event.target.value)}
          aria-invalid={errors[name] ? true : undefined}
          aria-describedby={options.hint ? `${id}-hint` : undefined}
          disabled={options.disabled}
          autoComplete="off"
        />
        {options.hint && (
          <p id={`${id}-hint`} className="text-[0.8rem] text-ink-2">
            {options.hint}
          </p>
        )}
      </Field>
    );
  }

  // The walk-in customer pays at once: the server refuses any credit, so the field is not offered.
  const walkIn = customer?.is_walk_in ?? false;

  return (
    <DialogContent className="w-[min(720px,calc(100vw-2rem))]">
      <DialogTitle>{t(customer ? "admin.customers.form.editTitle" : "admin.customers.form.createTitle")}</DialogTitle>
      <DialogDescription className="sr-only">
        {customer?.name ?? t("admin.customers.form.createTitle")}
      </DialogDescription>

      <form id={formId} onSubmit={submit} noValidate className="grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
        {input("name", t("admin.customers.form.name"))}
        {input("reference", t("admin.customers.form.reference"), {
          hint: customer ? undefined : t("admin.customers.form.referenceHint"),
          disabled: true,
        })}
        <Field label={t("admin.customers.form.kind")} htmlFor={`${formId}-kind`} error={errors.kind}>
          <Select
            value={values.kind}
            onValueChange={(value) => setValues((current) => ({ ...current, kind: value as CustomerKindEnum }))}
          >
            <SelectTrigger id={`${formId}-kind`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.values(CustomerKindEnum).map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {t(`admin.customers.kinds.${kind}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {input("tax_id", t("admin.customers.form.taxId"), { hint: t("admin.customers.form.taxIdHint") })}
        {input("phone", t("admin.customers.form.phone"), { type: "tel" })}
        {input("email", t("admin.customers.form.email"), { type: "email" })}
        {input("city", t("admin.customers.form.city"))}
        {input("address", t("admin.customers.form.address"))}
        {input("credit_limit", t("admin.customers.form.creditLimit"), {
          hint: t("admin.customers.form.creditLimitHint"),
          inputMode: "decimal",
          disabled: walkIn,
        })}
        {input("payment_terms_days", t("admin.customers.form.paymentTerms"), {
          hint: t("admin.customers.form.paymentTermsHint"),
          inputMode: "numeric",
          disabled: walkIn,
        })}
        <Field
          label={t("admin.customers.form.notes")}
          htmlFor={`${formId}-notes`}
          error={errors.notes}
          className="col-span-full"
        >
          <textarea
            id={`${formId}-notes`}
            name="notes"
            rows={3}
            value={values.notes}
            onChange={(event) => set("notes")(event.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
          />
        </Field>

        <fieldset className="col-span-full flex flex-col gap-3">
          <legend className="mb-2 text-[0.78rem] font-semibold text-ink-2">{t("admin.customers.form.contacts")}</legend>
          {contacts.map((row, index) => (
            <div
              key={row.key}
              role="group"
              aria-label={t("admin.customers.form.contactNumber", { number: index + 1 })}
              className="grid grid-cols-[1fr_1fr_1fr_1fr_auto] gap-2 max-[720px]:grid-cols-2"
            >
              {CONTACT_FIELDS.map(({ field, label, placeholder, type }) => (
                <Input
                  key={field}
                  aria-label={t(label)}
                  placeholder={t(placeholder)}
                  type={type}
                  value={row[field]}
                  onChange={(event) => setContact(row.key, field, event.target.value)}
                  aria-invalid={field === "name" && errors.contacts && !row.name.trim() ? true : undefined}
                  autoComplete="off"
                />
              ))}
              <Button
                size="icon"
                variant="ghost"
                aria-label={t("admin.customers.form.removeContact")}
                title={t("admin.customers.form.removeContact")}
                onClick={() => setContacts((current) => current.filter((other) => other.key !== row.key))}
              >
                <Icon name="trash" />
              </Button>
            </div>
          ))}
          {errors.contacts && <p className="text-[0.78rem] font-semibold text-bad">{errors.contacts}</p>}
          <div>
            <Button onClick={() => setContacts((current) => [...current, contactRow()])}>
              <Icon name="plus" />
              {t("admin.customers.form.addContact")}
            </Button>
          </div>
        </fieldset>
      </form>

      {errors.detail && (
        <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
          {errors.detail}
        </p>
      )}

      <DialogFooter>
        <Button onClick={() => onDone()}>{t("admin.customers.form.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {save.isPending ? t("admin.customers.form.saving") : t("admin.customers.form.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
