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

**Power BI**, saved as a Power BI Project (`.pbip`) so the report can be tracked in git.

- Data is pulled from the Freshservice API (read-only) by a small Python extract script. The script finds and classifies the tickets and looks up each person's practice in Active Directory. Power BI reads the script's output file.
- The extract runs twice daily on a schedule. In Power BI Desktop, **Refresh** reloads the latest file, and a "Run extract now" shortcut updates the file on demand.
- The report is shared through the Power BI Service, so Microsoft sign-in controls who can open it.
- Certificates of Destruction stay on the Freshservice ticket. The dashboard links to the ticket.

The reasons for this choice are recorded in [OVERVIEW.md](OVERVIEW.md).

## Repository guide

| File | Purpose |
|---|---|
| [README.md](README.md) | What this project is and why it exists (this file) |
| [OVERVIEW.md](OVERVIEW.md) | Current state of the project, updated with **every** change |
| [AGENTS.md](AGENTS.md) | Rules that AI coding agents (and humans) must follow in this repo |
| `extract/` | Python extract script (standard library only) |
| `tests/` | Unit tests. They use fake data only. |
| `tools/` | Double-click launchers (for example `probe.cmd`) |
| `run.py` | Entry point used by the launchers. It works from a UNC path. |
| `data/` | Extracted data. **Git-ignored. Contains real employee data.** |

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
