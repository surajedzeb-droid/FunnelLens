"""All HTTP calls to LeadSquared: auth, retries, pagination, parallel requests.

Endpoints and their exact request/response shapes are documented in
docs/LOGIC_SPEC.md section 1. Only those endpoints are called here --
FunnelLens is read-only (README Critical Rule 12) and never invents an
endpoint or field name.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from funnellens.settings import Settings
from funnellens.timeutil import from_lsq_utc_string, to_lsq_utc_string

logger = logging.getLogger("funnellens.lsq_client")

_SECRET_PARAM_RE = re.compile(r"(?i)(accessKey|secretKey)=[^&\s]*")


def mask_secrets(text: str) -> str:
    """Replaces accessKey/secretKey query values with '***' wherever they appear, for safe logging/errors."""
    return _SECRET_PARAM_RE.sub(r"\1=***", text)


class LSQError(Exception):
    """Base class for LeadSquared client errors. Messages are always passed through mask_secrets()."""


class LSQTransientError(LSQError):
    """Raised for HTTP 429/5xx responses -- retried by tenacity."""


class RecordLimitError(LSQError):
    """Raised instead of silently truncating when a search would exceed the configured record cap (README Rule 9)."""


class LSQClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self._settings = settings
        self._session = session or requests.Session()
        host = settings.secrets.api_host
        if host.startswith("http://") or host.startswith("https://"):
            self._base_url = host.rstrip("/")
        else:
            self._base_url = f"https://{host}"
        self._retry_attempts = settings.api.get("retry_attempts", 5)
        self._max_workers = settings.api.get("max_workers", 5)
        self._page_size = settings.api["page_size"]
        self._opp_page_size = settings.api["opportunity_search_page_size"]
        self._max_records = settings.api["max_records"]
        self._max_opp_records = settings.api["max_opportunity_search_records"]

    # ------------------------------------------------------------------
    # Low-level request plumbing
    # ------------------------------------------------------------------

    def _auth_params(self) -> dict[str, str]:
        return {
            "accessKey": self._settings.secrets.access_key,
            "secretKey": self._settings.secrets.secret_key,
        }

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                 json_body: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        """Single HTTP attempt. Raises LSQTransientError on 429/5xx (retried by _request_with_retry)."""
        url = f"{self._base_url}{path}"
        all_params = {**self._auth_params(), **(params or {})}
        try:
            response = self._session.request(
                method, url, params=all_params, json=json_body, timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise LSQTransientError(mask_secrets(f"Connection error calling {path}: {exc}")) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise LSQTransientError(
                mask_secrets(f"LeadSquared {path} returned {response.status_code}: {response.text[:500]}")
            )
        if response.status_code != 200:
            raise LSQError(
                mask_secrets(f"LeadSquared {path} returned {response.status_code}: {response.text[:500]}")
            )
        try:
            return response.json()
        except ValueError as exc:
            raise LSQError(mask_secrets(f"LeadSquared {path} returned non-JSON response: {exc}")) from exc

    def _call(self, method: str, path: str, *, params: dict[str, Any] | None = None,
               json_body: dict[str, Any] | None = None) -> Any:
        """Retries _request on transient errors with exponential back-off, bounded by config.retry_attempts."""

        @retry(
            retry=retry_if_exception_type(LSQTransientError),
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            reraise=True,
        )
        def _do() -> Any:
            return self._request(method, path, params=params, json_body=json_body)

        return _do()

    def run_parallel(self, calls: list[Callable[[], Any]]) -> list[Any]:
        """Runs many zero-arg callables (e.g. functools.partial(self.get_tasks_for_lead, lead_id)) in a
        thread pool bounded by config.api.max_workers, returning results in the same order as `calls`."""
        if not calls:
            return []
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            return list(executor.map(lambda fn: fn(), calls))

    # ------------------------------------------------------------------
    # Endpoints (docs/LOGIC_SPEC.md section 1)
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """Makes one cheap, read-only call (Users.Get) to confirm the credentials and host work."""
        self.get_users()
        return True

    def get_users(self) -> list[dict[str, Any]]:
        """LOGIC_SPEC.md 1.1 -- Users.Get. Returns the raw user list (active + inactive, unfiltered)."""
        return self._call("GET", "/v2/UserManagement.svc/Users.Get")

    def get_tasks_for_owner(self, owner_id: str) -> list[dict[str, Any]]:
        """LOGIC_SPEC.md 1.2 -- Task.svc/Retrieve. Live snapshot of this owner's pending tasks, capped at
        500 rows (no further pagination) -- matches the Apps Script exactly, per Phase 0 Resolved Decision 2."""
        body = {
            "Parameter": {"LookupName": "OwnerId", "LookupValue": owner_id, "StatusCode": 0},
            "Columns": {"Exclude_CSV": "Description"},
            "Sorting": {"ColumnName": "DueDate", "Direction": "0"},
            "Paging": {"Offset": 0, "RowCount": 500},
        }
        data = self._call("POST", "/v2/Task.svc/Retrieve", json_body=body)
        return (data or {}).get("List", [])

    def get_tasks_for_lead(self, lead_id: str) -> list[dict[str, Any]]:
        """LOGIC_SPEC.md 1.3 -- LeadManagement.svc/RetrieveTaskByLeadId."""
        data = self._call(
            "GET", "/v2/LeadManagement.svc/RetrieveTaskByLeadId", params={"leadId": lead_id}
        )
        return (data or {}).get("TaskList", [])

    def search_leads(self, lookup_name: str, lookup_value: str, sql_operator: str,
                      include_csv: str) -> list[dict[str, Any]]:
        """LOGIC_SPEC.md 1.4 -- LeadManagement.svc/Leads.Get, paginated fully (PageIndex/PageSize).
        Raises RecordLimitError instead of truncating silently if api.max_records is reached (README Rule 9)."""
        all_leads: list[dict[str, Any]] = []
        page_index = 1
        while True:
            body = {
                "Parameter": {"LookupName": lookup_name, "LookupValue": lookup_value, "SqlOperator": sql_operator},
                "Columns": {"Include_CSV": include_csv},
                "Sorting": {"ColumnName": "CreatedOn", "Direction": "1"},
                "Paging": {"PageIndex": page_index, "PageSize": self._page_size},
            }
            data = self._call("POST", "/v2/LeadManagement.svc/Leads.Get", json_body=body)
            page = data if isinstance(data, list) else (data or {}).get("List", [])
            if not page:
                break
            all_leads.extend(page)
            if len(all_leads) >= self._max_records:
                raise RecordLimitError(
                    f"search_leads({lookup_name} {sql_operator} {lookup_value}) exceeded "
                    f"api.max_records ({self._max_records}); narrow the date range."
                )
            if len(page) < self._page_size:
                break
            page_index += 1
        return all_leads

    def search_leads_created_between(self, start: datetime, end: datetime, include_csv: str) -> list[dict[str, Any]]:
        """Convenience wrapper: leads created within [start, end] (README Rule 2 -- every date query is bounded
        both ends). LeadSquared's Leads.Get only accepts one bound server-side, so the upper bound is applied
        client-side, matching lsqSearchAllPages + the created-date filter in runSyncForDate (LOGIC_SPEC.md 1.4, 7)."""
        raw = self.search_leads("CreatedOn", to_lsq_utc_string(start), ">=", include_csv)
        return [lead for lead in raw if from_lsq_utc_string(lead["CreatedOn"]) <= end]

    def search_leads_modified_between(self, start: datetime, end: datetime, include_csv: str) -> list[dict[str, Any]]:
        """Same pattern as search_leads_created_between, filtered on ModifiedOn instead."""
        raw = self.search_leads("ModifiedOn", to_lsq_utc_string(start), ">=", include_csv)
        return [lead for lead in raw if from_lsq_utc_string(lead["ModifiedOn"]) <= end]

    def search_opportunities_by_enrolled_date(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """LOGIC_SPEC.md 1.5 -- OpportunityManagement.svc/Retrieve/BySearchParameter, paginated.
        Raises RecordLimitError instead of truncating silently if api.max_opportunity_search_records is reached."""
        event_code = self._settings.opportunity_event_code
        stage_field = self._settings.fields["opportunity_stage"]
        source_field = self._settings.fields["source"]
        enrolled_field = self._settings.fields["enrolled_date"]

        fmt = "%Y-%m-%d %I:%M:%S %p"
        range_str = f"{start.strftime(fmt)} TO {end.strftime(fmt)}"
        advanced_search = (
            '{"GrpConOp":"And","QueryTimeZone":"India Standard Time","Conditions":['
            '{"Type":"Activity","ConOp":"and","RowCondition":[{"SubConOp":"And","LSO":"ActivityEvent",'
            f'"LSO_Type":"PAEvent","Operator":"eq","RSO":"{event_code}"}}]}},'
            '{"Type":"Activity","ConOp":"and","RowCondition":[{"SubConOp":"and",'
            f'"LSO":"{enrolled_field}","LSO_Type":"DateTime","Operator":"between","RSO":"{range_str}"}}]}}'
            "]}"
        )

        all_opps: list[dict[str, Any]] = []
        page_index = 1
        while True:
            body = {
                "OpportunityEventCode": event_code,
                "AdvancedSearch": advanced_search,
                "Columns": {"Include_CSV": f"Owner,Status,{stage_field},P_{source_field}"},
                "Paging": {"PageIndex": page_index, "PageSize": self._opp_page_size},
                "Sorting": {"ColumnName": "CreatedOn", "Direction": 1},
            }
            data = self._call("POST", "/v2/OpportunityManagement.svc/Retrieve/BySearchParameter", json_body=body)
            page = (data or {}).get("List", [])
            if not page:
                break
            all_opps.extend(page)
            if len(all_opps) >= self._max_opp_records:
                raise RecordLimitError(
                    f"search_opportunities_by_enrolled_date({start} to {end}) exceeded "
                    f"api.max_opportunity_search_records ({self._max_opp_records}); narrow the date range."
                )
            if len(page) < self._opp_page_size:
                break
            page_index += 1
        return all_opps

    def get_opportunities_of_lead(self, lead_id: str) -> dict[str, Any] | None:
        """LOGIC_SPEC.md 1.6 -- OpportunityManagement.svc/GetOpportunitiesOfLead. Returns the most recently
        modified opportunity's raw fields, or None if the lead has no opportunity."""
        stage_field = self._settings.fields["opportunity_stage"]
        status_field = self._settings.fields["opportunity_status"]
        enrolled_field = self._settings.fields["enrolled_date"]
        body = {
            "Columns": {"Include_CSV": f"{stage_field},{status_field},{enrolled_field}"},
            "Paging": {"PageIndex": 1, "PageSize": 5},
            "Sorting": {"ColumnName": "ModifiedOn", "Direction": "1"},
        }
        data = self._call(
            "POST", "/v2/OpportunityManagement.svc/GetOpportunitiesOfLead",
            params={"leadId": lead_id}, json_body=body,
        )
        # Response shape varies by account config -- handle both defensively (Phase 0 Resolved Decision 12).
        items = data.get("List", data) if isinstance(data, dict) else data
        if not items:
            return None
        return items[0]
