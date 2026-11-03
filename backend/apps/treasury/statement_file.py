"""Reading a bank's statement from its Excel file (P9-T09d, D-253).

The first sheet has a header row with the columns DATE, LIBELLE (the title may go on: "LIBELLE STE LOGISTICA"),
DEBIT, CREDIT and, optionally, SOLDE. A date is a real Excel date or text such as "03-janv-24" or "03/01/2024";
amounts are numbers or text with a decimal comma. Nothing here touches the database.
"""

import datetime as dt
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.utils.translation import gettext as _
from openpyxl import load_workbook

MAX_ROWS = 5000
# An .xlsx is a zip: what it announces to unpack is checked before it is opened (D-141).
MAX_UNPACKED_BYTES = 100 * 1024 * 1024

MONTHS = {
    **{name: number for number, name in enumerate(("janv", "fevr", "mars", "avr", "mai", "juin"), start=1)},
    **{name: number for number, name in enumerate(("juil", "aout", "sept", "oct", "nov", "dec"), start=7)},
    "janvier": 1,
    "fevrier": 2,
    "avril": 4,
    "juillet": 7,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
}
DAY_TEXT = re.compile(r"^(\d{1,2})[-/. ]+([a-z]+|\d{1,2})[-/. ]+(\d{2}|\d{4})$")


class StatementFileError(Exception):
    """The file cannot be read as a statement at all (not an Excel file, a column missing, too long)."""


@dataclass(frozen=True)
class StatementRow:
    number: int
    day: dt.date
    label: str
    debit: Decimal
    credit: Decimal
    balance: Decimal | None


@dataclass(frozen=True)
class RowError:
    number: int
    message: str


def _normal(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", plain).strip().casefold()


def parse_day(value: Any) -> dt.date:
    """An Excel date, or text like "03-janv-24", "03/01/2024", "2024-01-03"; ValueError otherwise."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = _normal(str(value))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return dt.date.fromisoformat(text)
    found = DAY_TEXT.match(text)
    if found is None:
        raise ValueError(text)
    day, month_text, year_text = found.groups()
    month = int(month_text) if month_text.isdigit() else MONTHS[month_text]
    year = int(year_text)
    return dt.date(2000 + year if year < 100 else year, month, int(day))


def parse_amount(value: Any) -> Decimal:
    """A number, or text with spaces and a decimal comma; empty is zero. Rounded to the millime."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0.000")
    if isinstance(value, bool):
        raise ValueError(value)
    text = str(value).replace(" ", "").replace(" ", "").replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(text) from None


def _refuse_zip_bomb(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            unpacked = sum(entry.file_size for entry in archive.infolist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return  # not a zip: load_workbook answers that it is not an Excel file
    if unpacked > MAX_UNPACKED_BYTES:
        raise StatementFileError(_("Le fichier est trop gros une fois décompressé : coupez-le en plusieurs."))


def _column_of(title: str) -> str | None:
    normal = _normal(title)
    for key in ("date", "libelle", "debit", "credit", "solde"):
        if normal == key or (key == "libelle" and normal.startswith("libelle")):
            return key
    return None


def read_statement(content: bytes) -> tuple[list[StatementRow], list[RowError]]:
    """The rows of the first sheet, and the rows that could not be read (with the Excel row number)."""
    _refuse_zip_bomb(content)
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:  # openpyxl raises many types for a file that is not an .xlsx
        raise StatementFileError(_("Le fichier n'est pas un classeur Excel (.xlsx).")) from error
    rows = book.worksheets[0].iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        raise StatementFileError(_("Le fichier est vide."))
    positions: dict[str, int] = {}
    for index, value in enumerate(header):
        key = _column_of(str(value)) if value is not None else None
        if key is not None and key not in positions:
            positions[key] = index
    missing = [name.upper() for name in ("date", "libelle", "debit", "credit") if name not in positions]
    if missing:
        raise StatementFileError(_("Colonnes introuvables : %(names)s.") % {"names": ", ".join(missing)})

    result: list[StatementRow] = []
    errors: list[RowError] = []
    for number, values in enumerate(rows, start=2):
        if all(cell is None or str(cell).strip() == "" for cell in values):
            continue
        if len(result) + len(errors) >= MAX_ROWS:
            raise StatementFileError(
                _("Plus de %(count)s lignes : coupez le fichier en plusieurs.") % {"count": MAX_ROWS}
            )

        def cell(key: str, values: tuple[Any, ...] = values) -> Any:
            index = positions.get(key)
            return values[index] if index is not None and index < len(values) else None

        try:
            day = parse_day(cell("date"))
        except (ValueError, KeyError, TypeError):
            errors.append(RowError(number, _("Date illisible (attendu : 03-janv-24 ou 03/01/2024).")))
            continue
        try:
            debit, credit = parse_amount(cell("debit")), parse_amount(cell("credit"))
            balance = parse_amount(cell("solde")) if cell("solde") not in (None, "") else None
        except ValueError:
            errors.append(RowError(number, _("Montant illisible.")))
            continue
        label = " ".join(str(cell("libelle") or "").split())
        if not label:
            errors.append(RowError(number, _("Libellé manquant.")))
        elif len(label) > 255:
            errors.append(RowError(number, _("Libellé trop long (255 caractères au plus).")))
        elif debit < 0 or credit < 0:
            errors.append(RowError(number, _("Un débit et un crédit ne sont pas négatifs.")))
        else:
            result.append(StatementRow(number, day, label, debit, credit, balance))
    return result, errors
