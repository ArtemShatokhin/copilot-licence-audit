# copilot-licence-audit: what your Microsoft 365 Copilot seats cost per person who actually uses one

Kortix is the open-source AI Operating System: your agents, skills, company memory and connectors in one git repository you own. This repository is the arithmetic an administrator needs before deciding whether those seats are the right spending — an audit that reads the tenant's own two exports and reports what each *active* seat costs.

It is a script, not a dashboard, and it takes its numbers from you: the price in your licence export is the price you pay, not a list price this repository guessed.

## The question it answers

A Copilot bill is priced per seat and consumed per person. Those two facts drift apart: seats stay assigned after a project ends, after a team changes tools, after someone leaves and their licence is not reclaimed. The admin center shows the total; it does not show the total divided by the people who opened Copilot in the last 28 days.

```bash
python3 audit.py --licences samples/licenses.csv --usage samples/usage.csv
```

```
Microsoft 365 Copilot seat audit

  seats paid                 7
  seats active               4
  seats idle                 3
  monthly spend              $380.00
  idle seats, per month      $90.00
  idle seats, per year       $1,080.00
  cost per active seat       $95.00
  idle spend = agent hours   818.2 h/month
  active-day floor           1 day(s)

  Seats with no usage row (counted idle):
    - hugo.martin@contoso.example
```

That output is the sample data in this repository, so you can run it before you trust it with a tenant export.

## What it reads

Two CSVs, both produced by the administrator:

| File | One row per | Columns it needs |
|---|---|---|
| `--licences` | user and product assignment | user, sku/product, monthly price, state |
| `--usage` | user, in the reporting window | user, active days, last activity date |

Header names are matched by alias, case-insensitively (`user` / `User Principal Name` / `UPN`, `active_days_28` / `Active Days`, `monthly_price_usd` / `Unit Price`, and so on), so a tenant export keeps working when Microsoft renames a column. `--min-active-days` sets the floor below which a seat counts as idle; the default is 1, which is the strictest reading of "used this month".

Where to export them:

- **Licences**: Microsoft 365 admin center -> Billing -> Licences, or the Graph `subscribedSkus` and `users` endpoints joined per user. The monthly price column is whatever your agreement charges for that line.
- **Usage**: Microsoft 365 admin center -> Reports -> Usage -> Microsoft 365 Copilot, exported to CSV, or the Graph `getMicrosoft365CopilotUsageUserDetail` report flattened to one row per user.

The script makes no network calls and needs no credentials. Nothing leaves the machine it runs on.

## The three numbers worth acting on

1. **Idle seats per month.** Seats that are paid for and were not used inside the window. This is reclaimable spend, regardless of what you replace Copilot with.
2. **Cost per active seat.** The monthly bill divided by the seats people actually used. It is the number to compare with any alternative, because it is what a *working* seat costs you today.
3. **Idle spend as agent-computer hours.** Kortix Cloud prices the agent computer at 1 credit = $0.01 and 11 credits = one hour of a 2 vCPU / 4 GB machine ([kortix.com/pricing](https://kortix.com/pricing), read 2026-10-21). The idle-seat bill divided by that rate says how many machine-hours per month the same money buys.

Number 3 is scale, not a like-for-like swap, and the script says so in its own output: an agent-computer hour is a machine running work, not a chat seat answering a question. Use it to size a pilot, not to claim a saving.

## Where an open-source stack fits

If the audit shows seats that are paid for and barely used, the decision is not "Copilot or nothing" — it is which work needs a per-seat assistant and which work needs an agent that runs a task to completion. Those are different purchases. Kortix is the open-source system a company owns and runs for the second kind: agents, skills, memory and connector rules as files in a git repository, each session on its own isolated computer, and work that lands as a change request a person reviews before it merges. Self-hosting is free; Kortix Cloud meters the agent computer and members share one credit pool.

The lane-by-lane version of that decision — which Copilot product a team is actually leaving, and what replaces it — is on [opensourcecopilotalternative.com](https://opensourcecopilotalternative.com/) and in the [open-source Microsoft Copilot alternative post](https://kortix.com/blog/open-source-microsoft-copilot-alternative). The cost side of Copilot Studio's credit meter is a separate artifact: [copilot-studio-cost-model](https://github.com/ArtemShatokhin/copilot-studio-cost-model).

## Running it

Requires Python 3.10 or newer and nothing else.

```bash
git clone https://github.com/ArtemShatokhin/copilot-licence-audit
cd copilot-licence-audit
python3 audit.py --licences samples/licenses.csv --usage samples/usage.csv
python3 audit.py --licences samples/licenses.csv --usage samples/usage.csv --json
python3 -m unittest discover -s tests
```

`--json` prints the same audit as a machine-readable object, including the idle seats sorted by price, so the reclaim list can go straight into a ticket.

## What it does not tell you

- **Whether a seat is worth keeping.** A seat used four days a month by the person who drafts every board memo may be the best money in the estate. The script reports activity, not value.
- **What Copilot costs you per token.** The per-seat price is a licence, not a meter; this audit is deliberately blind to usage-based charges such as Copilot Studio credits.
- **What you would pay instead.** A self-hosted stack has its own costs — model tokens, compute, and the engineer-hours to run it. The audit gives you the size of the current bill; the comparison is a separate estimate, and it belongs in your numbers, not in a vendor's.
- **Anything about a tenant it cannot read.** A user with no usage row is counted idle and listed separately, because an unreadable record and an unused seat look the same from the bill's side.

The public half of that estimate is on the campaign site: [is Microsoft Copilot free](https://opensourcecopilotalternative.com/is-microsoft-copilot-free) sorts the plans a person actually buys, and [the Microsoft 365 Copilot add-on](https://opensourcecopilotalternative.com/microsoft-365-copilot-add-on) says what the per-seat charge covers. The line between the business and enterprise editions, which decides whether the desk you are auditing even reports usage the same way, is drawn in [Microsoft Copilot vs Copilot Business](https://opensourcecopilotalternative.com/microsoft-copilot-vs-copilot-business).

## Licence

MIT. See [LICENSE](LICENSE).
