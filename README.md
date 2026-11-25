# De-Millimanized Device Dashboard

A small internal dashboard that pulls **De-Millimanize machine tickets** from the Freshservice helpdesk and makes them easy to search, filter, and review.

## Why this exists

Employees can request a retired ("de-Millimanized") device. That program isn't meant to give people a new device every few months, but right now there's no quick way to see how often someone has asked.

The dashboard lets the program owner type in a name and see right away:

- **Whether** that person has asked for a de-Millimanized device before
- **When** each request was made
- **What happened**: approved/given or denied

## Stakeholders

| Role | Person |
|---|---|
| Requestor / primary user | Shannon |
| Coordinator | Lorne |
| Repo owner / Developer | Michael Graeber |
| Developer | Kevin Concepcion |

## Scope

### Must have (core requirement)
- Search by employee name
- Show each matching request with its **date** and **outcome** (given / denied / pending)
- Data comes from De-Millimanize tickets in Freshservice. This includes both form-based tickets and older free-text tickets created before the form existed.

### Should have
- Total count of completed De-Millimanize tickets
- Filters by date range and status
- A flag for people who asked again within a short window, such as 3 months

### Nice to have
- Chart of requests by **practice**
- Chart of requests by **device type**
- Open the **Certificate of Destruction** through a link to the Freshservice ticket

### Out of scope
- Creating, editing, closing, or approving tickets. The dashboard is **read-only**.
- Changing the de-Millimanize approval process

## Data source

- **Freshservice API**: Access was first set up through Spark.
- The dashboard only **reads** ticket data. It never writes back to Freshservice.
- Credentials (API keys) are never stored in this repository. See [AGENTS.md](AGENTS.md) for the rules.

## Technology

**Power BI**, built on an Excel workbook that a Python extract rewrites twice a day. The Power BI design follows Michael's specification, merged with this project's rules.

- The **extract** (`python run.py extract`) reads Freshservice (read-only, as the ADM account). It finds the De-Millimanize tickets, decides each outcome, flags frequent requesters, and writes `DeMillimanize Requests.xlsx` with 6 tables: Requests, People, PersonRequests, FormAnswers, Unconfirmed and RunLog.
- Tickets the wording rules aren't sure about go to **Unconfirmed** and aren't counted until a person confirms them once.
- **Power BI** only reads that workbook. It never calls Freshservice and never needs an API key.
- The report has 4 pages:
  - **Overview** (opens first): the totals, requests by month, models and the latest requests.
  - **Request Lookup:** type a name, then see their history and the frequent flag.
  - **Frequent and Patterns**
  - **Ticket Detail and Data Quality**
- In Power BI Desktop, **Refresh** reloads the workbook. `tools\run-extract.cmd` updates the workbook on demand.
- The report is shared through the Power BI Service, so Microsoft sign-in controls who can open it. A *Program Owners* RLS role is included.
- Certificates of Destruction stay on the Freshservice ticket. The dashboard links to the ticket.

The reasons for this choice are recorded in [OVERVIEW.md](OVERVIEW.md).

## Repository guide

| File | Purpose |
|---|---|
| [README.md](README.md) | What this project is and why it exists (this file) |
| [OVERVIEW.md](OVERVIEW.md) | Current state of the project, updated with **every** change |
| [AGENTS.md](AGENTS.md) | Rules that AI coding agents (and humans) must follow in this repo |
| `extract/` | Python extract: API client, matching and outcome rules, workbook writer |
| `powerbi/` | Power BI model script (TMDL), theme and [build guide](powerbi/GUIDE.md) |
| `sample_data/` | **Fake** data generator for building the report without real data |
| `tests/` | Unit tests. They use fake data only. |
| `tools/` | Double-click launchers: `probe.cmd`, `run-extract.cmd`, `schedule-extract.cmd` |
| `run.py` | Entry point used by the launchers. It works from a UNC path. |
| `requirements.txt` | openpyxl (required) and pypdf (optional, reads Certificate of Destruction PDFs) |
| `data/` | The real workbook, run state, the outcome override file and the confirmation file. **Git-ignored. Contains real employee data.** |

## Getting started

**Requirements:** Windows, Python 3.13 (machine-wide install), and the `FRESHSERVICE_API_KEY` user environment variable on the ADM account.

**Run the tests** (no API key needed):

```powershell
python -m unittest discover -s tests -t .
```

**Probe the Freshservice API** (stage 1). This shows only field names and types, never employee data:

1. In **File Explorer** (not VS Code), open the `tools` folder and double-click `probe.cmd` as your normal account.
2. When asked, type the **ADM account password**. A second window opens and runs the probe as the ADM account.
3. When asked, enter one form ticket number and one older or archived ticket number, digits only.
4. The report is saved to `data\probe_report.json`.

**Run the extract:** double-click `tools\run-extract.cmd` in File Explorer and enter the ADM password. It writes `data\DeMillimanize Requests.xlsx`.

- The first run is a full run.
- Later runs only fetch changed tickets. To force a full run: `python run.py extract --full`.

**Schedule it** (twice daily, as the ADM account): double-click `tools\schedule-extract.cmd`. Confirm with IT policy first (see OVERVIEW.md, open questions).

**Correct an outcome by hand:** add a row to `data\outcome_overrides.csv`:

- Columns: `Ticket ID, Outcome, Reason, Reviewed By, Reviewed On`
- `Outcome` must be Approved, Denied, Pending or Needs Review.
- `Reviewed On` must be in `YYYY-MM-DD` format.

The next run applies it, with Outcome Source "Manual Override".

**Include archived tickets** (older than about a year): run `python run.py archive` once.

- A new scan starts at tickets created on or after **2023-07-01**, the same date as the data cutoff below. Change it with `DEDASH_ARCHIVE_SINCE`, or run `python run.py archive --all` to scan from the very first ticket.
- **Data cutoff:** tickets created before **2023-07-01** are left out of the workbook (earlier data isn't relevant). Change it with `DEDASH_DATA_START`; blank keeps everything.
- It reads the archived ticket list, which is slow: roughly 12 seconds a page, 4 at a time. From 2024 that is about 430 pages, so allow about an hour. The whole archive is about 1,140 pages.
- It can be stopped at any time and picks up where it left off. Later runs only read pages added since.
- Then run the extract again to rebuild the workbook. Until the scan has finished, the RunLog message says so.
- Only the subject of an archived ticket can be screened, so an archived request with a plain subject is missed.
- After changing the wording rules in `extract/classify.py`, run `python run.py archive --restart`.

**Confirm a ticket the rules weren't sure about:** these tickets are listed in the workbook's `Unconfirmed` sheet and on the report's Data Quality page. They aren't counted until someone answers. Add a row to `data\match_confirmations.csv`:

- Columns: `Ticket ID, Is De-Millimanize, Reviewed By, Reviewed On, Note`
- `Is De-Millimanize` must be Yes or No. Yes counts the ticket as a request. No removes it for good.
- Each ticket only needs an answer once. The next run applies it.

**Build the Power BI report:** follow [powerbi/GUIDE.md](powerbi/GUIDE.md). Start with fake data from `python run.py mock`. After changing the workbook columns, regenerate the model script with `python run.py tmdl`. To regenerate the 4 report pages, close Power BI Desktop and run `python run.py pages`.
