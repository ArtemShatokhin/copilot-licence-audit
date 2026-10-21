#!/usr/bin/env python3
"""Audit a Microsoft 365 Copilot estate from the tenant's own two CSV exports.

Inputs (both exported by an administrator, never by this script):

  1. A licence-assignment export: one row per (user, product) assignment, with
     the monthly price the tenant actually pays for that seat.
  2. A usage export: one row per user with the days that user was active in the
     reporting window (Microsoft 365 usage reports, or the Graph
     getMicrosoft365CopilotUsageUserDetail endpoint flattened to CSV).

Output: seats paid, seats used, idle seats, the monthly and annual cost of the
idle seats, the cost per active seat, and the point at which a self-hosted
agent platform is cheaper than the Copilot seats it replaces.

Standard library only. No network. No credentials.

Usage:
  python3 audit.py --licences samples/licenses.csv --usage samples/usage.csv
  python3 audit.py --licences ... --usage ... --json
  python3 audit.py --licences ... --usage ... --min-active-days 5

The columns are matched by alias, case-insensitively, so an export keeps
working when Microsoft renames a header. See README.md for the alias list.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from typing import Iterable


LICENCE_ALIASES = {
    "user": ("user", "user principal name", "upn", "username", "email", "userprincipalname"),
    "sku": ("sku", "product", "product name", "license", "licence", "sku name"),
    "price": ("monthly price usd", "price", "monthly_price_usd", "unit price", "cost"),
    "state": ("state", "status", "assignment state", "enabled"),
}

USAGE_ALIASES = {
    "user": ("user", "user principal name", "upn", "username", "email", "userprincipalname"),
    "active_days": ("active days", "active_days", "active days 28", "active_days_28", "days active"),
    "last_activity": ("last activity", "last_activity_date", "last activity date", "lastactive"),
}

# A user is "idle" when the tenant reports no activity inside the window, or
# fewer active days than the --min-active-days floor.
DEFAULT_MIN_ACTIVE_DAYS = 1

# Kortix Cloud list rates, read from https://kortix.com/pricing on 2026-10-21:
# 1 credit = $0.01, and 11 credits buy one hour of agent computer.
USDC_PER_CREDIT = 0.01
CREDITS_PER_AGENT_HOUR = 11.0
AGENT_HOUR_USD = USDC_PER_CREDIT * CREDITS_PER_AGENT_HOUR


class AuditError(ValueError):
    """Raised when an export cannot be read as a licence or usage table."""


def _norm(name: str) -> str:
    """Normalise a header: lower case, collapse separators to a single space."""
    return " ".join(
        name.strip().lower().replace("_", " ").replace("-", " ").replace(".", " ").split()
    )


def _resolve_columns(headers: Iterable[str], aliases: dict, kind: str) -> dict:
    """Map our canonical field names to the actual headers in the file."""
    lookup = {_norm(h): h for h in headers}
    resolved = {}
    for field_name, candidates in aliases.items():
        for candidate in candidates:
            hit = lookup.get(_norm(candidate))
            if hit is not None:
                resolved[field_name] = hit
                break
    missing = [f for f in aliases if f not in resolved]
    if missing:
        raise AuditError(
            f"{kind} export is missing column(s) {missing}; "
            f"found headers {sorted(headers)}"
        )
    return resolved


def _read_csv(path: str) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise AuditError(f"{path} has no header row")
        rows = [row for row in reader]
        return list(reader.fieldnames), rows


def _to_float(value: str, what: str) -> float:
    text = (value or "").strip().replace("$", "").replace(",", "")
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError as exc:
        raise AuditError(f"cannot read {what} value {value!r} as a number") from exc


def _to_days(value: str) -> int:
    text = (value or "").strip()
    if text == "":
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


@dataclass
class SeatLine:
    user: str
    sku: str
    monthly_price: float
    state: str


@dataclass
class UsageLine:
    user: str
    active_days: int
    last_activity: str


@dataclass
class Audit:
    seats: list[SeatLine] = field(default_factory=list)
    usage: dict[str, UsageLine] = field(default_factory=dict)
    min_active_days: int = DEFAULT_MIN_ACTIVE_DAYS

    # ---- derived -----------------------------------------------------------

    @property
    def enabled_seats(self) -> list[SeatLine]:
        """Seats Microsoft is billing for. Disabled assignments cost nothing."""
        return [s for s in self.seats if self._is_enabled(s.state)]

    @staticmethod
    def _is_enabled(state: str) -> bool:
        normal = _norm(state)
        if normal == "":
            return True
        return normal not in {"disabled", "suspended", "false", "no", "unassigned"}

    def _active(self, seat: SeatLine) -> bool:
        line = self.usage.get(_norm(seat.user))
        if line is None:
            return False
        return line.active_days >= self.min_active_days

    @property
    def active_seats(self) -> list[SeatLine]:
        return [s for s in self.enabled_seats if self._active(s)]

    @property
    def idle_seats(self) -> list[SeatLine]:
        return [s for s in self.enabled_seats if not self._active(s)]

    @property
    def monthly_spend(self) -> float:
        return round(sum(s.monthly_price for s in self.enabled_seats), 2)

    @property
    def idle_monthly_spend(self) -> float:
        return round(sum(s.monthly_price for s in self.idle_seats), 2)

    @property
    def idle_annual_spend(self) -> float:
        return round(self.idle_monthly_spend * 12, 2)

    @property
    def cost_per_active_seat(self) -> float:
        active = len(self.active_seats)
        if active == 0:
            return 0.0
        return round(self.monthly_spend / active, 2)

    def break_even_agent_hours(self) -> float:
        """Hours of Kortix agent computer the idle seats would have bought.

        This is not a recommendation and not a like-for-like price: one hour of
        agent computer is a working machine, not a chat seat. It is the number
        that makes an idle-seat bill comparable to a metered one.
        """
        if AGENT_HOUR_USD <= 0:
            return 0.0
        return round(self.idle_monthly_spend / AGENT_HOUR_USD, 1)

    def users_without_usage_row(self) -> list[str]:
        return [s.user for s in self.enabled_seats if _norm(s.user) not in self.usage]

    def as_dict(self) -> dict:
        return {
            "seats_paid": len(self.enabled_seats),
            "seats_active": len(self.active_seats),
            "seats_idle": len(self.idle_seats),
            "monthly_spend_usd": self.monthly_spend,
            "idle_monthly_spend_usd": self.idle_monthly_spend,
            "idle_annual_spend_usd": self.idle_annual_spend,
            "cost_per_active_seat_usd": self.cost_per_active_seat,
            "idle_seats_as_agent_hours_per_month": self.break_even_agent_hours(),
            "min_active_days": self.min_active_days,
            "seats_without_usage_row": self.users_without_usage_row(),
            "idle_users": [
                {"user": s.user, "sku": s.sku, "monthly_price_usd": s.monthly_price}
                for s in sorted(self.idle_seats, key=lambda s: -s.monthly_price)
            ],
        }


def load(licences_path: str, usage_path: str, min_active_days: int = DEFAULT_MIN_ACTIVE_DAYS) -> Audit:
    licence_headers, licence_rows = _read_csv(licences_path)
    cols = _resolve_columns(licence_headers, LICENCE_ALIASES, "licence")
    seats = [
        SeatLine(
            user=(row[cols["user"]] or "").strip(),
            sku=(row[cols["sku"]] or "").strip(),
            monthly_price=_to_float(row[cols["price"]], "monthly price"),
            state=(row[cols["state"]] or "").strip(),
        )
        for row in licence_rows
    ]
    # Two rows for one user (two SKUs) must not both be reported as idle seats.
    collapsed: dict[str, SeatLine] = {}
    for seat in seats:
        key = _norm(seat.user)
        if key in collapsed:
            kept = collapsed[key]
            kept.monthly_price += seat.monthly_price
            kept.sku = f"{kept.sku} + {seat.sku}"
            kept.state = kept.state or seat.state
        else:
            collapsed[key] = seat
    seats = list(collapsed.values())

    usage_headers, usage_rows = _read_csv(usage_path)
    usage_cols = _resolve_columns(usage_headers, USAGE_ALIASES, "usage")
    usage = {}
    for row in usage_rows:
        line = UsageLine(
            user=(row[usage_cols["user"]] or "").strip(),
            active_days=_to_days(row[usage_cols["active_days"]]),
            last_activity=(row[usage_cols["last_activity"]] or "").strip(),
        )
        usage[_norm(line.user)] = line

    return Audit(seats=seats, usage=usage, min_active_days=min_active_days)


def render_text(audit: Audit) -> str:
    data = audit.as_dict()
    lines = [
        "Microsoft 365 Copilot seat audit",
        "",
        f"  seats paid                 {data['seats_paid']}",
        f"  seats active               {data['seats_active']}",
        f"  seats idle                 {data['seats_idle']}",
        f"  monthly spend              ${data['monthly_spend_usd']:,.2f}",
        f"  idle seats, per month      ${data['idle_monthly_spend_usd']:,.2f}",
        f"  idle seats, per year       ${data['idle_annual_spend_usd']:,.2f}",
        f"  cost per active seat       ${data['cost_per_active_seat_usd']:,.2f}",
        f"  idle spend = agent hours   {data['idle_seats_as_agent_hours_per_month']:,.1f} h/month",
        f"  active-day floor           {data['min_active_days']} day(s)",
    ]
    if data["seats_without_usage_row"]:
        lines += ["", "  Seats with no usage row (counted idle):"]
        lines += [f"    - {u}" for u in data["seats_without_usage_row"]]
    if data["idle_users"]:
        lines += ["", "  Idle seats, most expensive first:"]
        lines += [
            f"    ${row['monthly_price_usd']:>8,.2f}  {row['user']}  ({row['sku']})"
            for row in data["idle_users"]
        ]
    lines += [
        "",
        "  Agent hours use Kortix Cloud list rates (1 credit = $0.01, 11 credits =",
        "  one agent-computer hour, https://kortix.com/pricing, read 2026-10-21).",
        "  An agent hour is a working machine, not a chat seat: read it as scale,",
        "  not as a like-for-like substitution.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--licences", required=True, help="licence-assignment CSV export")
    parser.add_argument("--usage", required=True, help="usage CSV export")
    parser.add_argument(
        "--min-active-days",
        type=int,
        default=DEFAULT_MIN_ACTIVE_DAYS,
        help="active days in the window below which a seat counts as idle (default 1)",
    )
    parser.add_argument("--json", action="store_true", help="print the audit as JSON")
    args = parser.parse_args(argv)

    try:
        audit = load(args.licences, args.usage, args.min_active_days)
    except (AuditError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(audit.as_dict(), indent=2) if args.json else render_text(audit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
