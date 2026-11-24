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
PAGES = [("RequestLookup", "Request Lookup"), ("Overview", "Overview"),
         ("FrequentPatterns", "Frequent and Patterns"), ("TicketDetail", "Ticket Detail and Data Quality")]


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


def earliest(entity: str, prop: str) -> dict:
    agg = {"Aggregation": {"Expression": field(entity, prop), "Function": 3}}  # 3 = Min
    return {"field": agg, "queryRef": f"Min({entity}.{prop})", "nativeQueryRef": f"Earliest {prop}"}


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


class Page:
    def __init__(self, name: str, title: str):
        self.name, self.title, self.visuals, self.interactions = name, title, [], []

    def add(self, vtype: str, x, y, w, h, roles: dict | None = None, title: str | None = None,
            alt: str | None = None, objects: dict | None = None, vc: dict | None = None,
            filters: list | None = None, sort: tuple | None = None) -> str:
        index = len(self.visuals)
        vc = dict(vc or {})
        if title:
            vc["title"] = [{"properties": {"show": lit("true"), "text": lit(text(title))}}]
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
              filters: list | None = None, sort: tuple | None = None, url: bool = False) -> str:
        """Table with wrapped text and fixed column widths that fit inside the visual (no side scrolling).

        columns: list of (projection, relative width).
        """
        scale = (w - 44) / sum(weight for _, weight in columns)
        values = {"wordWrap": lit("true")}
        if url:
            values["urlIcon"] = lit("true")
        objs = {
            "columnHeaders": [{"properties": {"wordWrap": lit("true"), "autoSizeColumnWidth": lit("false")}}],
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
        self.add("textbox", 0, 0, 1920, 60, alt=f"{self.title} page header",
                 objects={"general": [{"properties": {"paragraphs": [{"textRuns": [{
                     "value": self.title,
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

    def slicer(self, entity: str, prop: str, x, y, w, h, mode: str = "Dropdown", title: str | None = None) -> str:
        # The visual title names the slicer, so the slicer's own header is hidden to leave room for the control.
        objects = {"data": [{"properties": {"mode": lit(text(mode))}}],
                   "header": [{"properties": {"show": lit("false")}}]}
        if mode == "Dropdown":
            objects["selection"] = [{"properties": {"strictSingleSelect": lit("false")}}]
        return self.add("slicer", x, y, w, h, roles={"Values": [col(entity, prop)]}, title=title or prop,
                        alt=f"Filter by {title or prop}", objects=objects)


OUTCOME_FONT = {"values": [{"properties": {"fontColor": measure_color("Outcome Color")},
                            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                         "metadata": "Requests.Outcome"}}]}


# ---- pages -------------------------------------------------------------------------------------
def request_lookup() -> Page:
    p = Page(*PAGES[0])
    p.header()
    search = p.add("slicer", 24, 128, 600, 96, roles={"Values": [col("People", "Person")]}, title="Search a name",
                   alt="Search box: choose a person to see their request history",
                   objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}],
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
    frequent = p.table(24, 652, 600, 404, [(col("People", "Person"), 3), (col("People", "Last Request"), 2),
                                           (col("People", "Shortest Gap (Days)"), 2)],
                       title="Frequent people (all, not just the searched name)", alt="People flagged as frequent requesters",
                       filters=[equals_filter("People", "Frequent", "Yes")],
                       sort=(col("People", "Last Request"), "Descending"))
    p.no_filter(search, frequent)
    # Plain columns only: a measure here would hide rows where it is blank (e.g. a person's first request).
    history = [(col("Requests", "Created Date"), 8), (col("Requests", "Ticket ID"), 6), (col("PersonRequests", "Role"), 7),
               (col("Requests", "Requester Name"), 10), (col("Requests", "Computer Provided To"), 10),
               (col("Requests", "Device Type"), 7), (col("Requests", "PC Serial Number"), 9), (col("Requests", "Outcome"), 8),
               (col("Requests", "Approver"), 9), (col("Requests", "Decision Date"), 8),
               (col("Requests", "Days Since Previous (Recipient)"), 8), (col("Requests", "Certificate Attached"), 7),
               (col("Requests", "Outcome Evidence"), 16), (named(col("Requests", "Ticket URL"), "Link"), 4)]
    p.table(648, 236, 1248, 560, history, title="Request history", url=True,
            alt="Every request for the selected person, newest first", objects=OUTCOME_FONT,
            sort=(col("Requests", "Created Date"), "Descending"))
    p.card("No History Message", 648, 800, 1248, 44, font=14, alt="Message when the person has no requests", vc=HIDDEN_BOX)
    p.add("scatterChart", 648, 848, 1248, 208, title="Timeline", alt="Timeline of the person's requests, colored by outcome",
          roles={"Category": [col("Requests", "Ticket ID")], "Series": [col("Requests", "Outcome")],
                 "X": [earliest("Requests", "Created Date")], "Y": [meas("Timeline Y")]},
          objects={"valueAxis": [{"properties": {"show": lit("false")}}]})
    return p


def overview() -> Page:
    p = Page(*PAGES[1])
    p.header()
    p.slicer("DimDate", "Date", 24, 128, 300, 110, mode="Between", title="Created date")
    y = 246
    for entity, prop, label in (("Requests", "Outcome", None), ("Requests", "Device Type", None),
                                ("Requests", "Department", None), ("Requests", "Requester Name", "Requester"),
                                ("Requests", "Computer Provided To", None), ("People", "Frequent", "Frequent person"),
                                ("Requests", "Match Source", None)):
        p.slicer(entity, prop, 24, y, 300, 92, title=label or prop)
        y += 100
    for i, name in enumerate(("Total Requests", "Approved", "Denied", "Pending", "Needs Review",
                              "Approval Rate %", "Frequent People")):
        p.card(name, 340 + i * 223, 128, 215, 110, font=28, title=name)
    p.add("lineStackedColumnComboChart", 340, 254, 1556, 400, title="Requests by month (dashed line = same month last year)",
          roles={"Category": [col("DimDate", "Month Start")], "Series": [col("Requests", "Outcome")],
                 "Y": [meas("Total Requests")], "Y2": [meas("Requests Same Period Last Year")]},
          objects={"categoryAxis": [{"properties": {"axisType": lit("'Categorical'")}}],
                   "lineStyles": [{"properties": {"lineChartType": lit("'linear'"), "lineStyle": lit("'dashed'")}}]})
    p.add("donutChart", 340, 670, 380, 386, title="Outcome share",
          roles={"Category": [col("Requests", "Outcome")], "Y": [meas("Total Requests")]},
          objects={"legend": [{"properties": {"position": lit("'Bottom'")}}]})
    for i, (prop, label) in enumerate((("Device Type", "By device type"), ("Department", "By department (practice)"),
                                       ("Approver", "By approver"))):
        p.add("clusteredBarChart", 736 + i * 388, 670, 380 if i < 2 else 392, 386, title=label,
              roles={"Category": [col("Requests", prop)], "Y": [meas("Total Requests")]},
              sort=(meas("Total Requests"), "Descending"))
    return p


def frequent_patterns() -> Page:
    p = Page(*PAGES[2])
    p.header()
    ranked = [("Person", 12), ("Requests Made", 7), ("Requests Made For Others", 8), ("Times Named As Recipient", 8),
              ("Approved", 7), ("Denied", 6), ("Last Request", 9), ("Shortest Gap (Days)", 8), ("Frequent", 7),
              ("Technician", 8)]
    p.table(24, 128, 940, 440, [(col("People", c), wt) for c, wt in ranked], title="People ranked (shortest gap first)",
            objects={"values": [{"properties": {"fontColor": measure_color("Frequent Color")},
                                 "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                              "metadata": "People.Person"}}]},
            sort=(col("People", "Shortest Gap (Days)"), "Ascending"))
    p.add("pivotTable", 980, 128, 916, 440, title="Requests by month and year (heatmap)",
          roles={"Rows": [col("DimDate", "Year")], "Columns": [col("DimDate", "Month")], "Values": [meas("Total Requests")]})
    p.add("lineChart", 24, 584, 620, 472, title="Share of each year's requests by month (Nov-Jan = holiday season)",
          roles={"Category": [col("DimDate", "Month")], "Series": [col("DimDate", "Year")], "Y": [meas("Share of Year %")]},
          objects={"lineStyles": [{"properties": {"lineChartType": lit("'linear'")}}]})
    p.add("clusteredColumnChart", 660, 584, 620, 472,
          title="Days between requests (red = within the 120-day frequent window)",
          roles={"Category": [col("GapBuckets", "Bucket")], "Y": [meas("Requests in Gap Bucket")]},
          objects={"dataPoint": [{"properties": {"fill": measure_color("Gap Bucket Color")},
                                  "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]},
          sort=(col("GapBuckets", "Bucket"), "Ascending"))
    p.table(1296, 584, 600, 230, [(col("Requests", "Requester Name"), 1), (col("Requests", "Computer Provided To"), 1),
                                  (col("Requests", "Created Date"), 1), (col("Requests", "Outcome"), 1)],
            title="Devices given to someone else (non-technicians)",
            filters=[equals_filter("Requests", "Recipient Differs From Requester", "Yes"),
                     equals_filter("Requests", "Requester Is Technician", "No")], objects=OUTCOME_FONT)
    p.table(1296, 826, 600, 230, [(col("Requests", "PC Serial Number"), 6), (col("Requests", "Created Date"), 5),
                                  (col("Requests", "Ticket ID"), 4), (col("Requests", "Computer Provided To"), 6),
                                  (col("Requests", "Outcome"), 5)],
            title="Same serial seen before",
            filters=[equals_filter("Requests", "Same Serial Seen Before", "Yes")], objects=OUTCOME_FONT)
    return p


def ticket_detail() -> Page:
    p = Page(*PAGES[3])
    p.header()
    for i, (name, label) in enumerate((("Needs Review", "Outcome needs review"), ("Match Needs Review", "Match needs review"),
                                       ("Certificates Missing", "Certificates missing"))):
        p.card(name, 24 + i * 316, 128, 300, 100, font=28, title=label)
    p.card("Refresh Health", 972, 128, 460, 100, font=16, font_color=WHITE, title="Refresh health",
           vc={"background": [{"properties": {"show": lit("true"), "color": measure_color("Refresh Health Color"),
                                              "transparency": lit("0D")}}]})
    p.card("Hours Since Last Success", 1448, 128, 448, 100, font=28, title="Hours since last successful extract")
    # Key columns only, so nothing scrolls sideways; every column is in the Excel workbook.
    detail = [("Ticket ID", 6), ("Created Date", 7), ("Requester Name", 9), ("Computer Provided To", 9), ("Department", 9),
              ("Device Type", 6), ("PC Serial Number", 8), ("Outcome", 7), ("Outcome Source", 8), ("Outcome Evidence", 20),
              ("Approver", 8), ("Decision Date", 7), ("Certificate Attached", 7), ("Same Serial Seen Before", 7),
              ("Match Source", 6), ("Status", 6), ("Requester Is Technician", 7)]
    p.table(24, 244, 1872, 420, [(col("Requests", c), wt) for c, wt in detail]
            + [(named(col("Requests", "Ticket URL"), "Link"), 4)],
            title="All requests (key columns; every column is in the Excel workbook)", url=True, objects=OUTCOME_FONT,
            sort=(col("Requests", "Created Date"), "Descending"))
    worklists = [
        ("Worklist: outcome needs review", [(col("Requests", "Ticket ID"), 2), (col("Requests", "Created Date"), 3),
                                            (col("Requests", "Outcome Evidence"), 6)], ("Requests", "Outcome", "Needs Review")),
        ("Worklist: match needs review", [(col("Requests", "Ticket ID"), 2), (col("Requests", "Subject"), 5),
                                          (col("Requests", "Matched Phrase"), 4)], ("Requests", "Match Needs Review", "Yes")),
        ("Worklist: certificate missing", [(col("Requests", "Ticket ID"), 2), (col("Requests", "Created Date"), 3),
                                           (col("Requests", "Computer Provided To"), 4)],
         ("Requests", "Certificate Missing", "Yes")),
    ]
    for i, (label, columns, flt) in enumerate(worklists):
        p.table(24 + i * 372, 680, 364, 376, columns, title=label, filters=[equals_filter(*flt)])
    p.table(1140, 680, 364, 376, [(col("FormAnswers", "Field"), 4), (col("FormAnswers", "Value"), 5)],
            title="Form answers (select a ticket above)")
    p.table(1512, 680, 384, 376, [(col("RunLog", "Run"), 2), (col("RunLog", "Finished (Local)"), 5), (col("RunLog", "Mode"), 5),
                                  (col("RunLog", "Status"), 4), (col("RunLog", "Message"), 7)],
            title="Refresh log", sort=(col("RunLog", "Run"), "Descending"))
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
    for page in (request_lookup(), overview(), frequent_patterns(), ticket_detail()):
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
