"""Generate the 4 report pages (PBIR format) described in powerbi/GUIDE.md.

Writes into DeMillimanize.Report/definition/pages. Close Power BI Desktop before running.
Run:  python run.py pages
"""

import json
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "DeMillimanize.Report" / "definition" / "pages"
BACKUP_DIR = ROOT / "powerbi" / f"page_backup_{date.today():%Y%m%d}"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
VISUAL_SCHEMA = f"{SCHEMA}/visualContainer/2.14.0/schema.json"
PAGE_SCHEMA = f"{SCHEMA}/page/2.1.0/schema.json"
PAGES_SCHEMA = f"{SCHEMA}/pagesMetadata/1.1.0/schema.json"

NAVY, TEAL, WHITE, RED = "#12344D", "#00C1A0", "#FFFFFF", "#E5484D"
M = "_Measures"
PAGES = [("Overview", "Overview"), ("RequestLookup", "Request Lookup"),
         ("FrequentPatterns", "Frequent and Patterns"), ("TicketDetail", "Ticket Detail and Data Quality")]
PAGE_TITLES = dict(PAGES)


# ---- JSON building blocks (same shapes Power BI Desktop writes) ---------------------------
def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def color(hex_value: str) -> dict:
    return {"solid": {"color": lit(text(hex_value))}}


def measure_color(name: str) -> dict:
    return {"solid": {"color": {"expr": {"Measure": {"Expression": {"SourceRef": {"Entity": M}}, "Property": name}}}}}


def field(entity: str, prop: str, kind: str = "Column") -> dict:
    return {kind: {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def col(entity: str, prop: str) -> dict:
    return {"field": field(entity, prop), "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


def meas(prop: str) -> dict:
    return {"field": field(M, prop, "Measure"), "queryRef": f"{M}.{prop}", "nativeQueryRef": prop}


def named(projection: dict, label: str) -> dict:
    return {**projection, "displayName": label}


HIDDEN_BOX = {"background": [{"properties": {"show": lit("false")}}],
              "border": [{"properties": {"show": lit("false")}}],
              "dropShadow": [{"properties": {"show": lit("false")}}]}


def equals_filter(entity: str, prop: str, value: str) -> dict:
    alias = entity[0].lower()
    return {
        "name": f"f_{entity}_{prop}".replace(" ", "_").replace("(", "").replace(")", ""),
        "field": field(entity, prop),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": entity, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": prop}}],
                "Values": [[{"Literal": {"Value": text(value)}}]]}}}],
        },
    }


def not_blank_filter(entity: str, prop: str) -> dict:
    alias = entity[0].lower()
    column = {"Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": prop}}
    return {
        "name": f"nb_{entity}_{prop}".replace(" ", "_").replace("(", "").replace(")", ""),
        "field": field(entity, prop),
        "type": "Advanced",
        "filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": entity, "Type": 0}],
            "Where": [{"Condition": {"Not": {"Expression": {"Comparison": {
                "ComparisonKind": 0, "Left": column, "Right": {"Literal": {"Value": "null"}}}}}}}],
        },
    }


class Page:
    def __init__(self, name: str, title: str, heading: str | None = None):
        self.name, self.title, self.visuals, self.interactions = name, title, [], []
        self.heading = heading or title

    def add(self, vtype: str, x, y, w, h, roles: dict | None = None, title: str | None = None,
            alt: str | None = None, objects: dict | None = None, vc: dict | None = None,
            filters: list | None = None, sort: tuple | None = None) -> str:
        index = len(self.visuals)
        vc = dict(vc or {})
        if title:
            vc["title"] = [{"properties": {"show": lit("true"), "text": lit(text(title))}}]
            vc["subTitle"] = [{"properties": {"show": lit("false")}}]
        if alt or title:
            vc["general"] = [{"properties": {"altText": lit(text(alt or title))}}]
        visual = {"visualType": vtype}
        if roles:
            visual["query"] = {"queryState": {role: {"projections": p} for role, p in roles.items()}}
            if sort:
                visual["query"]["sortDefinition"] = {
                    "sort": [{"field": sort[0]["field"], "direction": sort[1]}], "isDefaultSort": False}
        if objects:
            visual["objects"] = objects
        if vc:
            visual["visualContainerObjects"] = vc
        visual["drillFilterOtherVisuals"] = True
        container = {
            "$schema": VISUAL_SCHEMA,
            "name": f"{self.name[:6].lower()}{index:02d}",
            "position": {"x": x, "y": y, "z": index, "height": h, "width": w, "tabOrder": index},
            "visual": visual,
        }
        if filters:
            container["filterConfig"] = {"filters": filters}
        self.visuals.append(container)
        return container["name"]

    def no_filter(self, source: str, target: str) -> None:
        self.interactions.append({"source": source, "target": target, "type": "NoFilter"})

    def table(self, x, y, w, h, columns: list, title: str, alt: str | None = None, objects: dict | None = None,
              filters: list | None = None, sort: tuple | None = None, url: bool = False, font: int | None = None) -> str:
        """Table with wrapped text and fixed column widths that fit inside the visual (no side scrolling).

        columns: list of (projection, relative width).
        """
        scale = (w - 44) / sum(weight for _, weight in columns)
        values = {"wordWrap": lit("true")}
        headers = {"wordWrap": lit("true"), "autoSizeColumnWidth": lit("false")}
        if url:
            values["urlIcon"] = lit("true")
        if font:
            values["fontSize"] = headers["fontSize"] = lit(f"{font}D")
        objs = {
            "columnHeaders": [{"properties": headers}],
            "values": [{"properties": values}],
            "total": [{"properties": {"totals": lit("false")}}],
            "columnWidth": [{"properties": {"value": lit(f"{int(weight * scale)}D")},
                             "selector": {"metadata": proj["queryRef"]}} for proj, weight in columns],
        }
        for key, entries in (objects or {}).items():
            objs.setdefault(key, []).extend(entries)
        return self.add("tableEx", x, y, w, h, roles={"Values": [proj for proj, _ in columns]}, title=title, alt=alt,
                        objects=objs, filters=filters, sort=sort)

    # ---- shared pieces ----
    def header(self) -> None:
        self.add("textbox", 0, 0, 1920, 60, alt=f"{self.heading} page header",
                 objects={"general": [{"properties": {"paragraphs": [{"textRuns": [{
                     "value": self.heading,
                     "textStyle": {"fontWeight": "bold", "fontSize": "20pt", "color": WHITE}}]}]}}]},
                 vc={"background": [{"properties": {"show": lit("true"), "color": color(NAVY),
                                                    "transparency": lit("0D")}}]})
        for i, (target, label) in enumerate(PAGES):
            active = target == self.name
            self.add("actionButton", 1000 + i * 226, 8, 214, 44, alt=f"Go to {label}",
                     objects={
                         "text": [{"properties": {"show": lit("true"), "text": lit(text(label)),
                                                  "fontColor": color(NAVY if active else WHITE)},
                                   "selector": {"id": "default"}}],
                         "fill": [{"properties": {"show": lit("true"), "fillColor": color(WHITE if active else TEAL),
                                                  "transparency": lit("0D")},
                                   "selector": {"id": "default"}}],
                     },
                     vc={"visualLink": [{"properties": {"show": lit("true"), "type": lit("'PageNavigation'"),
                                                        "navigationSection": lit(text(target))}}]})
        self.card("Mock Data Banner", 24, 64, 700, 58, font=12, font_color=RED, alt="Shows a warning when mock data is loaded")
        self.card("Last Refreshed", 1396, 64, 500, 58, font=11, alt="When the data was last extracted from Freshservice")

    def card(self, measure: str, x, y, w, h, font=24, font_color: str | None = None,
             title: str | None = None, alt: str | None = None, vc: dict | None = None) -> None:
        labels = {"fontSize": lit(f"{font}D")}
        if font_color:
            labels["color"] = color(font_color)
        self.add("card", x, y, w, h, roles={"Values": [meas(measure)]}, title=title, alt=alt or measure,
                 objects={"labels": [{"properties": labels}],
                          "categoryLabels": [{"properties": {"show": lit("false")}}]},
                 vc=vc)

    def slicer(self, entity: str, prop: str, x, y, w, h, mode: str = "Dropdown", title: str | None = None,
               search: bool = False, select_all: bool = False, sort: tuple | None = None) -> str:
        # The visual title names the slicer, so the slicer's own header is hidden to leave room for the control.
        objects = {"data": [{"properties": {"mode": lit(text(mode))}}],
                   "header": [{"properties": {"show": lit("false")}}]}
        if mode == "Dropdown":
            selection = {"strictSingleSelect": lit("false")}
            if select_all:
                selection["selectAllCheckboxEnabled"] = lit("true")  # "Select all" on top of the list
            objects["selection"] = [{"properties": selection}]
        if search:
            objects["general"] = [{"properties": {"selfFilterEnabled": lit("true")}}]
        return self.add("slicer", x, y, w, h, roles={"Values": [col(entity, prop)]}, title=title or prop,
                        alt=f"Filter by {title or prop}", objects=objects, sort=sort)


OUTCOME_FONT = {"values": [{"properties": {"fontColor": measure_color("Outcome Color")},
                            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                         "metadata": "Requests.Outcome"}}]}


# ---- pages -------------------------------------------------------------------------------------
def overview() -> Page:
    """Home page: four filters, five numbers, two charts, a practice bar and the latest requests."""
    p = Page("Overview", PAGE_TITLES["Overview"], heading="De-Millimanize Dashboard")
    p.header()
    # Nothing picked (or "Select all") is all time; ticking one or more years narrows every visual to them.
    p.slicer("DimDate", "Year", 24, 128, 456, 88, title="Created date: all time, or pick a year", select_all=True,
             sort=(col("DimDate", "Year"), "Descending"))
    for i, (prop, label) in enumerate((("Outcome", "Outcome"), ("Model Line", "Model"), ("Department", "Practice"))):
        p.slicer("Requests", prop, 492 + i * 472, 128, 460, 88, title=label, search=True)
    cards = (("Total Requests", "Total requests", 40), ("Approved", "Approved", 40), ("Needs Review", "Needs review", 40),
             ("Frequent People", "Frequent people", 40), ("Latest Request", "Most recent request", 24))
    for i, (name, label, size) in enumerate(cards):
        p.card(name, 24 + i * 376, 228, 368, 124, font=size, title=label)
    # A date axis thins its own labels, so years of months stay readable (a categorical axis showed every month).
    p.add("columnChart", 24, 364, 1120, 380, title="Requests by month",
          roles={"Category": [col("DimDate", "Month Start")], "Series": [col("Requests", "Outcome")],
                 "Y": [meas("Requests by Period")]},
          objects={"legend": [{"properties": {"position": lit("'Top'")}}]})
    p.add("pieChart", 1156, 364, 740, 380, title="Models",
          roles={"Category": [col("Requests", "Model Group")], "Y": [meas("Total Requests")]},
          objects={"legend": [{"properties": {"position": lit("'Right'"), "fontSize": lit("8D")}}],
                   "labels": [{"properties": {"labelStyle": lit("'Percent of total'"), "fontSize": lit("10D")}}]},
          sort=(meas("Total Requests"), "Descending"))
    p.add("clusteredBarChart", 24, 756, 560, 300, title="Requests by recipient's practice",
          roles={"Category": [col("Requests", "Department")], "Y": [meas("Total Requests")]},
          sort=(meas("Total Requests"), "Descending"))
    # Everyone named as "Computer provided to" on tickets less than 120 days apart, whatever the filters above say.
    p.table(596, 756, 556, 300, [(col("People", "Person"), 6), (named(col("People", "Times Named As Recipient"), "Computers"), 3),
                                 (named(col("People", "Last Received"), "Last received"), 4),
                                 (named(col("People", "Shortest Gap (Days)"), "Gap (days)"), 3),
                                 (named(col("People", "Technician"), "Tech"), 2)],
            title="Frequent: computer provided to, under 120 days apart", alt="People named as the recipient on tickets less than 120 days apart",
            font=11, filters=[equals_filter("People", "Frequent", "Yes")],
            sort=(col("People", "Last Received"), "Descending"))
    p.table(1164, 756, 732, 300, [(col("Requests", "Created Date"), 3), (col("Requests", "Computer Provided To"), 5),
                                  (col("Requests", "Model"), 6), (col("Requests", "Outcome"), 3),
                                  (named(col("Requests", "Ticket URL"), "Link"), 1)],
            title="Most recent requests", url=True, objects=OUTCOME_FONT, font=11,
            sort=(col("Requests", "Created Date"), "Descending"))
    return p


def request_lookup() -> Page:
    p = Page("RequestLookup", PAGE_TITLES["RequestLookup"])
    p.header()
    # A dropdown with search: click it, start typing a name, and the list narrows to the matches.
    search = p.add("slicer", 24, 128, 600, 96, roles={"Values": [col("People", "Person")]},
                   title="Search a name (click, then start typing)",
                   alt="Search box: type a name and pick the person to see their request history",
                   objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}],
                            "general": [{"properties": {"selfFilterEnabled": lit("true")}}],
                            "header": [{"properties": {"show": lit("false")}}],
                            "selection": [{"properties": {"strictSingleSelect": lit("true")}}],
                            "items": [{"properties": {"textSize": lit("14D")}}]})
    p.card("Lookup Prompt", 648, 128, 620, 96, font=16, alt="Prompt shown before a name is chosen", vc=HIDDEN_BOX)
    p.card("Frequent Banner", 1292, 128, 604, 96, font=24, font_color=RED,
           alt="Red FREQUENT REQUESTER banner when the person is a frequent requester", vc=HIDDEN_BOX)
    p.table(24, 236, 600, 130, [(col("People", "Person"), 3), (col("People", "Email"), 5), (col("People", "Department"), 3),
                                (col("People", "Technician"), 2), (col("People", "Frequent"), 2)],
            title="Profile", alt="Profile of the selected person")
    counts = (("Requests Made", "Requests made"), ("Requests Made For Others", "For others"),
              ("Times Named As Recipient", "As recipient"), ("Approved", "Approved"), ("Denied", "Denied"),
              ("Pending", "Pending"), ("Needs Review", "Needs review"), ("First Request", "First request"),
              ("Last Request", "Last request"), ("Shortest Gap (Days)", "Shortest gap (days)"))
    p.add("multiRowCard", 24, 378, 600, 262, title="Request counts", alt="Request counts for the selected person",
          roles={"Values": [named(col("People", c), label) for c, label in counts]},
          objects={"dataLabels": [{"properties": {"fontSize": lit("14D")}}],
                   "categoryLabels": [{"properties": {"fontSize": lit("10D")}}]})
    frequent = p.table(24, 652, 600, 404, [(col("People", "Person"), 3), (named(col("People", "Last Received"), "Last received"), 2),
                                           (col("People", "Shortest Gap (Days)"), 2)],
                       title="Frequent people (all, not just the searched name)", alt="People flagged as frequent requesters",
                       filters=[equals_filter("People", "Frequent", "Yes")],
                       sort=(col("People", "Last Received"), "Descending"))
    p.no_filter(search, frequent)
    # Plain columns only: a measure here would hide rows where it is blank (e.g. a person's first request).
    history = [(col("Requests", "Created Date"), 7), (col("Requests", "Ticket ID"), 5), (col("PersonRequests", "Role"), 6),
               (col("Requests", "Requester Name"), 10), (col("Requests", "Computer Provided To"), 10),
               (col("Requests", "Model"), 12), (col("Requests", "Outcome"), 7),
               (named(col("Requests", "Days Since Previous (Recipient)"), "Days since previous"), 7),
               (named(col("Requests", "Certificate Attached"), "Certificate"), 6),
               (named(col("Requests", "Ticket URL"), "Link"), 3)]
    p.table(648, 236, 1248, 760, history, title="Request history", url=True, font=11,
            alt="Every request for the selected person, newest first", objects=OUTCOME_FONT,
            sort=(col("Requests", "Created Date"), "Descending"))
    p.card("No History Message", 648, 1004, 1248, 52, font=14, alt="Message when the person has no requests", vc=HIDDEN_BOX)
    return p


def frequent_patterns() -> Page:
    p = Page("FrequentPatterns", PAGE_TITLES["FrequentPatterns"])
    p.header()
    wildcard = {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": f"{M}.Total Requests"}
    p.add("pivotTable", 24, 128, 1872, 440, title="Requests by month and year (darker = busier month)",
          roles={"Rows": [col("DimDate", "Year")], "Columns": [col("DimDate", "Month")], "Values": [meas("Total Requests")]},
          objects={"values": [{"properties": {"fontSize": lit("14D")}},
                              {"properties": {"backColor": measure_color("Heatmap Color")}, "selector": wildcard}],
                   "columnHeaders": [{"properties": {"fontSize": lit("13D")}}],
                   "rowHeaders": [{"properties": {"fontSize": lit("13D")}}],
                   "grid": [{"properties": {"rowPadding": lit("5D")}}],
                   "columnWidth": [{"properties": {"value": lit("128D")}, "selector": {"metadata": f"{M}.Total Requests"}},
                                   {"properties": {"value": lit("140D")}, "selector": {"metadata": "DimDate.Year"}}]})
    ranked = [("Person", "Person", 12), ("Times Named As Recipient", "Computers received", 7), ("Last Received", "Last received", 8),
              ("Shortest Gap (Days)", "Shortest gap (days)", 7), ("Frequent", "Frequent", 6), ("Technician", "Technician", 7)]
    p.table(24, 580, 880, 476, [(named(col("People", c), label), wt) for c, label, wt in ranked],
            title="People named as recipient more than once (shortest gap first; red = under 120 days)", font=11,
            objects={"values": [{"properties": {"fontColor": measure_color("Frequent Color")},
                                 "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                              "metadata": "People.Person"}}]},
            filters=[not_blank_filter("People", "Shortest Gap (Days)")],
            sort=(col("People", "Shortest Gap (Days)"), "Ascending"))
    p.add("clusteredColumnChart", 916, 580, 484, 476, title="Requests by month of the year (all years together)",
          roles={"Category": [col("DimDate", "Month")], "Y": [meas("Total Requests")]})
    p.add("clusteredColumnChart", 1412, 580, 484, 476, title="Shortest gap between a person's computers, in days",
          roles={"Category": [col("GapBuckets", "Bucket")], "Y": [meas("People in Gap Bucket")]},
          objects={"dataPoint": [{"properties": {"fill": measure_color("Gap Bucket Color")},
                                  "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]},
          sort=(col("GapBuckets", "Bucket"), "Ascending"))
    return p


def ticket_detail() -> Page:
    p = Page("TicketDetail", PAGE_TITLES["TicketDetail"])
    p.header()
    for i, (name, label) in enumerate((("Waiting for Confirmation", "Waiting for confirmation"),
                                       ("Needs Review", "Outcome needs review"),
                                       ("Certificates Missing", "Certificates missing"),
                                       ("Serial Mismatches", "Serial mismatches"))):
        p.card(name, 24 + i * 316, 128, 300, 100, font=28, title=label)
    p.card("Refresh Health", 1288, 128, 608, 100, font=16, font_color=WHITE, title="Refresh health",
           vc={"background": [{"properties": {"show": lit("true"), "color": measure_color("Refresh Health Color"),
                                              "transparency": lit("0D")}}]})
    # Key columns only, so nothing scrolls sideways; every column is in the Excel workbook.
    detail = [("Ticket ID", 5), ("Created Date", 7), ("Requester Name", 10), ("Computer Provided To", 10), ("Department", 6),
              ("Recipient Source", 8), ("Model", 11), ("PC Serial Number", 8), ("Outcome", 7), ("Outcome Evidence", 16),
              ("Certificate Attached", 6), ("Match Confidence", 7), ("Archived", 5)]
    p.table(24, 244, 1872, 400, [(col("Requests", c), wt) for c, wt in detail]
            + [(named(col("Requests", "Ticket URL"), "Link"), 3)],
            title="All requests (key columns; every column is in the Excel workbook)", url=True, objects=OUTCOME_FONT,
            sort=(col("Requests", "Created Date"), "Descending"))
    p.table(24, 660, 800, 396, [(col("Unconfirmed", "Ticket ID"), 4), (col("Unconfirmed", "Created Date"), 5),
                                (col("Unconfirmed", "Subject"), 10), (col("Unconfirmed", "Confidence"), 5),
                                (col("Unconfirmed", "Evidence"), 12), (named(col("Unconfirmed", "Ticket URL"), "Link"), 2)],
            title="Waiting for confirmation (not counted until someone answers yes or no)", url=True,
            sort=(col("Unconfirmed", "Created Date"), "Descending"))
    p.table(836, 660, 356, 396, [(col("Requests", "Ticket ID"), 2), (col("Requests", "Created Date"), 3),
                                 (col("Requests", "Outcome Evidence"), 6)],
            title="Outcome needs review", filters=[equals_filter("Requests", "Outcome", "Needs Review")])
    p.table(1204, 660, 316, 396, [(col("Requests", "Ticket ID"), 2), (col("Requests", "Created Date"), 3),
                                  (col("Requests", "Computer Provided To"), 4)],
            title="Certificate missing", filters=[equals_filter("Requests", "Certificate Missing", "Yes")])
    p.table(1532, 660, 364, 396, [(named(col("RunLog", "Finished (Local)"), "Finished"), 5), (col("RunLog", "Status"), 4),
                                  (col("RunLog", "Message"), 9)],
            title="Refresh log", sort=(col("RunLog", "Finished (Local)"), "Descending"))
    return p


def main() -> int:
    if not PAGES_DIR.exists():
        raise SystemExit(f"Not found: {PAGES_DIR}. Save the report as a .pbip first.")
    ours = {name for name, _ in PAGES}
    for folder in PAGES_DIR.iterdir():
        if folder.is_dir() and folder.name not in ours:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(BACKUP_DIR / folder.name))
            print(f"Backed up existing page '{folder.name}' to {BACKUP_DIR}")
    for page in (overview(), request_lookup(), frequent_patterns(), ticket_detail()):
        page_dir = PAGES_DIR / page.name
        if page_dir.exists():
            shutil.rmtree(page_dir)  # generated by this script on a previous run
        (page_dir / "visuals").mkdir(parents=True)
        page_json = {"$schema": PAGE_SCHEMA, "name": page.name, "displayName": page.title,
                     "displayOption": "FitToPage", "height": 1080, "width": 1920}
        if page.interactions:
            page_json["visualInteractions"] = page.interactions
        (page_dir / "page.json").write_text(json.dumps(page_json, indent=2), encoding="utf-8")
        for v in page.visuals:
            vdir = page_dir / "visuals" / v["name"]
            vdir.mkdir()
            (vdir / "visual.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
        print(f"{page.title}: {len(page.visuals)} visuals")
    (PAGES_DIR / "pages.json").write_text(json.dumps({
        "$schema": PAGES_SCHEMA, "pageOrder": [n for n, _ in PAGES], "activePageName": PAGES[0][0]}, indent=2),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
