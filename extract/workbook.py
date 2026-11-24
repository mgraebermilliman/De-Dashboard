"""Write the tables to an Excel workbook with named Excel Tables (what Power BI reads)."""

import os
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

_MAX_CELL_TEXT = 32_000


def _cell_value(value):
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)[:_MAX_CELL_TEXT]
    return value


def write_workbook(path: Path, tables: dict[str, tuple[list[str], list[dict]]]) -> None:
    """Write atomically so Power BI never reads a half-written file."""
    wb = Workbook()
    wb.remove(wb.active)
    for name, (columns, rows) in tables.items():
        ws = wb.create_sheet(name)
        for col, header in enumerate(columns, start=1):
            ws.cell(row=1, column=col, value=header)
        for r, row in enumerate(rows, start=2):
            for col, header in enumerate(columns, start=1):
                cell = ws.cell(row=r, column=col, value=_cell_value(row.get(header)))
                # Ticket text must never become a live formula (spreadsheet formula injection).
                if cell.data_type == "f":
                    cell.data_type = "s"
                if isinstance(cell.value, datetime):
                    cell.number_format = "yyyy-mm-dd hh:mm"
                elif isinstance(cell.value, date):
                    cell.number_format = "yyyy-mm-dd"
        last_row = max(len(rows), 1) + 1  # an Excel table needs at least one data row
        table = Table(displayName=name, ref=f"A1:{get_column_letter(len(columns))}{last_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(table)
        ws.freeze_panes = "A2"
        for col, header in enumerate(columns, start=1):
            ws.column_dimensions[get_column_letter(col)].width = min(max(len(header) + 2, 12), 40)

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.stem + ".tmp.xlsx")
    wb.save(temp)
    try:
        os.replace(temp, path)
    except PermissionError:
        temp.unlink(missing_ok=True)
        raise PermissionError(f"Could not replace {path.name}. Close it in Excel and run again.") from None
