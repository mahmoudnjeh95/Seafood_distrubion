import { getGetNumberingQueryKey, type NumberLine, updateNumbering, useGetNumbering } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Input, PageHeader, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router";

import { fieldErrors } from "../lib/errors";
import { DRAFT_WORD, nextWithPrefix } from "./numbering";

/** The prefix in front of the numbers and the number the next record gets. Owners and managers change it (D-223). */
function NumberingForm({ lines }: { lines: NumberLine[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [prefixes, setPrefixes] = useState(() => lines.map((line) => line.prefix));
  const [drafts, setDrafts] = useState(() => lines.map((line) => line.draft_prefix));
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () =>
      updateNumbering({
        prefixes: lines.map((line, index) => ({
          kind: line.kind,
          prefix: prefixes[index] ?? "",
          // Only the documents with a draft step have a draft prefix (D-283).
          ...(line.has_draft ? { draft_prefix: drafts[index] ?? "" } : {}),
        })),
      }),
    onSuccess: (saved) => {
      setErrors({});
      setPrefixes(saved.map((line) => line.prefix));
      setDrafts(saved.map((line) => line.draft_prefix));
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
            <Th>{t("admin.numbering.draftPrefix")}</Th>
            <Th>{t("admin.numbering.defaultPrefix")}</Th>
            <Th>{t("admin.numbering.next")}</Th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, index) => {
            const prefix = prefixes[index] ?? "";
            const error = errors[`prefixes.${index}.prefix`];
            const draft = drafts[index] ?? "";
            const draftError = errors[`prefixes.${index}.draft_prefix`];
            return (
              <Fragment key={line.kind}>
                {(index === 0 || lines[index - 1]?.group !== line.group) && (
                  <tr>
                    <td colSpan={5} className="bg-surface-2 px-3 pt-4 pb-1 text-[0.82rem] font-semibold text-ink-2">
                      {line.group}
                    </td>
                  </tr>
                )}
                <tr>
                  <Td>
                    {line.title}
                    {line.yearly && (
                      <span className="block text-[0.8rem] text-ink-2">{t("admin.numbering.yearly")}</span>
                    )}
                  </Td>
                  <Td>
                    <Input
                      aria-label={line.title}
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
                  <Td>
                    {line.has_draft ? (
                      <>
                        <Input
                          aria-label={`${t("admin.numbering.draftPrefix")} · ${line.title}`}
                          name={`draft-prefix-${line.kind}`}
                          value={draft}
                          maxLength={6}
                          className="w-28 uppercase"
                          aria-invalid={draftError ? true : undefined}
                          onChange={(event) =>
                            setDrafts((current) =>
                              current.map((value, position) => (position === index ? event.target.value : value)),
                            )
                          }
                        />
                        {draftError && (
                          <p role="alert" className="mt-1 text-[0.8rem] text-bad">
                            {draftError}
                          </p>
                        )}
                      </>
                    ) : (
                      <span className="text-ink-2">{t("admin.numbering.draftNone")}</span>
                    )}
                  </Td>
                  <Td className="num text-ink-2">{line.default_prefix}</Td>
                  <Td className="num font-semibold">
                    {nextWithPrefix(line, prefix)}
                    {line.has_draft && (
                      <span className="block text-[0.8rem] font-normal text-ink-2">
                        {t("admin.numbering.nextDraft", {
                          number: nextWithPrefix(line, draft.trim().toUpperCase() || DRAFT_WORD, true),
                        })}
                      </span>
                    )}
                  </Td>
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
