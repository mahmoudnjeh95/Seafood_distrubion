import {
  archiveProduct,
  createCategory,
  createProduct,
  getListCategoriesQueryKey,
  IllustrationEnum,
  type Product,
  type ProductCreate,
  removeProductPhoto,
  restoreProduct,
  updateProduct,
  uploadProductPhoto,
  useListCategories,
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
  MoneyInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { PriceSection } from "./PriceSection";
import { ProductPicture } from "./ProductCard";
import { refreshProducts } from "./shared";

type FormValues = {
  reference: string;
  name: string;
  name_ar: string;
  category: string;
  sale_price: string;
  min_stock: string;
  storage_temp_min: string;
  storage_temp_max: string;
  illustration: IllustrationEnum;
  vat_rate: string;
};

type ProductDescription = Omit<ProductCreate, "sale_price">;

type Errors = Partial<Record<keyof FormValues | "photo" | "detail", string>>;

const EMPTY: FormValues = {
  reference: "",
  name: "",
  name_ar: "",
  category: "",
  sale_price: "",
  min_stock: "0",
  storage_temp_min: "",
  storage_temp_max: "",
  illustration: IllustrationEnum.fish,
  vat_rate: "",
};

// The API writes "20.000"; people here write "20,000". Both are read back by parseDecimalInput.
const typed = (decimal: string | null) => (decimal ?? "").replace(".", ",");

function valuesOf(product: Product): FormValues {
  return {
    reference: product.reference,
    name: product.name,
    name_ar: product.name_ar,
    category: String(product.category.id),
    sale_price: typed(product.current_price),
    min_stock: typed(product.min_stock),
    storage_temp_min: typed(product.storage_temp_min),
    storage_temp_max: typed(product.storage_temp_max),
    illustration: product.illustration,
    vat_rate: typed(product.vat_rate),
  };
}

/** Create a product (`product` absent) or change one. Owners and managers only; the server checks it too.
 * `startName` fills a new product's name, e.g. the one a driver typed at the port (D-176). */
export function ProductDialog({
  product,
  startName,
  onDone,
}: {
  product?: Product;
  startName?: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const categories = useListCategories();
  const [values, setValues] = useState<FormValues>(product ? valuesOf(product) : { ...EMPTY, name: startName ?? "" });
  const [errors, setErrors] = useState<Errors>({});
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [newCategory, setNewCategory] = useState<string | null>(null);

  // The chosen photo is shown before it is sent; its temporary address is released when replaced or closed.
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );

  function choosePhoto(file: File | null) {
    setPhoto(file);
    setPreview(file ? URL.createObjectURL(file) : null);
  }

  const set = (field: keyof FormValues) => (value: string) => setValues((current) => ({ ...current, [field]: value }));

  const save = useMutation({
    mutationFn: async ({ description, salePrice }: { description: ProductDescription; salePrice: string }) => {
      const saved = product
        ? await updateProduct(product.id, description)
        : await createProduct({ ...description, sale_price: salePrice });
      if (photo) {
        try {
          await uploadProductPhoto(saved.id, { photo });
        } catch (failure) {
          // The product itself is saved: say what went wrong with the photo and carry on.
          toast.error(fieldErrors(failure).photo ?? t("admin.products.form.error"));
        }
      }
      return saved;
    },
    onSuccess: async () => {
      toast.success(t(product ? "admin.products.form.saved" : "admin.products.form.created"));
      await refreshProducts(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.products.form.error") });
    },
  });

  const addCategory = useMutation({
    mutationFn: (name: string) => createCategory({ name }),
    onSuccess: async (category) => {
      await queryClient.invalidateQueries({ queryKey: getListCategoriesQueryKey() });
      set("category")(String(category.id));
      setNewCategory(null);
      setErrors((current) => ({ ...current, category: undefined }));
    },
    onError: (failure) =>
      setErrors((current) => ({ ...current, category: fieldErrors(failure).name ?? t("admin.products.form.error") })),
  });

  const toggleActive = useMutation({
    mutationFn: (target: Product) => (target.is_active ? archiveProduct(target.id) : restoreProduct(target.id)),
    onSuccess: async (saved) => {
      toast.success(t(saved.is_active ? "admin.products.form.restoredDone" : "admin.products.form.archivedDone"));
      await refreshProducts(queryClient);
      onDone();
    },
    // A product still in stock is refused by the server, with the reason.
    onError: (failure) => toast.error(fieldErrors(failure).detail ?? t("admin.products.form.error")),
  });

  const dropPhoto = useMutation({
    mutationFn: (target: Product) => removeProductPhoto(target.id),
    onSuccess: async () => {
      toast.success(t("admin.products.form.photoRemoved"));
      await refreshProducts(queryClient);
    },
    onError: () => toast.error(t("admin.products.form.error")),
  });

  /** The same checks as the server, so most mistakes show before sending. The server's answer still wins. */
  function validate(): { found: Errors; description: ProductDescription; salePrice: string } {
    const found: Errors = {};
    const decimal = (field: keyof FormValues, places: number, required: boolean): string | null => {
      const text = values[field].trim();
      if (text === "") {
        if (required) found[field] = t("admin.products.form.required");
        return null;
      }
      const parsed = parseDecimalInput(text, places);
      if (parsed === null) found[field] = t("admin.products.form.invalidNumber", { places });
      return parsed;
    };
    if (!values.name.trim()) found.name = t("admin.products.form.required");
    if (!values.category) found.category = t("admin.products.form.required");
    const description: ProductDescription = {
      reference: values.reference.trim(),
      name: values.name.trim(),
      name_ar: values.name_ar.trim(),
      category: Number(values.category),
      min_stock: decimal("min_stock", 3, false) ?? "0",
      storage_temp_min: decimal("storage_temp_min", 1, false),
      storage_temp_max: decimal("storage_temp_max", 1, false),
      illustration: values.illustration,
      // Empty: the organization's rate from the finance settings (D-056); 0 = exempt.
      vat_rate: decimal("vat_rate", 2, false),
    };
    // Only a new product takes a price here; later prices go through the price section.
    const salePrice = product ? "" : (decimal("sale_price", 3, true) ?? "");
    return { found, description, salePrice };
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const { found, description, salePrice } = validate();
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate({ description, salePrice });
  }

  function input(
    name: keyof FormValues,
    label: string,
    kind: "text" | "decimal" | "money" | "arabic" = "text",
    disabled = false,
  ) {
    const id = `${formId}-${name}`;
    const Control = kind === "money" ? MoneyInput : Input;
    return (
      <Field label={label} htmlFor={id} error={errors[name]}>
        <Control
          id={id}
          name={name}
          value={values[name]}
          onChange={(event) => set(name)(event.target.value)}
          aria-invalid={errors[name] ? true : undefined}
          autoComplete="off"
          disabled={disabled}
          placeholder={disabled && !product ? t("admin.numbering.auto") : undefined}
          inputMode={kind === "decimal" || kind === "money" ? "decimal" : undefined}
          className={kind === "decimal" || kind === "money" ? "num" : undefined}
          dir={kind === "arabic" ? "rtl" : undefined}
          lang={kind === "arabic" ? "ar" : undefined}
        />
      </Field>
    );
  }

  function submitNewCategory() {
    const name = newCategory?.trim();
    if (name) addCategory.mutate(name);
  }

  const shownPhoto = preview ?? product?.photo_url ?? null;

  return (
    <DialogContent className="w-[min(680px,calc(100vw-2rem))]">
      <DialogTitle>{t(product ? "admin.products.form.editTitle" : "admin.products.form.createTitle")}</DialogTitle>
      <DialogDescription className="sr-only">{product?.name ?? t("admin.products.form.createTitle")}</DialogDescription>

      <form id={formId} onSubmit={submit} noValidate className="grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
        {input("reference", t("admin.products.form.reference"), "text", true)}
        {input("name", t("admin.products.form.name"))}
        {input("name_ar", t("admin.products.form.nameAr"), "arabic")}

        <Field label={t("admin.products.form.category")} htmlFor={`${formId}-category`} error={errors.category}>
          {newCategory === null ? (
            <div className="flex gap-2">
              <Select value={values.category} onValueChange={set("category")}>
                <SelectTrigger id={`${formId}-category`} aria-invalid={errors.category ? true : undefined}>
                  <SelectValue placeholder={t("admin.products.form.chooseCategory")} />
                </SelectTrigger>
                <SelectContent>
                  {categories.data?.map((category) => (
                    <SelectItem key={category.id} value={String(category.id)}>
                      {category.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="icon"
                className="flex-none"
                aria-label={t("admin.products.form.newCategory")}
                title={t("admin.products.form.newCategory")}
                onClick={() => setNewCategory("")}
              >
                <Icon name="plus" />
              </Button>
            </div>
          ) : (
            <div className="flex gap-2">
              <Input
                id={`${formId}-category`}
                autoFocus
                placeholder={t("admin.products.form.newCategory")}
                value={newCategory}
                onChange={(event) => setNewCategory(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    submitNewCategory();
                  } else if (event.key === "Escape") {
                    // Leave the dialog open: Escape only cancels the new category.
                    event.stopPropagation();
                    setNewCategory(null);
                  }
                }}
              />
              <Button
                className="flex-none"
                disabled={!newCategory.trim() || addCategory.isPending}
                onClick={submitNewCategory}
              >
                {t("admin.products.form.addCategory")}
              </Button>
            </div>
          )}
        </Field>

        {!product && input("sale_price", t("admin.products.form.salePrice"), "money")}
        {input("min_stock", t("admin.products.form.minStock"), "decimal")}
        <div className="col-span-full">
          {input("vat_rate", t("admin.products.form.vatRate"), "decimal")}
          <p className="mt-1 text-[0.8rem] text-ink-2">{t("admin.products.form.vatRateHint")}</p>
        </div>

        <div className="col-span-full grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
          {input("storage_temp_min", t("admin.products.form.tempMin"), "decimal")}
          {input("storage_temp_max", t("admin.products.form.tempMax"), "decimal")}
          <p className="col-span-full -mt-2 text-[0.8rem] text-ink-2">{t("admin.products.form.tempHint")}</p>
        </div>

        <div className="col-span-full grid grid-cols-[180px_1fr] items-start gap-4 max-[560px]:grid-cols-1">
          <ProductPicture
            photoUrl={shownPhoto}
            illustration={values.illustration}
            className="rounded-control border border-line"
          />
          <div className="flex flex-col gap-3">
            <Field label={t("admin.products.form.illustration")} htmlFor={`${formId}-illustration`}>
              <Select value={values.illustration} onValueChange={set("illustration")}>
                <SelectTrigger id={`${formId}-illustration`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.values(IllustrationEnum).map((name) => (
                    <SelectItem key={name} value={name}>
                      {t(`admin.products.illustrations.${name}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <div className="flex flex-wrap items-center gap-2">
              <Button asChild>
                <label htmlFor={`${formId}-photo`}>
                  {t(shownPhoto ? "admin.products.form.changePhoto" : "admin.products.form.choosePhoto")}
                </label>
              </Button>
              <input
                id={`${formId}-photo`}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="sr-only"
                onChange={(event) => choosePhoto(event.target.files?.[0] ?? null)}
              />
              {product?.photo_url && !photo && (
                <Button variant="ghost" disabled={dropPhoto.isPending} onClick={() => dropPhoto.mutate(product)}>
                  {t("admin.products.form.removePhoto")}
                </Button>
              )}
            </div>
            <p className="text-[0.8rem] text-ink-2">{t("admin.products.form.photoHint")}</p>
            {errors.photo && <p className="text-[0.78rem] font-semibold text-bad">{errors.photo}</p>}
          </div>
        </div>
      </form>

      {product && <PriceSection product={product} canEdit />}

      {errors.detail && (
        <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
          {errors.detail}
        </p>
      )}

      <DialogFooter className="items-center">
        {product && (
          <Button
            variant="ghost"
            className="me-auto"
            disabled={toggleActive.isPending}
            onClick={() => toggleActive.mutate(product)}
          >
            {t(product.is_active ? "admin.products.form.archive" : "admin.products.form.restore")}
          </Button>
        )}
        <Button onClick={onDone}>{t("admin.products.form.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {save.isPending ? t("admin.products.form.saving") : t("admin.products.form.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
