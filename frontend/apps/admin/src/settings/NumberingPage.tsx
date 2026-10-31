import { getGetNumberingQueryKey, type NumberLine, updateNumbering, useGetNumbering } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Input, PageHeader, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router";

import { fieldErrors } from "../lib/errors";

/** The next number as it reads with `prefix` typed: the server's "<prefix><separator><number>" with the new prefix. */
export function nextWithPrefix(line: NumberLine, prefix: string): string {
  return `${prefix}${line.next_number.slice(line.prefix.length)}`;
}

/** The prefix in front of the numbers and the number the next record gets. Owners and managers change it (D-223). */
function NumberingForm({ lines }: { lines: NumberLine[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [prefixes, setPrefixes] = useState(() => lines.map((line) => line.prefix));
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () =>
      updateNumbering({ prefixes: lines.map((line, index) => ({ kind: line.kind, prefix: prefixes[index] ?? "" })) }),
    onSuccess: (saved) => {
      setErrors({});
      setPrefixes(saved.map((line) => line.prefix));
      queryClient.setQueryData(getGetNumberingQueryKey(), saved);
      toast.success(t("admin.numbering.saved"));
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      setErrors(found);
      if (Object.keys(found).length === 0) toast.error(t("admin.numbering.error"));
    },
  });

  return (
    <>
      <Table>
        <thead>
          <tr>
            <Th>{t("admin.numbering.kind")}</Th>
            <Th>{t("admin.numbering.prefix")}</Th>
            <Th>{t("admin.numbering.defaultPrefix")}</Th>
            <Th>{t("admin.numbering.next")}</Th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, index) => {
            const prefix = prefixes[index] ?? "";
            const error = errors[`prefixes.${index}.prefix`];
            return (
              <Fragment key={line.kind}>
                {(index === 0 || lines[index - 1]?.group !== line.group) && (
                  <tr>
                    <td colSpan={4} className="bg-surface-2 px-3 pt-4 pb-1 text-[0.82rem] font-semibold text-ink-2">
                      {line.group}
                    </td>
                  </tr>
                )}
                <tr>
                  <Td>
                    {line.label}
                    {line.yearly && (
                      <span className="block text-[0.8rem] text-ink-2">{t("admin.numbering.yearly")}</span>
                    )}
                  </Td>
                  <Td>
                    <Input
                      aria-label={line.label}
                      name={`prefix-${line.kind}`}
                      value={prefix}
                      maxLength={6}
                      className="w-28 uppercase"
                      aria-invalid={error ? true : undefined}
                      onChange={(event) =>
                        setPrefixes((current) =>
                          current.map((value, position) => (position === index ? event.target.value : value)),
                        )
                      }
                    />
                    {error && (
                      <p role="alert" className="mt-1 text-[0.8rem] text-bad">
                        {error}
                      </p>
                    )}
                  </Td>
                  <Td className="num text-ink-2">{line.default_prefix}</Td>
                  <Td className="num font-semibold">{nextWithPrefix(line, prefix)}</Td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </Table>
      <div className="mt-4 flex justify-end">
        <Button disabled={save.isPending} onClick={() => save.mutate()}>
          {t("admin.numbering.save")}
        </Button>
      </div>
    </>
  );
}

/** "Paramètres › Numérotation": the prefix of every kind of number (clients, products, documents), D-223. */
export function NumberingPage() {
  const { t } = useTranslation();
  const query = useGetNumbering();
  return (
    <>
      <PageHeader eyebrow={t("admin.settings.company")} title={t("admin.numbering.title")} />
      <p className="text-ink-2">{t("admin.numbering.intro")}</p>
      <Link to="/parametres" className="mb-4 inline-block text-[0.9rem] font-semibold text-sea hover:underline">
        {t("admin.numbering.back")}
      </Link>
      {query.data && <NumberingForm key={query.dataUpdatedAt} lines={query.data} />}
    </>
  );
}
