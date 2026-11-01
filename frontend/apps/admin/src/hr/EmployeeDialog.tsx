import { createEmployee, type Employee, type EmployeeWrite, updateEmployee, useListMembers } from "@frutti/api";
import { parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
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
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { refreshHr } from "./shared";

type TextField =
  | "reference"
  | "name"
  | "position"
  | "phone"
  | "hire_date"
  | "monthly_salary"
  | "cnss_number"
  | "cnss_rate"
  | "employee_cnss_rate"
  | "notes";
type Errors = Partial<Record<TextField | "user" | "detail", string>>;

const NO_LOGIN = "none";
// The sample files give 17,07 % (D-055, provisional).
const DEFAULT_RATE = "17,07";
// The employee's own contribution, withheld from the salary (D-119, provisional until the accountant confirms).
const DEFAULT_OWN_RATE = "9,18";

// The API writes "1250.000"; people here write "1250,000". Both are read back by parseDecimalInput.
const typed = (decimal: string) => decimal.replace(".", ",");

/** Create an employee (`employee` absent) or change one. The owner only; the server checks it too. */
export function EmployeeDialog({ employee, onDone }: { employee?: Employee; onDone: (saved?: Employee) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const members = useListMembers();
  const [values, setValues] = useState<Record<TextField, string>>({
    reference: employee?.reference ?? "",
    name: employee?.name ?? "",
    position: employee?.position ?? "",
    phone: employee?.phone ?? "",
    hire_date: employee?.hire_date ?? "",
    monthly_salary: employee ? typed(employee.monthly_salary) : "",
    cnss_number: employee?.cnss_number ?? "",
    cnss_rate: employee ? typed(employee.cnss_rate) : DEFAULT_RATE,
    employee_cnss_rate: employee ? typed(employee.employee_cnss_rate) : DEFAULT_OWN_RATE,
    notes: employee?.notes ?? "",
  });
  const [login, setLogin] = useState(employee?.user ? String(employee.user.id) : NO_LOGIN);
  const [errors, setErrors] = useState<Errors>({});

  const set = (field: TextField) => (value: string) => setValues((current) => ({ ...current, [field]: value }));

  const save = useMutation({
    mutationFn: (payload: EmployeeWrite) => (employee ? updateEmployee(employee.id, payload) : createEmployee(payload)),
    onSuccess: async (saved) => {
      toast.success(t(employee ? "admin.hr.form.saved" : "admin.hr.form.created"));
      await refreshHr(queryClient);
      onDone(saved);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.hr.form.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!values.name.trim()) found.name = t("admin.hr.form.required");
    const salary = parseDecimalInput(values.monthly_salary.trim() || "0", 3);
    if (salary === null || salary.startsWith("-")) found.monthly_salary = t("admin.hr.form.invalidAmount");
    const rate = parseDecimalInput(values.cnss_rate.trim() || "0", 2);
    if (rate === null || rate.startsWith("-") || Number(rate) > 100) found.cnss_rate = t("admin.hr.form.invalidRate");
    const ownRate = parseDecimalInput(values.employee_cnss_rate.trim() || "0", 2);
    if (ownRate === null || ownRate.startsWith("-") || Number(ownRate) > 100) {
      found.employee_cnss_rate = t("admin.hr.form.invalidRate");
    }
    setErrors(found);
    if (Object.keys(found).length > 0 || salary === null || rate === null) return;
    const trimmed = (field: TextField) => values[field].trim();
    save.mutate({
      reference: trimmed("reference"),
      name: trimmed("name"),
      position: trimmed("position"),
      phone: trimmed("phone"),
      hire_date: trimmed("hire_date") || null,
      monthly_salary: salary,
      cnss_number: trimmed("cnss_number"),
      cnss_rate: rate,
      employee_cnss_rate: ownRate ?? "0",
      user: login === NO_LOGIN ? null : Number(login),
      notes: trimmed("notes"),
    });
  }

  function input(
    name: TextField,
    label: string,
    options: {
      hint?: string;
      type?: string;
      inputMode?: "decimal";
      money?: boolean;
      className?: string;
      disabled?: boolean;
    } = {},
  ) {
    const id = `${formId}-${name}`;
    const Control = options.money ? MoneyInput : Input;
    return (
      <Field label={label} htmlFor={id} error={errors[name]} className={options.className}>
        <Control
          id={id}
          name={name}
          type={options.type ?? "text"}
          inputMode={options.inputMode}
          value={values[name]}
          onChange={(event) => set(name)(event.target.value)}
          aria-invalid={errors[name] ? true : undefined}
          aria-describedby={options.hint ? `${id}-hint` : undefined}
          autoComplete="off"
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
      <DialogTitle>{t(employee ? "admin.hr.form.editTitle" : "admin.hr.form.createTitle")}</DialogTitle>
      <DialogDescription className="sr-only">{employee?.name ?? t("admin.hr.form.createTitle")}</DialogDescription>

      <form id={formId} onSubmit={submit} noValidate className="grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
        {input("name", t("admin.hr.form.name"))}
        {input("reference", t("admin.hr.form.reference"), {
          hint: employee ? undefined : t("admin.hr.form.referenceHint"),
          disabled: true,
        })}
        {input("position", t("admin.hr.form.position"))}
        {input("phone", t("admin.hr.form.phone"), { type: "tel" })}
        {input("hire_date", t("admin.hr.form.hireDate"), { type: "date" })}
        {input("monthly_salary", t("admin.hr.form.salary"), {
          hint: t("admin.hr.form.salaryHint"),
          inputMode: "decimal",
          money: true,
        })}
        {input("cnss_number", t("admin.hr.form.cnssNumber"))}
        {input("cnss_rate", t("admin.hr.form.cnssRate"), {
          hint: t("admin.hr.form.cnssRateHint"),
          inputMode: "decimal",
        })}
        {input("employee_cnss_rate", t("admin.hr.form.employeeCnssRate"), {
          hint: t("admin.hr.form.employeeCnssRateHint"),
          inputMode: "decimal",
        })}
        <Field label={t("admin.hr.form.user")} htmlFor={`${formId}-user`} error={errors.user} className="col-span-full">
          <Select value={login} onValueChange={setLogin}>
            <SelectTrigger id={`${formId}-user`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_LOGIN}>{t("admin.hr.form.noUser")}</SelectItem>
              {(members.data ?? [])
                .filter((member) => member.is_active)
                .map((member) => (
                  <SelectItem key={member.user.id} value={String(member.user.id)}>
                    {`${member.user.first_name} ${member.user.last_name}`.trim() || member.user.username}
                    {` (${t(`roles.${member.role}`)})`}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          <p className="text-[0.8rem] text-ink-2">{t("admin.hr.form.userHint")}</p>
        </Field>
        <Field
          label={t("admin.hr.form.notes")}
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
      </form>

      {errors.detail && (
        <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
          {errors.detail}
        </p>
      )}

      <DialogFooter>
        <Button onClick={() => onDone()}>{t("admin.hr.form.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {save.isPending ? t("admin.hr.form.saving") : t("admin.hr.form.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
