import { type EInvoicingSettingsOverview, updateEInvoicingSettings, useGetEInvoicingSettings } from "@frutti/api";
import { formatDate, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
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
import { useId, useState } from "react";
import { Link } from "react-router";

import { fieldErrors } from "../lib/errors";
import { einvoicingStatus } from "./einvoicing";

function SettingsForm({ overview }: { overview: EInvoicingSettingsOverview }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const current = overview.settings;
  const mayEdit = overview.may_edit;
  const [enabled, setEnabled] = useState(current.enabled);
  const [environment, setEnvironment] = useState<string>(current.environment);
  const [apiBaseUrl, setApiBaseUrl] = useState(current.api_base_url);
  const [authMode, setAuthMode] = useState<string>(current.auth_mode);
  const [clientId, setClientId] = useState(current.client_id);
  const [certificateHolder, setCertificateHolder] = useState(current.certificate_holder);
  const [certificateExpires, setCertificateExpires] = useState(current.certificate_expires_on ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () =>
      updateEInvoicingSettings({
        enabled,
        environment,
        api_base_url: apiBaseUrl.trim(),
        auth_mode: authMode,
        client_id: clientId.trim(),
        certificate_holder: certificateHolder.trim(),
        certificate_expires_on: certificateExpires || null,
      }),
    onSuccess: async () => {
      setErrors({});
      toast.success(t("admin.einvoicing.saved"));
      await queryClient.invalidateQueries({
        predicate: (query) =>
          typeof query.queryKey[0] === "string" && query.queryKey[0].startsWith("/api/v1/einvoicing-settings"),
      });
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      if (Object.keys(fromServer).length > 0) setErrors(fromServer);
      else toast.error(t("admin.einvoicing.saveError"));
    },
  });

  const status = einvoicingStatus(overview);
  const statusLabel = {
    off: t("admin.einvoicing.statusOff"),
    incomplete: t("admin.einvoicing.statusIncomplete"),
    ready: t("admin.einvoicing.statusReady"),
    on: t("admin.einvoicing.statusOn"),
  }[status];

  return (
    <div className="grid grid-cols-2 items-start gap-4 max-[900px]:grid-cols-1">
      <Card>
        <CardTitle>{t("admin.einvoicing.title")}</CardTitle>
        <p className="mb-4 rounded-card bg-surface-2 p-3 text-[0.88rem] text-ink-2">{t("admin.einvoicing.notSent")}</p>
        <p className="mb-3 text-[0.92rem]">
          <span className="text-ink-2">{t("admin.einvoicing.status")} : </span>
          <strong>{statusLabel}</strong>
        </p>
        {overview.certificate_expiring && (
          <p role="alert" className="mb-3 text-[0.88rem] font-semibold text-bad">
            {t("admin.einvoicing.expiring")}
          </p>
        )}
        <div className="flex flex-col gap-4">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              className="mt-1"
              checked={enabled}
              disabled={!mayEdit}
              onChange={(event) => setEnabled(event.target.checked)}
            />
            <span>
              <span className="font-semibold">{t("admin.einvoicing.enabled")}</span>
              <span className="block text-[0.82rem] text-ink-2">{t("admin.einvoicing.enabledHint")}</span>
            </span>
          </label>
          {errors.enabled && (
            <p role="alert" className="text-[0.85rem] font-semibold text-bad">
              {errors.enabled}
            </p>
          )}
          <Field label={t("admin.einvoicing.environment")} htmlFor={`${formId}-environment`} error={errors.environment}>
            <Select value={environment} onValueChange={setEnvironment} disabled={!mayEdit}>
              <SelectTrigger id={`${formId}-environment`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sandbox">{t("admin.einvoicing.environmentTest")}</SelectItem>
                <SelectItem value="production">{t("admin.einvoicing.environmentProduction")}</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.einvoicing.apiBaseUrl")} htmlFor={`${formId}-api-url`} error={errors.api_base_url}>
            <Input
              id={`${formId}-api-url`}
              type="url"
              value={apiBaseUrl}
              disabled={!mayEdit}
              onChange={(event) => setApiBaseUrl(event.target.value)}
              aria-invalid={errors.api_base_url ? true : undefined}
              autoComplete="off"
            />
            <p className="text-[0.78rem] text-ink-2">{t("admin.einvoicing.apiBaseUrlHint")}</p>
          </Field>
          <Field label={t("admin.einvoicing.authMode")} htmlFor={`${formId}-auth`} error={errors.auth_mode}>
            <Select
              value={authMode || "undecided"}
              onValueChange={(value) => setAuthMode(value === "undecided" ? "" : value)}
              disabled={!mayEdit}
            >
              <SelectTrigger id={`${formId}-auth`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="undecided">{t("admin.einvoicing.authUndecided")}</SelectItem>
                <SelectItem value="certificate">{t("admin.einvoicing.authCertificate")}</SelectItem>
                <SelectItem value="client_secret">{t("admin.einvoicing.authClientSecret")}</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.einvoicing.clientId")} htmlFor={`${formId}-client-id`} error={errors.client_id}>
            <Input
              id={`${formId}-client-id`}
              value={clientId}
              disabled={!mayEdit}
              onChange={(event) => setClientId(event.target.value)}
              autoComplete="off"
            />
          </Field>
          <Field
            label={t("admin.einvoicing.certificateHolder")}
            htmlFor={`${formId}-holder`}
            error={errors.certificate_holder}
          >
            <Input
              id={`${formId}-holder`}
              value={certificateHolder}
              disabled={!mayEdit}
              onChange={(event) => setCertificateHolder(event.target.value)}
              autoComplete="off"
            />
          </Field>
          <Field
            label={t("admin.einvoicing.certificateExpires")}
            htmlFor={`${formId}-expires`}
            error={errors.certificate_expires_on}
          >
            <Input
              id={`${formId}-expires`}
              type="date"
              value={certificateExpires}
              disabled={!mayEdit}
              onChange={(event) => setCertificateExpires(event.target.value)}
            />
          </Field>
          {mayEdit ? (
            <div>
              <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>
                {t("admin.einvoicing.save")}
              </Button>
            </div>
          ) : (
            <p className="text-[0.85rem] text-ink-2">{t("admin.einvoicing.readOnly")}</p>
          )}
        </div>
      </Card>
      <Card>
        <CardTitle>{t("admin.einvoicing.checks")}</CardTitle>
        <ul className="flex flex-col gap-2 text-[0.92rem]">
          {overview.checks.map((check) => (
            <li key={check.key} className="flex items-start gap-2">
              <span className={check.ok ? "font-semibold text-sea" : "font-semibold text-bad"}>
                {check.ok ? t("admin.einvoicing.ok") : t("admin.einvoicing.missing")}
              </span>
              <span>{check.text}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-[0.82rem] text-ink-2">
          {current.certificate_expires_on
            ? `${t("admin.einvoicing.certificateExpires")} : ${formatDate(current.certificate_expires_on)}`
            : null}
        </p>
        <Link
          to="/factures/parametres"
          className="mt-3 inline-block text-[0.9rem] font-semibold text-sea hover:underline"
        >
          {t("admin.financeSettings.title")}
        </Link>
      </Card>
    </div>
  );
}

/** Paramètres › Facturation électronique (P11-T05a, D-310): the TTN account, and what is still missing. */
export function EInvoicingPage() {
  const { t } = useTranslation();
  const query = useGetEInvoicingSettings();
  return (
    <>
      <Link to="/parametres" className="text-[0.85rem] font-semibold text-sea hover:underline">
        {t("admin.settings.title")}
      </Link>
      <PageHeader eyebrow={t("admin.settings.company")} title={t("admin.einvoicing.title")} />
      <p className="text-ink-2">{t("admin.einvoicing.intro")}</p>
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
