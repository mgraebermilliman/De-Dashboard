# AGENTS.md: Rules for AI Agents

These rules apply to **every** AI coding agent (GitHub Copilot, Claude, ChatGPT, etc.) working in this repository. People contributing to the repo should follow them too. If a request conflicts with these rules, the agent must **stop and ask** before going ahead.

Read [README.md](README.md) for the project's purpose and [OVERVIEW.md](OVERVIEW.md) for its current state before making any change.

---

## 1. Data integrity

1. **Never make up data.** Do not invent ticket numbers, names, dates, statuses, counts, practices, or certificates. If data is missing, say so.
2. **Keep the source of truth.** Every number or record on the dashboard must trace back to a Freshservice ticket. Do not hardcode results.
3. **Mark mock data clearly.** Sample data used for development must be fake. It must live in a clearly named file, such as `sample_data/` or `*.mock.json`, and must never be shown as real.
4. **Don't change meaning quietly.** If you map Freshservice statuses to "Given / Denied / Pending," write the mapping down in code and in [OVERVIEW.md](OVERVIEW.md). Don't guess at statuses you don't recognize. Show them as "Unknown."
5. **Check before saying it works.** Don't say a feature works unless you have run it or tested it. If you couldn't verify it, say that.

## 2. Freshservice API: read-only

1. Use **GET requests only**. Never send POST, PUT, PATCH, or DELETE requests to Freshservice.
2. Respect API rate limits. Use pagination and backoff. Don't loop in a way that could flood the helpdesk.
3. Fetch only the fields the dashboard needs.

## 3. Secrets and credentials

1. **Never commit API keys, passwords, tokens, or connection strings.** This includes code, config files, notebooks, screenshots, and commit messages.
2. Load credentials from environment variables or a local `.env` file. The `.env` file **must** be listed in `.gitignore`.
3. Commit a `.env.example` that has placeholder values only.
4. Never print, log, or echo a secret, even partially.
5. If a secret is ever committed by accident, **stop and tell the repo owner right away**. Deleting it in a later commit is not enough.

## 4. Privacy of employee information

This dashboard shows employee names, request history, and possibly Certificates of Destruction.

1. **Do not commit real employee data** such as names, emails, ticket exports, CSVs, or certificate PDFs.
2. Do not paste real ticket contents into public tools, public issues, or outside services.
3. Show only the fields needed to meet the requirement: name, request date, outcome, and optionally practice, device type, and certificate.
4. The dashboard must be available **only to authorized users**. Don't add public sharing links or anonymous access.

## 5. Security

1. Follow the OWASP Top 10. Validate and escape all user input, including the name search box. Use parameterized queries, and never build SQL or HTML from raw strings.
2. Don't turn off TLS or certificate checks.
3. Add only well-known, maintained dependencies, and pin their versions. Tell the user why each new dependency is needed.
4. Downloaded certificates must come from the matching Freshservice ticket attachment only. Never accept an arbitrary file path or URL from the user.

## 6. Scope control

1. Build only what was asked for or what is listed in [README.md](README.md). Don't add extra features without approval.
2. Don't refactor, rename, or reformat code that has nothing to do with the task.
3. Keep it simple. This is a small internal tool, not a platform.

## 7. Git and repository safety

1. **Never** push, force-push, rewrite history, delete branches, or merge into `main` without explicit approval from the repo owner (**Michael Graeber**).
2. Work on a feature branch. Keep commits small and use clear messages that describe the change.
3. Never use `--no-verify` or bypass hooks or checks.
4. Ask before deleting any file you didn't create during the current task.

## 8. Required on every change

Before a change is finished, the agent must:

1. **Update [OVERVIEW.md](OVERVIEW.md).** Add a dated entry to the Change Log and update any section that is now out of date, such as the status, architecture, or open questions.
2. Update [README.md](README.md) if the scope, setup steps, or usage changed.
3. Confirm there are no secrets or real employee data in the changes.
4. Give the user a short summary: what changed, what was tested, and what still needs checking.

## 9. When in doubt

Stop and ask. A clarifying question costs less than a wrong number in front of the program owner.
