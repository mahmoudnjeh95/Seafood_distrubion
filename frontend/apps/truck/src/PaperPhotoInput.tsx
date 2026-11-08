import { useTranslation } from "@frutti/i18n";
import { Button } from "@frutti/ui";
import { useEffect, useRef, useState } from "react";

/**
 * The photo of the supplier's paper (D-159): one big button opens the phone's camera directly, another picks a photo
 * already taken; the photo is shown before it is sent, and can be taken again or removed.
 */
export function PaperPhotoInput({
  value,
  onChange,
  alreadyJoined,
  title,
}: {
  value: File | undefined;
  onChange: (photo: File | undefined) => void;
  /** The purchase already has a photo on the server: a new one replaces it. */
  alreadyJoined: boolean;
  /** The heading above the buttons; the supplier's paper by default. */
  title?: string;
}) {
  const { t } = useTranslation();
  const camera = useRef<HTMLInputElement>(null);
  const gallery = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const heading = title ?? t("truck.purchase.paperPhoto");

  // The chosen photo is shown from a temporary address, released when replaced or when the screen closes.
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );

  const choose = (photo: File | undefined) => {
    setPreview(photo === undefined ? null : URL.createObjectURL(photo));
    onChange(photo);
  };

  const picked = (files: FileList | null) => {
    const photo = files?.[0];
    if (photo !== undefined) choose(photo);
  };

  return (
    <div className="space-y-2">
      <p className="font-semibold">{heading}</p>
      {alreadyJoined && value === undefined ? (
        <p className="text-sm text-ink-2">{t("truck.purchase.paperJoined")}</p>
      ) : null}
      {preview === null || value === undefined ? null : (
        <img
          src={preview}
          alt={heading}
          className="max-h-64 w-full rounded-control border border-line object-contain"
        />
      )}
      {/* `capture` opens the back camera directly on Android and iPhone; the other input opens the photos. */}
      <input
        ref={camera}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        aria-label={t("truck.purchase.takePhoto")}
        onChange={(event) => {
          picked(event.target.files);
          event.target.value = "";
        }}
      />
      <input
        ref={gallery}
        type="file"
        accept="image/*"
        className="hidden"
        aria-label={t("truck.purchase.pickPhoto")}
        onChange={(event) => {
          picked(event.target.files);
          event.target.value = "";
        }}
      />
      <Button size="lg" className="py-4 text-lg" onClick={() => camera.current?.click()}>
        {t(value === undefined ? "truck.purchase.takePhoto" : "truck.purchase.retakePhoto")}
      </Button>
      <div className="flex gap-2">
        <Button variant="ghost" onClick={() => gallery.current?.click()}>
          {t("truck.purchase.pickPhoto")}
        </Button>
        {value === undefined ? null : (
          <Button variant="ghost" onClick={() => choose(undefined)}>
            {t("truck.purchase.removePhoto")}
          </Button>
        )}
      </div>
    </div>
  );
}
