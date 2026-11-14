import { type SearchHit, useSearchEverything } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { cn, Dialog, DialogContent, DialogDescription, DialogTitle } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { type KeyboardEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { hitPath } from "./hitPath";

/** Ctrl+K (⌘K on a Mac) or the header button: one box that finds a customer, supplier, product, lot, BL or invoice
 * from any page (D-330). The server only searches what the person may read. */
export function GlobalSearch() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-full border border-line px-3 py-1.5 text-sm text-ink-2 hover:bg-surface-2 print:hidden"
      >
        <span>{t("admin.search.button")}</span>
        <kbd className="rounded border border-line px-1 text-xs max-sm:hidden">Ctrl K</kbd>
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        {open ? <SearchBox onDone={() => setOpen(false)} /> : null}
      </Dialog>
    </>
  );
}

function SearchBox({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const query = useDebounced(text.trim(), 200);
  const results = useSearchEverything(
    { q: query },
    { query: { enabled: query.length >= 2, placeholderData: keepPreviousData } },
  );
  const hits = query.length >= 2 ? (results.data ?? []) : [];
  const chosen = Math.min(active, Math.max(hits.length - 1, 0));

  function go(hit: SearchHit) {
    onDone();
    void navigate(hitPath(hit));
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(Math.min(chosen + 1, hits.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(Math.max(chosen - 1, 0));
    } else if (event.key === "Enter" && hits[chosen]) {
      event.preventDefault();
      go(hits[chosen]);
    }
  }

  return (
    <DialogContent className="top-[12vh] translate-y-0 gap-3 p-4">
      <DialogTitle className="sr-only">{t("admin.search.title")}</DialogTitle>
      <DialogDescription className="sr-only">{t("admin.search.hint")}</DialogDescription>
      <input
        autoFocus
        type="search"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setActive(0);
        }}
        onKeyDown={onKeyDown}
        placeholder={t("admin.search.placeholder")}
        aria-label={t("admin.search.title")}
        className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-[1.05rem]"
      />
      {query.length < 2 ? (
        <p className="text-sm text-ink-2">{t("admin.search.hint")}</p>
      ) : hits.length === 0 && !results.isFetching ? (
        <p className="text-sm text-ink-2">{t("admin.search.none")}</p>
      ) : (
        <ul role="listbox" aria-label={t("admin.search.title")} className="max-h-[60vh] overflow-y-auto">
          {hits.map((hit, index) => (
            <li key={`${hit.kind}-${hit.id}`} role="option" aria-selected={index === chosen}>
              {index === 0 || hits[index - 1]?.kind !== hit.kind ? (
                <p className="px-2 pt-2 pb-1 text-xs font-semibold text-ink-2 uppercase">
                  {t(`admin.search.kinds.${hit.kind}`)}
                </p>
              ) : null}
              <button
                type="button"
                onClick={() => go(hit)}
                onMouseEnter={() => setActive(index)}
                className={cn(
                  "flex w-full flex-col items-start rounded-control px-2 py-1.5 text-left",
                  index === chosen && "bg-surface-2",
                )}
              >
                <span className="font-semibold">{hit.title}</span>
                {hit.detail ? <span className="text-sm text-ink-2">{hit.detail}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </DialogContent>
  );
}
