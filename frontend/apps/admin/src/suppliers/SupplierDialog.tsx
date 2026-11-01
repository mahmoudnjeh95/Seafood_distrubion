import { createSupplier, type Supplier, type SupplierContact, type SupplierWrite, updateSupplier } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import {
  Button,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Icon,
  Input,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { refreshSuppliers } from "./shared";

type TextField = "reference" | "name" | "tax_id" | "phone" | "email" | "address" | "city" | "notes";
type FormValues = Record<TextField, string>;
type ContactRow = Required<SupplierContact> & { key: number };
type Errors = Partial<Record<TextField | "contacts" | "detail", string>>;

const EMPTY: FormValues = {
  reference: "",
  name: "",
  tax_id: "",
  phone: "",
  email: "",
  address: "",
  city: "",
  notes: "",
};

const CONTACT_FIELDS = [
  { field: "name", label: "admin.suppliers.form.contactName", placeholder: "admin.suppliers.form.name", type: "text" },
  {
    field: "role",
    label: "admin.suppliers.form.contactRole",
    placeholder: "admin.suppliers.form.contactRole",
    type: "text",
  },
  {
    field: "phone",
    label: "admin.suppliers.form.contactPhone",
    placeholder: "admin.suppliers.form.phone",
    type: "tel",
  },
  {
    field: "email",
    label: "admin.suppliers.form.contactEmail",
    placeholder: "admin.suppliers.form.email",
    type: "email",
  },
] as const;

// Gives each contact row a stable React key, also for rows not saved yet.
let nextKey = 0;
function contactRow(contact?: SupplierContact): ContactRow {
  nextKey += 1;
  return {
    key: nextKey,
    name: contact?.name ?? "",
    role: contact?.role ?? "",
    phone: contact?.phone ?? "",
    email: contact?.email ?? "",
  };
}

/** Create a supplier (`supplier` absent) or change one. Owners and managers only; the server checks it too.
 * `start` fills a new supplier's name and phone, e.g. the ones a driver typed at the port (D-176). */
export function SupplierDialog({
  supplier,
  start,
  onDone,
}: {
  supplier?: Supplier;
  start?: { name: string; phone?: string };
  onDone: (saved?: Supplier) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [values, setValues] = useState<FormValues>(
    supplier
      ? {
          reference: supplier.reference,
          name: supplier.name,
          tax_id: supplier.tax_id,
          phone: supplier.phone,
          email: supplier.email,
          address: supplier.address,
          city: supplier.city,
          notes: supplier.notes,
        }
      : { ...EMPTY, name: start?.name ?? "", phone: start?.phone ?? "" },
  );
  const [contacts, setContacts] = useState<ContactRow[]>(() => supplier?.contacts.map(contactRow) ?? []);
  const [errors, setErrors] = useState<Errors>({});

  const set = (field: TextField) => (value: string) => setValues((current) => ({ ...current, [field]: value }));
  const setContact = (key: number, field: keyof SupplierContact, value: string) =>
    setContacts((current) => current.map((row) => (row.key === key ? { ...row, [field]: value } : row)));

  const save = useMutation({
    mutationFn: (payload: SupplierWrite) => (supplier ? updateSupplier(supplier.id, payload) : createSupplier(payload)),
    onSuccess: async (saved) => {
      toast.success(t(supplier ? "admin.suppliers.form.saved" : "admin.suppliers.form.created"));
      await refreshSuppliers(queryClient);
      onDone(saved);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.suppliers.form.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!values.name.trim()) found.name = t("admin.suppliers.form.required");
    // Blank rows are dropped; a row with something in it needs a name.
    const filled = contacts.filter((row) => row.name.trim() || row.role.trim() || row.phone.trim() || row.email.trim());
    if (filled.some((row) => !row.name.trim())) found.contacts = t("admin.suppliers.form.required");
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const trimmed = (field: TextField) => values[field].trim();
    const payload: SupplierWrite = {
      reference: trimmed("reference"),
      name: trimmed("name"),
      tax_id: trimmed("tax_id"),
      phone: trimmed("phone"),
      email: trimmed("email"),
      address: trimmed("address"),
      city: trimmed("city"),
      notes: trimmed("notes"),
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
    options: { hint?: string; type?: string; autoComplete?: string; className?: string; disabled?: boolean } = {},
  ) {
    const id = `${formId}-${name}`;
    return (
      <Field label={label} htmlFor={id} error={errors[name]} className={options.className}>
        <Input
          id={id}
          name={name}
          type={options.type ?? "text"}
          value={values[name]}
          onChange={(event) => set(name)(event.target.value)}
          aria-invalid={errors[name] ? true : undefined}
          aria-describedby={options.hint ? `${id}-hint` : undefined}
          autoComplete={options.autoComplete ?? "off"}
          disabled={options.disabled}
        />
        {options.hint && (
          <p id={`${id}-hint`} className="text-[0.8rem] text-ink-2">
            {options.hint}
          </p>
        )}
      </Field>
    );
  }

  return (
    <DialogContent className="w-[min(720px,calc(100vw-2rem))]">
      <DialogTitle>{t(supplier ? "admin.suppliers.form.editTitle" : "admin.suppliers.form.createTitle")}</DialogTitle>
      <DialogDescription className="sr-only">
        {supplier?.name ?? t("admin.suppliers.form.createTitle")}
      </DialogDescription>

      <form id={formId} onSubmit={submit} noValidate className="grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
        {input("name", t("admin.suppliers.form.name"))}
        {input("reference", t("admin.suppliers.form.reference"), {
          hint: supplier ? undefined : t("admin.suppliers.form.referenceHint"),
          disabled: true,
        })}
        {input("tax_id", t("admin.suppliers.form.taxId"), { hint: t("admin.suppliers.form.taxIdHint") })}
        {input("phone", t("admin.suppliers.form.phone"), { type: "tel" })}
        {input("email", t("admin.suppliers.form.email"), { type: "email" })}
        {input("city", t("admin.suppliers.form.city"))}
        {input("address", t("admin.suppliers.form.address"), { className: "col-span-full" })}
        <Field
          label={t("admin.suppliers.form.notes")}
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
          <legend className="mb-2 text-[0.78rem] font-semibold text-ink-2">{t("admin.suppliers.form.contacts")}</legend>
          {contacts.map((row, index) => (
            <div
              key={row.key}
              role="group"
              aria-label={t("admin.suppliers.form.contactNumber", { number: index + 1 })}
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
                aria-label={t("admin.suppliers.form.removeContact")}
                title={t("admin.suppliers.form.removeContact")}
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
              {t("admin.suppliers.form.addContact")}
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
        <Button onClick={() => onDone()}>{t("admin.suppliers.form.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {save.isPending ? t("admin.suppliers.form.saving") : t("admin.suppliers.form.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
