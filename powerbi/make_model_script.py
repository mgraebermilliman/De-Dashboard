"""Generate powerbi/DeMillimanize.model.tmdl from the workbook schema in extract/tables.py.

The output is a TMDL script for Power BI Desktop's TMDL view (paste, then Apply). Generating it
keeps the Power BI column list in sync with what the extract writes.
Run:  python run.py tmdl
"""

from pathlib import Path

from extract.tables import (FORM_ANSWERS_COLUMNS, PEOPLE_COLUMNS, PERSON_REQUESTS_COLUMNS,
                            REQUESTS_COLUMNS, RUNLOG_COLUMNS)

OUTPUT = Path(__file__).resolve().parent / "DeMillimanize.model.tmdl"
DEFAULT_PATH = r"O:\De-Dashboard\sample_data\DeMillimanize Requests.mock.xlsx"
MEASURE_TABLE = "_Measures"

INT = {"Ticket ID", "Requester Request #", "Days Since Previous (Requester)", "Recipient Request #",
       "Days Since Previous (Recipient)", "Requests Made", "Requests Made For Others",
       "Times Named As Recipient", "Approved", "Denied", "Pending", "Needs Review", "Shortest Gap (Days)",
       "Run", "Tickets Listed", "Forms Checked", "Matched Total", "API Calls"}
DATE = {"Created Date", "First Request", "Last Request"}
DATETIME = {"Decision Date", "Closed Date", "Last Updated", "Started (UTC)", "Finished (UTC)", "Finished (Local)"}
NO_SUM = {"Ticket ID", "Run", "Requester Request #", "Recipient Request #", "Days Since Previous (Requester)",
          "Days Since Previous (Recipient)", "Shortest Gap (Days)"}
HIDDEN = {("PersonRequests", "Person"), ("PersonRequests", "Ticket ID"), ("FormAnswers", "Ticket ID")}
FOLDERS = {
    "Ticket": ["Ticket ID", "Ticket URL", "Created Date", "Ticket Type", "Status", "Item Stage", "Closed Date",
               "Subject", "Resolution Note", "Last Updated"],
    "People": ["Requester Name", "Requester Email", "Department", "Computer Provided To",
               "Recipient Differs From Requester", "Requested For", "Requester Is Technician",
               "Recipient Is Technician"],
    "Outcome": ["Outcome", "Outcome Source", "Outcome Evidence", "Approver", "Decision Date"],
    "Device": ["Device Type", "PC Make and Model", "PC Serial Number", "Most Recent PC Name",
               "Certificate Attached", "Certificate File", "Certificate Missing"],
    "Frequency": ["Frequent (Requester)", "Requester Request #", "Days Since Previous (Requester)",
                  "Frequent (Recipient)", "Recipient Request #", "Days Since Previous (Recipient)",
                  "Same Serial Seen Before", "Holiday Season"],
    "Matching": ["Match Source", "Matched Phrase", "Matched Field", "Match Needs Review"],
}
FOLDER_OF = {col: folder for folder, cols in FOLDERS.items() for col in cols}


def q(name: str) -> str:
    """Quote a TMDL object name when it has anything other than letters, digits or underscores."""
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def m_type(col: str) -> str:
    if col in INT:
        return "Int64.Type"
    if col in DATE:
        return "type date"
    if col in DATETIME:
        return "type datetime"
    return "type text"


def column_block(table: str, col: str) -> list[str]:
    if col in INT:
        props = ["dataType: int64", "formatString: 0"]
    elif col in DATE:
        props = ["dataType: dateTime", 'formatString: mmm d, yyyy']
    elif col in DATETIME:
        props = ["dataType: dateTime", 'formatString: mmm d, yyyy h:mm AM/PM']
    else:
        props = ["dataType: string"]
    props.append("summarizeBy: " + ("none" if col in NO_SUM or col not in INT else "sum"))
    props.append(f"sourceColumn: {col}")
    if col == "Ticket URL":
        props.append("dataCategory: WebUrl")
    if (table, col) in HIDDEN:
        props.append("isHidden")
    if table == "Requests" and col in FOLDER_OF:
        props.append(f"displayFolder: {FOLDER_OF[col]}")
    return [f"\t\tcolumn {q(col)}"] + [f"\t\t\t{p}" for p in props] + [""]


def m_table(table: str, columns: list[str], key: str) -> list[str]:
    types = ",\n".join(f'\t\t\t\t\t\t{{"{c}", {m_type(c)}}}' for c in columns)
    body = [
        "let",
        f'\tSource = Workbook{{[Item="{table}", Kind="Table"]}}[Data],',
        "\tTyped = Table.TransformColumnTypes(Source, {",
        types,
        "\t}),",
        f"\tRows = Table.SelectRows(Typed, each [{key}] <> null)",
        "in",
        "\tRows",
    ]
    return partition(table, body)


def partition(table: str, body: list[str]) -> list[str]:
    lines = [f"\t\tpartition {q(table)} = m", "\t\t\tmode: import", "\t\t\tsource ="]
    for line in "\n".join(body).split("\n"):
        lines.append("\t\t\t\t\t" + line)
    return lines + [""]


def table(name: str, columns: list[str], key: str, extra: list[str] | None = None) -> list[str]:
    lines = [f"\ttable {q(name)}", ""]
    for col in columns:
        lines += column_block(name, col)
    lines += extra or []
    lines += m_table(name, columns, key)
    return lines


def measure(name: str, dax: str, fmt: str | None, folder: str) -> list[str]:
    # TMDL view rejected multi-line measure bodies (2026-11-24), so each formula goes on one line.
    one_line = " ".join(part.strip() for part in dax.strip().split("\n"))
    lines = [f"\t\tmeasure {q(name)} = {one_line}"]
    if fmt:
        lines.append(f"\t\t\tformatString: {fmt}")
    lines.append(f"\t\t\tdisplayFolder: {folder}")
    return lines + [""]


WORKBOOK_M = [
    "let",
    "\t// WorkbookPath can be a local/UNC file path or a SharePoint file URL (https://...).",
    '\tSource = if Text.StartsWith(WorkbookPath, "http", Comparer.OrdinalIgnoreCase)',
    "\t\tthen Web.Contents(WorkbookPath)",
    "\t\telse File.Contents(WorkbookPath),",
    "\tBook = Excel.Workbook(Source, null, true)",
    "in",
    "\tBook",
]

DIMDATE_M = [
    "let",
    "\tCreated = List.RemoveNulls(Requests[Created Date]),",
    "\tToday = Date.From(DateTime.LocalNow()),",
    "\tStartDate = #date(Date.Year(if List.IsEmpty(Created) then Today else List.Min(Created)), 1, 1),",
    "\tEndDate = #date(Date.Year(List.Max(Created & {Today})), 12, 31),",
    "\tDays = List.Dates(StartDate, Duration.Days(EndDate - StartDate) + 1, #duration(1, 0, 0, 0)),",
    "\tBase = Table.FromList(Days, Splitter.SplitByNothing(), type table [Date = date]),",
    '\tYear = Table.AddColumn(Base, "Year", each Date.Year([Date]), Int64.Type),',
    '\tQuarter = Table.AddColumn(Year, "Quarter", each "Q" & Text.From(Date.QuarterOfYear([Date])), type text),',
    '\tMonthNumber = Table.AddColumn(Quarter, "Month Number", each Date.Month([Date]), Int64.Type),',
    '\tMonth = Table.AddColumn(MonthNumber, "Month", each Date.ToText([Date], "MMM", "en-US"), type text),',
    '\tMonthStart = Table.AddColumn(Month, "Month Start", each Date.StartOfMonth([Date]), type date),',
    '\tMonthYear = Table.AddColumn(MonthStart, "Month Year", each Date.ToText([Date], "MMM yyyy", "en-US"), type text),',
    '\tWeek = Table.AddColumn(MonthYear, "Week", each Date.WeekOfYear([Date], Day.Monday), Int64.Type),',
    '\tDayName = Table.AddColumn(Week, "Day of Week", each Date.ToText([Date], "ddd", "en-US"), type text),',
    '\tDayNumber = Table.AddColumn(DayName, "Day of Week Number", each Date.DayOfWeek([Date], Day.Monday) + 1, Int64.Type),',
    "\t// Same rule as the extract: Nov 15 through Jan 5.",
    '\tHoliday = Table.AddColumn(DayNumber, "Holiday Season", each',
    "\t\tif (Date.Month([Date]) = 11 and Date.Day([Date]) >= 15) or Date.Month([Date]) = 12",
    '\t\t\tor (Date.Month([Date]) = 1 and Date.Day([Date]) <= 5) then "Yes" else "No", type text),',
    '\tHolidayMonth = Table.AddColumn(Holiday, "Holiday Month", each',
    '\t\tif List.Contains({11, 12, 1}, Date.Month([Date])) then "Yes" else "No", type text)',
    "in",
    "\tHolidayMonth",
]
DIMDATE_COLUMNS = [
    ("Date", "dateTime", "mmm d, yyyy", ["isKey"]), ("Year", "int64", "0", []), ("Quarter", "string", None, []),
    ("Month Number", "int64", "0", []), ("Month", "string", None, ["sortByColumn: 'Month Number'"]),
    ("Month Start", "dateTime", "mmm yyyy", []), ("Month Year", "string", None, ["sortByColumn: 'Month Start'"]),
    ("Week", "int64", "0", []), ("Day of Week", "string", None, ["sortByColumn: 'Day of Week Number'"]),
    ("Day of Week Number", "int64", "0", []), ("Holiday Season", "string", None, []),
    ("Holiday Month", "string", None, []),
]

GAP_BUCKETS_M = [
    "#table(",
    '\ttype table [Bucket = text, #"Min Days" = Int64.Type, #"Max Days" = Int64.Type,',
    '\t\t#"Bucket Order" = Int64.Type, #"Within 120 Days" = text],',
    '\t{{"0-30", 0, 30, 1, "Yes"}, {"31-60", 31, 60, 2, "Yes"}, {"61-90", 61, 90, 3, "Yes"},',
    '\t\t{"91-120", 91, 120, 4, "Yes"}, {"121-180", 121, 180, 5, "No"}, {"181-365", 181, 365, 6, "No"},',
    '\t\t{"365+", 366, 1000000, 7, "No"}})',
]

COUNT = "COALESCE ( CALCULATE ( COUNTROWS ( Requests ), {filter} ), 0 )"
MEASURES = [
    # (name, DAX, format, folder)
    ("Total Requests", "COALESCE ( COUNTROWS ( Requests ), 0 )", "#,0", "Counts"),
    ("Approved", COUNT.format(filter='Requests[Outcome] = "Approved"'), "#,0", "Counts"),
    ("Denied", COUNT.format(filter='Requests[Outcome] = "Denied"'), "#,0", "Counts"),
    ("Pending", COUNT.format(filter='Requests[Outcome] = "Pending"'), "#,0", "Counts"),
    ("Needs Review", COUNT.format(filter='Requests[Outcome] = "Needs Review"'), "#,0", "Counts"),
    ("Unique Requesters", "COALESCE ( DISTINCTCOUNTNOBLANK ( Requests[Requester Name] ), 0 )", "#,0", "Counts"),
    ("Frequent Requests", COUNT.format(
        filter='Requests[Frequent (Requester)] = "Yes" || Requests[Frequent (Recipient)] = "Yes"'), "#,0", "Counts"),
    ("Frequent People", 'COALESCE ( CALCULATE ( DISTINCTCOUNT ( PersonRequests[Person] ), People[Frequent] = "Yes" ), 0 )',
     "#,0", "Counts"),
    ("Requests Made For Others", COUNT.format(filter='Requests[Recipient Differs From Requester] = "Yes"'), "#,0", "Counts"),
    ("Duplicate Serials", COUNT.format(filter='Requests[Same Serial Seen Before] = "Yes"'), "#,0", "Counts"),
    ("Certificates Missing", COUNT.format(filter='Requests[Certificate Missing] = "Yes"'), "#,0", "Counts"),
    ("Match Needs Review", COUNT.format(filter='Requests[Match Needs Review] = "Yes"'), "#,0", "Counts"),
    ("Technician-Listed Requests", COUNT.format(filter='Requests[Recipient Is Technician] = "Yes"'), "#,0", "Counts"),
    ("Approval Rate %", "DIVIDE ( [Approved], [Approved] + [Denied] )", "0.0%", "Rates"),
    ("Denial Rate %", "DIVIDE ( [Denied], [Approved] + [Denied] )", "0.0%", "Rates"),
    ("Holiday Season Share %",
     'DIVIDE ( CALCULATE ( COUNTROWS ( Requests ), Requests[Holiday Season] = "Yes" ), [Total Requests] )',
     "0.0%", "Rates"),
    ("Avg Days Between Requests", "AVERAGE ( Requests[Days Since Previous (Requester)] )", "0", "Timing"),
    ("Avg Days Between Requests (Recipient)", "AVERAGE ( Requests[Days Since Previous (Recipient)] )", "0", "Timing"),
    ("Avg Days to Decision", """AVERAGEX (
	FILTER ( Requests, NOT ISBLANK ( Requests[Decision Date] ) && NOT ISBLANK ( Requests[Created Date] ) ),
	DATEDIFF ( Requests[Created Date], Requests[Decision Date], DAY )
)""", "0.0", "Timing"),
    ("Requests Same Period Last Year", "CALCULATE ( [Total Requests], SAMEPERIODLASTYEAR ( DimDate[Date] ) )",
     "#,0", "Timing"),
    ("Requests MoM Change", """VAR Previous = CALCULATE ( [Total Requests], DATEADD ( DimDate[Date], -1, MONTH ) )
RETURN IF ( HASONEVALUE ( DimDate[Month Start] ), [Total Requests] - Previous )""", "+#,0;-#,0;0", "Timing"),
    ("Requests MoM Change %", """VAR Previous = CALCULATE ( [Total Requests], DATEADD ( DimDate[Date], -1, MONTH ) )
RETURN IF ( HASONEVALUE ( DimDate[Month Start] ), DIVIDE ( [Total Requests] - Previous, Previous ) )""",
     "+0.0%;-0.0%;0.0%", "Timing"),
    ("Requests YoY Change", "[Total Requests] - [Requests Same Period Last Year]", "+#,0;-#,0;0", "Timing"),
    ("Requests YoY Change %", "DIVIDE ( [Total Requests] - [Requests Same Period Last Year], [Requests Same Period Last Year] )",
     "+0.0%;-0.0%;0.0%", "Timing"),
    ("Share of Year %", "DIVIDE ( [Total Requests], CALCULATE ( [Total Requests], ALLEXCEPT ( DimDate, DimDate[Year] ) ) )",
     "0.0%", "Patterns"),
    ("All-Years Share of Month %", """DIVIDE (
	CALCULATE ( [Total Requests], REMOVEFILTERS ( DimDate[Year] ) ),
	CALCULATE ( [Total Requests], REMOVEFILTERS ( DimDate[Year], DimDate[Month], DimDate[Month Number] ) )
)""", "0.0%", "Patterns"),
    ("Requests in Gap Bucket", """VAR Low = SELECTEDVALUE ( GapBuckets[Min Days] )
VAR High = SELECTEDVALUE ( GapBuckets[Max Days] )
RETURN
	COALESCE (
		SUMX (
			Requests,
			VAR Gap = COALESCE ( Requests[Days Since Previous (Recipient)], Requests[Days Since Previous (Requester)] )
			RETURN IF ( NOT ISBLANK ( Gap ) && Gap >= Low && Gap <= High, 1 )
		),
		0
	)""", "#,0", "Patterns"),
    ("Holiday Band", """IF (
	SELECTEDVALUE ( DimDate[Holiday Month] ) = "Yes",
	MAXX ( ALLSELECTED ( DimDate[Month Start] ), [Total Requests] )
)""", "#,0", "Patterns"),
    ("Selected Person", "SELECTEDVALUE ( People[Person] )", None, "Lookup"),
    ("Lookup Prompt", 'IF ( ISBLANK ( [Selected Person] ), "Type a name to see their request history", "" )',
     None, "Lookup"),
    ("Frequent Banner", 'IF ( SELECTEDVALUE ( People[Frequent] ) = "Yes", "FREQUENT REQUESTER", "" )', None, "Lookup"),
    ("No History Message", 'IF ( NOT ISBLANK ( [Selected Person] ) && [Total Requests] = 0, "No prior requests found.", "" )',
     None, "Lookup"),
    ("Days Since Previous (Role)", """SWITCH (
	SELECTEDVALUE ( PersonRequests[Role] ),
	"Recipient", MAX ( Requests[Days Since Previous (Recipient)] ),
	"Requester", MAX ( Requests[Days Since Previous (Requester)] ),
	MIN ( MAX ( Requests[Days Since Previous (Recipient)] ), MAX ( Requests[Days Since Previous (Requester)] ) )
)""", "0", "Lookup"),
    ("Timeline Y", "IF ( [Total Requests] > 0, 1 )", "0", "Lookup"),
    ("Outcome Color", """SWITCH (
	SELECTEDVALUE ( Requests[Outcome] ),
	"Approved", "#2EB67D",
	"Denied", "#E5484D",
	"Pending", "#F5A623",
	"Needs Review", "#7B61FF",
	"#8A96A3"
)""", None, "Formatting"),
    ("Certificate Flag", 'IF ( SELECTEDVALUE ( Requests[Certificate Attached] ) = "Yes", 1, 0 )', "0", "Formatting"),
    ("Frequent Color", 'IF ( SELECTEDVALUE ( People[Frequent] ) = "Yes", "#E5484D", "#12344D" )', None, "Formatting"),
    ("Gap Bucket Color", 'IF ( SELECTEDVALUE ( GapBuckets[Within 120 Days] ) = "Yes", "#E5484D", "#8A96A3" )', None,
     "Formatting"),
    ("Mock Data Banner", """IF (
	COALESCE ( CALCULATE ( COUNTROWS ( Requests ), CONTAINSSTRING ( Requests[Ticket URL], "example.invalid" ), REMOVEFILTERS () ), 0 ) > 0,
	"MOCK DATA - not real tickets",
	""
)""", None, "Formatting"),
    ("Last Refreshed", """VAR LastOk = CALCULATE ( MAX ( RunLog[Finished (Local)] ), RunLog[Status] = "Success" )
RETURN
	IF (
		ISBLANK ( LastOk ),
		"Last refreshed: no successful run yet",
		"Last refreshed: " & FORMAT ( LastOk, "mmm d, yyyy h:mm AM/PM" )
	)""", None, "Refresh"),
    ("Latest Run Status", """VAR LastRun = MAX ( RunLog[Run] )
RETURN CALCULATE ( SELECTEDVALUE ( RunLog[Status] ), RunLog[Run] = LastRun )""", None, "Refresh"),
    ("Hours Since Last Success", """VAR LastOk = CALCULATE ( MAX ( RunLog[Finished (UTC)] ), RunLog[Status] = "Success" )
RETURN IF ( NOT ISBLANK ( LastOk ), ( UTCNOW () - LastOk ) * 24 )""", "0.0", "Refresh"),
    ("Refresh Health", """IF (
	[Latest Run Status] <> "Success" || ISBLANK ( [Hours Since Last Success] ) || [Hours Since Last Success] > 36,
	"Attention: check the refresh log",
	"Healthy"
)""", None, "Refresh"),
    ("Refresh Health Color", 'IF ( [Refresh Health] = "Healthy", "#2EB67D", "#E5484D" )', None, "Refresh"),
]

RELATIONSHIPS = [
    ("PersonRequests_People", "PersonRequests.Person", "People.Person", None),
    ("PersonRequests_Requests", "PersonRequests.'Ticket ID'", "Requests.'Ticket ID'", "bothDirections"),
    ("Requests_DimDate", "Requests.'Created Date'", "DimDate.Date", None),
    ("FormAnswers_Requests", "FormAnswers.'Ticket ID'", "Requests.'Ticket ID'", None),
]


def build() -> str:
    lines = ["createOrReplace", ""]
    lines += [f'\texpression WorkbookPath = "{DEFAULT_PATH}" meta [IsParameterQuery=true, Type="Text", '
              "IsParameterQueryRequired=true]", ""]
    lines += ["\texpression Workbook ="] + ["\t\t\t" + l for l in WORKBOOK_M] + [""]

    lines += table("Requests", REQUESTS_COLUMNS, "Ticket ID")
    lines += table("People", PEOPLE_COLUMNS, "Person")
    lines += table("PersonRequests", PERSON_REQUESTS_COLUMNS, "Ticket ID")
    lines += table("FormAnswers", FORM_ANSWERS_COLUMNS, "Ticket ID")
    lines += table("RunLog", RUNLOG_COLUMNS, "Run")

    lines += ["\ttable DimDate", "\t\tdataCategory: Time", ""]
    for name, dtype, fmt, extra in DIMDATE_COLUMNS:
        lines += [f"\t\tcolumn {q(name)}", f"\t\t\tdataType: {dtype}"]
        lines += [f"\t\t\tformatString: {fmt}"] if fmt else []
        lines += ["\t\t\tsummarizeBy: none", f"\t\t\tsourceColumn: {name}"] + [f"\t\t\t{e}" for e in extra] + [""]
    lines += partition("DimDate", DIMDATE_M)

    lines += ["\ttable GapBuckets", ""]
    for name, dtype, extra in [("Bucket", "string", ["sortByColumn: 'Bucket Order'"]), ("Min Days", "int64", ["isHidden"]),
                               ("Max Days", "int64", ["isHidden"]), ("Bucket Order", "int64", ["isHidden"]),
                               ("Within 120 Days", "string", [])]:
        lines += [f"\t\tcolumn {q(name)}", f"\t\t\tdataType: {dtype}", "\t\t\tsummarizeBy: none",
                  f"\t\t\tsourceColumn: {name}"] + [f"\t\t\t{e}" for e in extra] + [""]
    lines += partition("GapBuckets", GAP_BUCKETS_M)

    # "Measures" is a reserved table name in Power BI (TMDL view rejects it).
    lines += [f"\ttable {MEASURE_TABLE}", ""]
    for name, dax, fmt, folder in MEASURES:
        lines += measure(name, dax, fmt, folder)
    lines += ["\t\tcolumn Placeholder", "\t\t\tdataType: string", "\t\t\tisHidden", "\t\t\tsummarizeBy: none",
              "\t\t\tsourceColumn: Placeholder", ""]
    lines += partition(MEASURE_TABLE, ["#table(type table [Placeholder = text], {})"])

    for name, from_col, to_col, direction in RELATIONSHIPS:
        lines += [f"\trelationship {name}"]
        lines += [f"\t\tcrossFilteringBehavior: {direction}"] if direction else []
        lines += [f"\t\tfromColumn: {from_col}", f"\t\ttoColumn: {to_col}", ""]

    lines += ["\trole 'Program Owners'", "\t\tmodelPermission: read", ""]
    return "\n".join(lines)


def main() -> int:
    OUTPUT.write_text(build(), encoding="utf-8")
    print(f"TMDL script written: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
