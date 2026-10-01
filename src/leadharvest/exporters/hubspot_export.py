"""HubSpot CRM push (V1, F13): find the company by domain (or exact name), update or create.

Like the Sheets rule for client columns, values already set in HubSpot are never overwritten:
an existing company only gets the properties that are empty there.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from leadharvest.clean.normalize import is_shared_domain
from leadharvest.exporters.base import ExportError
from leadharvest.http import parse_retry_after
from leadharvest.logging_setup import get_logger
from leadharvest.models import ExportResult, Lead, Run

log = get_logger("hubspot")

API = "https://api.hubapi.com"
PROPERTIES = ("name", "domain", "phone", "website", "address", "city", "country")
MIN_INTERVAL_S = 0.25  # stays under the CRM search API limit (~5 requests/second)
MAX_ATTEMPTS = 4


def lead_properties(lead: Lead) -> dict[str, str]:
    props = {
        "name": lead.business_name,
        "domain": lead.domain if lead.domain and not is_shared_domain(lead.domain) else None,
        "phone": lead.phone,
        "website": lead.website,
        "address": lead.address,
        "city": lead.city,
        "country": lead.country,
    }
    return {k: v for k, v in props.items() if v}


class HubSpotExporter:
    name = "hubspot"

    def __init__(
        self,
        token: str,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token:
            raise ExportError("HubSpot export needs HUBSPOT_ACCESS_TOKEN (private app token).")
        self.client = client or httpx.Client(timeout=20)
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.sleep = sleep
        self.clock = clock
        self._next_at = 0.0

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = self._next_at - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._next_at = self.clock() + MIN_INTERVAL_S
            response = self.client.request(method, API + path, headers=self.headers, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == MAX_ATTEMPTS:
                    break
                delay = parse_retry_after(response.headers.get("Retry-After")) or 2.0**attempt
                self.sleep(delay)
                continue
            if response.status_code >= 400:
                # Never include headers (token) in the error.
                raise ExportError(
                    f"HubSpot {method} {path} → HTTP {response.status_code}: {response.text[:200]}"
                )
            return response
        raise ExportError(f"HubSpot {method} {path} failed after {MAX_ATTEMPTS} attempts")

    def find_company(self, props: dict[str, str]) -> dict[str, Any] | None:
        if "domain" in props:
            prop, value = "domain", props["domain"]
        else:
            prop, value = "name", props["name"]
        body = {
            "filterGroups": [
                {"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}
            ],
            "properties": list(PROPERTIES),
            "limit": 2,
        }
        results = self._request("POST", "/crm/v3/objects/companies/search", json=body).json()
        found = results.get("results", [])
        if len(found) > 1:
            log.warning("HubSpot has several companies with %s=%s; updating the first", prop, value)
        return found[0] if found else None

    def export(self, leads: list[Lead], run: Run) -> ExportResult:
        created = updated = 0
        for lead in leads:
            props = lead_properties(lead)
            existing = self.find_company(props)
            if existing is None:
                self._request("POST", "/crm/v3/objects/companies", json={"properties": props})
                created += 1
                continue
            current = existing.get("properties") or {}
            missing = {k: v for k, v in props.items() if not current.get(k)}
            if missing:
                self._request(
                    "PATCH", f"/crm/v3/objects/companies/{existing['id']}",
                    json={"properties": missing},
                )  # fmt: skip
            updated += 1
        return ExportResult(
            exporter=self.name,
            target="HubSpot companies",
            rows_updated=updated,
            rows_appended=created,
        )
