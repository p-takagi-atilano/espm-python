from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import date
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from espm.config import EspmConfig
from espm.errors import (
    EspmApiError,
    EspmAuthenticationError,
    EspmAuthorizationError,
    EspmNotFoundError,
    EspmReadOnlyError,
)
from espm.models import (
    Account,
    AdditionalIdentifier,
    AggregateMeterInfo,
    Building,
    BulkResult,
    ConsumptionRecord,
    Customer,
    Hierarchy,
    IndividualMeter,
    Meter,
    Notification,
    PendingConnection,
    PendingMeterShare,
    PendingPropertyShare,
    Property,
    PropertyMeterAssociation,
    PropertyMetric,
    PropertyMetrics,
    PropertyUse,
    ReportingMetric,
    ResourceLink,
    ScoreReason,
    SharingAction,
    UseDetail,
    UseDetailRevision,
    Verification,
    WasteRecord,
)
from espm.xml import (
    build_sharing_response,
    next_link,
    parse_account,
    parse_additional_identifiers,
    parse_aggregate_meter,
    parse_api_errors,
    parse_building,
    parse_consumption,
    parse_hierarchy,
    parse_individual_meter,
    parse_links,
    parse_meter,
    parse_meter_association,
    parse_metrics,
    parse_notifications,
    parse_pending_connections,
    parse_pending_meters,
    parse_pending_properties,
    parse_property,
    parse_property_use,
    parse_reporting_metrics,
    parse_score_reasons,
    parse_use_detail,
    parse_use_detail_revisions,
    parse_verification,
    parse_waste_data,
    parse_xml,
)


class EspmClient:
    """Asynchronous, GET-only client for ESPM web services."""

    def __init__(self, config: EspmConfig, *, http_client: httpx.AsyncClient | None = None):
        self.config = config
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=config.resolved_base_url,
            auth=httpx.BasicAuth(config.username, config.password.get_secret_value()),
            headers={"Accept": "application/xml", "User-Agent": config.user_agent},
            timeout=httpx.Timeout(config.read_timeout, connect=config.connect_timeout),
        )

    async def __aenter__(self) -> EspmClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        empty_404: bool = False,
    ) -> bytes | None:
        if method.upper() != "GET":
            raise EspmReadOnlyError("espm-python only permits GET requests")

        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self._http.request("GET", path, params=params, headers=headers)
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                if attempt >= self.config.max_retries:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))
                continue

            retryable = response.status_code in {429, 500, 502, 503, 504}
            if retryable and attempt < self.config.max_retries:
                await asyncio.sleep(0.25 * (2**attempt))
                continue
            if response.status_code == 404 and empty_404:
                return None
            if response.is_error:
                self._raise_api_error(response)
            return response.content
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_api_error(response: httpx.Response) -> None:
        message = response.reason_phrase or "Request failed"
        codes: tuple[str, ...] = ()
        if response.content:
            try:
                parsed_message, codes = parse_api_errors(parse_xml(response.content))
                message = parsed_message or message
            except Exception:  # malformed/non-XML error response
                pass
        kwargs = {
            "message": message,
            "status_code": response.status_code,
            "error_codes": codes,
            "request_id": response.headers.get("X-Request-ID"),
        }
        if response.status_code == 401:
            raise EspmAuthenticationError(**kwargs)
        if response.status_code == 403:
            raise EspmAuthorizationError(**kwargs)
        if response.status_code == 404:
            raise EspmNotFoundError(**kwargs)
        raise EspmApiError(**kwargs)

    async def _xml(self, path: str, **kwargs: Any) -> Any:
        content = await self._request("GET", path, **kwargs)
        return parse_xml(content) if content is not None else None

    async def _respond_to_share(self, path: str, action: SharingAction, note: str | None) -> None:
        if not self.config.allow_mutations:
            raise EspmReadOnlyError(
                "connection/share responses require EspmConfig(allow_mutations=True)"
            )
        response = await self._http.post(
            path,
            content=build_sharing_response(action.value, note),
            headers={"Content-Type": "application/xml", "Accept": "application/xml"},
        )
        if response.is_error:
            self._raise_api_error(response)

    async def _paginated_links(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> tuple[ResourceLink, ...]:
        page = 1
        gathered: list[ResourceLink] = []
        while True:
            root = await self._xml(
                path,
                params={**(params or {}), "page": page},
                empty_404=True,
            )
            if root is None:
                break
            following = next_link(root)
            gathered.extend(
                link for link in parse_links(root) if "next" not in (link.description or "").lower()
            )
            if following is None:
                break
            next_page = httpx.QueryParams(urlparse(following).query).get("page")
            page = int(next_page) if next_page else page + 1
        return tuple(gathered)

    async def _bulk[T](
        self,
        identifiers: Iterable[int],
        operation: Callable[[int], Awaitable[T]],
    ) -> tuple[BulkResult[T], ...]:
        """Run independent query operations concurrently while preserving input order."""
        semaphore = asyncio.Semaphore(4)

        async def run(identifier: int) -> BulkResult[T]:
            async with semaphore:
                return BulkResult(id=identifier, value=await operation(identifier))

        return tuple(await asyncio.gather(*(run(identifier) for identifier in identifiers)))

    async def get_account(self) -> Account:
        return parse_account(await self._xml("/account"))

    async def list_customers(self) -> tuple[ResourceLink, ...]:
        root = await self._xml("/customer/list", empty_404=True)
        return parse_links(root) if root is not None else ()

    async def get_customer(self, customer_id: int) -> Customer:
        return cast(
            Customer,
            parse_account(await self._xml(f"/customer/{customer_id}"), customer_id=customer_id),
        )

    async def list_properties(self, account_id: int) -> tuple[ResourceLink, ...]:
        root = await self._xml(f"/account/{account_id}/property/list", empty_404=True)
        return parse_links(root) if root is not None else ()

    async def list_changed_properties(
        self, customer_id: int, since: date
    ) -> tuple[ResourceLink, ...]:
        return await self._paginated_links(
            f"/customer/{customer_id}/property/whatChanged",
            params={"date": since.isoformat()},
        )

    async def get_property(self, property_id: int) -> Property:
        return parse_property(await self._xml(f"/property/{property_id}"), property_id)

    async def bulk_get_properties(
        self, property_ids: Iterable[int]
    ) -> tuple[BulkResult[Property], ...]:
        """Get properties concurrently, preserving the input order and property IDs."""
        return await self._bulk(property_ids, self.get_property)

    async def get_property_hierarchy(self, property_id: int) -> Hierarchy:
        return parse_hierarchy(await self._xml(f"/idHierarchy/property/{property_id}"))

    async def list_property_identifiers(self, property_id: int) -> tuple[AdditionalIdentifier, ...]:
        root = await self._xml(f"/property/{property_id}/identifier/list", empty_404=True)
        return parse_additional_identifiers(root) if root is not None else ()

    async def get_property_identifier(
        self, property_id: int, identifier_id: int
    ) -> AdditionalIdentifier:
        root = await self._xml(f"/property/{property_id}/identifier/{identifier_id}")
        identifiers = parse_additional_identifiers(root)
        if not identifiers:
            raise EspmApiError("ESPM returned no property identifier")
        return identifiers[0]

    async def get_property_verification(self, property_id: int) -> Verification | None:
        root = await self._xml(f"/property/{property_id}/verification", empty_404=True)
        return parse_verification(root) if root is not None else None

    async def list_buildings(self, property_id: int) -> tuple[ResourceLink, ...]:
        root = await self._xml(f"/property/{property_id}/building/list", empty_404=True)
        return parse_links(root) if root is not None else ()

    async def get_building(self, building_id: int) -> Building:
        return parse_building(await self._xml(f"/building/{building_id}"), building_id)

    async def list_building_properties(self, building_id: int) -> tuple[ResourceLink, ...]:
        root = await self._xml(f"/building/{building_id}/property/list", empty_404=True)
        return parse_links(root) if root is not None else ()

    async def list_property_uses(self, property_id: int) -> tuple[ResourceLink, ...]:
        root = await self._xml(f"/property/{property_id}/propertyUse/list", empty_404=True)
        return parse_links(root) if root is not None else ()

    async def get_property_use(self, property_use_id: int) -> PropertyUse:
        return parse_property_use(
            await self._xml(f"/propertyUse/{property_use_id}"), property_use_id
        )

    async def bulk_list_property_uses(
        self, property_ids: Iterable[int]
    ) -> tuple[BulkResult[tuple[ResourceLink, ...]], ...]:
        """List property uses concurrently, preserving the input property IDs."""
        return await self._bulk(property_ids, self.list_property_uses)

    async def bulk_get_property_uses(
        self, property_use_ids: Iterable[int]
    ) -> tuple[BulkResult[PropertyUse], ...]:
        """Get property uses concurrently, preserving the input order and IDs."""
        return await self._bulk(property_use_ids, self.get_property_use)

    async def list_changed_property_uses(
        self, customer_id: int, since: date
    ) -> tuple[ResourceLink, ...]:
        return await self._paginated_links(
            f"/customer/{customer_id}/propertyUse/whatChanged",
            params={"date": since.isoformat()},
        )

    async def list_changed_use_details(
        self, customer_id: int, since: date
    ) -> tuple[ResourceLink, ...]:
        return await self._paginated_links(
            f"/customer/{customer_id}/useDetails/whatChanged",
            params={"date": since.isoformat()},
        )

    async def get_property_use_hierarchy(self, property_use_id: int) -> Hierarchy:
        return parse_hierarchy(await self._xml(f"/idHierarchy/propertyUse/{property_use_id}"))

    async def get_use_detail(self, use_detail_id: int) -> UseDetail:
        root = await self._xml(f"/useDetails/{use_detail_id}")
        return parse_use_detail(root)

    async def get_use_detail_hierarchy(self, use_detail_id: int) -> Hierarchy:
        return parse_hierarchy(await self._xml(f"/idHierarchy/useDetails/{use_detail_id}"))

    async def get_use_detail_revisions(
        self,
        property_use_id: int,
        *,
        current_as_of_start: date | None = None,
        current_as_of_end: date | None = None,
    ) -> tuple[UseDetailRevision, ...]:
        params = _date_params(
            currentAsOfStart=current_as_of_start,
            currentAsOfEnd=current_as_of_end,
        )
        root = await self._xml(
            f"/propertyUse/{property_use_id}/useDetailsRevisions",
            params=params,
            empty_404=True,
        )
        return parse_use_detail_revisions(root) if root is not None else ()

    async def list_meters(
        self, property_id: int, *, my_access_only: bool | None = None
    ) -> tuple[ResourceLink, ...]:
        params = {} if my_access_only is None else {"myAccessOnly": str(my_access_only).lower()}
        root = await self._xml(f"/property/{property_id}/meter/list", params=params, empty_404=True)
        return parse_links(root) if root is not None else ()

    async def get_meter(self, meter_id: int) -> Meter:
        return parse_meter(await self._xml(f"/meter/{meter_id}"), meter_id)

    async def bulk_list_meters(
        self,
        property_ids: Iterable[int],
        *,
        my_access_only: bool | None = None,
    ) -> tuple[BulkResult[tuple[ResourceLink, ...]], ...]:
        """List meters concurrently, preserving the input property IDs."""
        return await self._bulk(
            property_ids,
            lambda property_id: self.list_meters(property_id, my_access_only=my_access_only),
        )

    async def bulk_get_meters(self, meter_ids: Iterable[int]) -> tuple[BulkResult[Meter], ...]:
        """Get meters concurrently, preserving the input order and meter IDs."""
        return await self._bulk(meter_ids, self.get_meter)

    async def get_meter_hierarchy(self, meter_id: int) -> Hierarchy:
        return parse_hierarchy(await self._xml(f"/idHierarchy/meter/{meter_id}"))

    async def list_changed_meters(self, customer_id: int, since: date) -> tuple[ResourceLink, ...]:
        return await self._paginated_links(
            f"/customer/{customer_id}/meter/whatChanged",
            params={"date": since.isoformat()},
        )

    async def list_changed_property_meters(
        self, property_id: int, since: date
    ) -> tuple[ResourceLink, ...]:
        return await self._paginated_links(
            f"/property/{property_id}/meter/whatChanged",
            params={"date": since.isoformat()},
        )

    async def list_changed_consumption_meters(
        self, customer_id: int, since: date
    ) -> tuple[ResourceLink, ...]:
        return await self._paginated_links(
            f"/customer/{customer_id}/meter/consumptionData/whatChanged",
            params={"date": since.isoformat()},
        )

    async def get_property_meter_association(self, property_id: int) -> PropertyMeterAssociation:
        return parse_meter_association(
            await self._xml(f"/association/property/{property_id}/meter")
        )

    async def get_aggregate_meter(self, meter_id: int) -> AggregateMeterInfo:
        return parse_aggregate_meter(await self._xml(f"/meter/{meter_id}/aggregateMeter"), meter_id)

    async def list_individual_meters(self, meter_id: int) -> tuple[ResourceLink, ...]:
        root = await self._xml(f"/meter/{meter_id}/individual/list", empty_404=True)
        return parse_links(root) if root is not None else ()

    async def get_individual_meter(self, individual_meter_id: int) -> IndividualMeter:
        return parse_individual_meter(await self._xml(f"/meter/individual/{individual_meter_id}"))

    async def get_consumption_hierarchy(self, consumption_data_id: int) -> Hierarchy:
        return parse_hierarchy(
            await self._xml(f"/idHierarchy/consumptionData/{consumption_data_id}")
        )

    async def get_meter_consumption(
        self,
        meter_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[ConsumptionRecord, ...]:
        params = _date_params(startDate=start_date, endDate=end_date)
        page = 1
        records: list[ConsumptionRecord] = []
        while True:
            page_params = {**params, "page": page}
            root = await self._xml(
                f"/meter/{meter_id}/consumptionData",
                params=page_params,
                empty_404=True,
            )
            if root is None:
                break
            batch = parse_consumption(root)
            records.extend(batch)
            following = next_link(root)
            if following:
                parsed = urlparse(following)
                query = httpx.QueryParams(parsed.query)
                next_page = query.get("page")
                page = int(next_page) if next_page else page + 1
            elif len(batch) == 120:
                page += 1
            else:
                break
        return tuple(records)

    async def bulk_get_meter_consumption(
        self,
        meter_ids: Iterable[int],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[BulkResult[tuple[ConsumptionRecord, ...]], ...]:
        """Get meter consumption concurrently, preserving the input meter IDs."""
        return await self._bulk(
            meter_ids,
            lambda meter_id: self.get_meter_consumption(
                meter_id,
                start_date=start_date,
                end_date=end_date,
            ),
        )

    async def get_meter_waste_data(
        self,
        meter_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[WasteRecord, ...]:
        params = _date_params(startDate=start_date, endDate=end_date)
        page = 1
        records: list[WasteRecord] = []
        while True:
            root = await self._xml(
                f"/meter/{meter_id}/wasteData",
                params={**params, "page": page},
                empty_404=True,
            )
            if root is None:
                break
            batch = parse_waste_data(root)
            records.extend(batch)
            following = next_link(root)
            if following:
                next_page = httpx.QueryParams(urlparse(following).query).get("page")
                page = int(next_page) if next_page else page + 1
            elif len(batch) == 120:
                page += 1
            else:
                break
        return tuple(records)

    async def get_property_metrics(
        self,
        property_id: int,
        *,
        year: int,
        month: int,
        metrics: Iterable[str],
        measurement_system: str = "EPA",
    ) -> PropertyMetrics:
        return await self._get_metrics(
            property_id, year, month, metrics, measurement_system, monthly=False
        )

    async def bulk_get_property_metrics(
        self,
        property_ids: Iterable[int],
        *,
        year: int,
        month: int,
        metrics: Iterable[str],
        measurement_system: str = "EPA",
    ) -> tuple[BulkResult[PropertyMetrics], ...]:
        """Get the same metrics for properties concurrently, preserving input IDs."""
        metric_names = tuple(metrics)
        return await self._bulk(
            property_ids,
            lambda property_id: self.get_property_metrics(
                property_id,
                year=year,
                month=month,
                metrics=metric_names,
                measurement_system=measurement_system,
            ),
        )

    async def get_monthly_property_metrics(
        self,
        property_id: int,
        *,
        year: int,
        month: int,
        metrics: Iterable[str],
        measurement_system: str = "EPA",
    ) -> PropertyMetrics:
        return await self._get_metrics(
            property_id, year, month, metrics, measurement_system, monthly=True
        )

    async def _get_metrics(
        self,
        property_id: int,
        year: int,
        month: int,
        metrics: Iterable[str],
        measurement_system: str,
        *,
        monthly: bool,
    ) -> PropertyMetrics:
        names = tuple(dict.fromkeys(metrics))
        if not names:
            raise ValueError("at least one metric name is required")
        if not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        if measurement_system not in {"EPA", "METRIC"}:
            raise ValueError("measurement_system must be 'EPA' or 'METRIC'")
        gathered: list[PropertyMetric] = []
        suffix = "/monthly" if monthly else ""
        for batch in _chunks(names, 10):
            root = await self._xml(
                f"/property/{property_id}/metrics{suffix}",
                params={"year": year, "month": month, "measurementSystem": measurement_system},
                headers={"PM-Metrics": ", ".join(batch)},
            )
            gathered.extend(parse_metrics(root, property_id, year, month).metrics)
        by_name = {metric.name: metric for metric in gathered}
        return PropertyMetrics(
            property_id=property_id,
            year=year,
            month=month,
            measurement_system=measurement_system,
            metrics=tuple(by_name[name] for name in names if name in by_name),
        )

    async def get_reasons_for_no_score(
        self, property_id: int, *, year: int, month: int
    ) -> tuple[ScoreReason, ...]:
        root = await self._xml(
            f"/property/{property_id}/reasonsForNoScore",
            params={"year": year, "month": month},
            empty_404=True,
        )
        return parse_score_reasons(root) if root is not None else ()

    async def get_reasons_for_no_water_score(
        self, property_id: int, *, year: int, month: int
    ) -> tuple[ScoreReason, ...]:
        root = await self._xml(
            f"/property/{property_id}/reasonsForNoWaterScore",
            params={"year": year, "month": month},
            empty_404=True,
        )
        return parse_score_reasons(root) if root is not None else ()

    async def get_property_use_detail_metrics(
        self,
        property_id: int,
        *,
        year: int,
        month: int,
        measurement_system: str = "EPA",
    ) -> PropertyMetrics:
        if not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        if measurement_system not in {"EPA", "METRIC"}:
            raise ValueError("measurement_system must be 'EPA' or 'METRIC'")
        root = await self._xml(
            f"/property/{property_id}/useDetails/metrics",
            params={"year": year, "month": month, "measurementSystem": measurement_system},
        )
        return parse_metrics(root, property_id, year, month)

    async def list_reporting_metrics(
        self,
        *,
        group_ids: Iterable[int] | None = None,
        available_to_custom_metrics: bool | None = None,
    ) -> tuple[ReportingMetric, ...]:
        params: dict[str, str] = {}
        if group_ids is not None:
            params["groupIds"] = ",".join(str(group_id) for group_id in group_ids)
        if available_to_custom_metrics is not None:
            params["availableToCustomMetrics"] = str(available_to_custom_metrics).lower()
        root = await self._xml("/reports/metrics", params=params, empty_404=True)
        return parse_reporting_metrics(root) if root is not None else ()

    async def list_pending_connections(self) -> tuple[PendingConnection, ...]:
        root = await self._xml("/connect/account/pending/list", empty_404=True)
        return parse_pending_connections(root) if root is not None else ()

    async def respond_to_connection(
        self,
        account_id: int,
        action: SharingAction,
        *,
        note: str | None = None,
    ) -> None:
        await self._respond_to_share(f"/connect/account/{account_id}", action, note)

    async def list_pending_property_shares(self) -> tuple[PendingPropertyShare, ...]:
        root = await self._xml("/share/property/pending/list", empty_404=True)
        return parse_pending_properties(root) if root is not None else ()

    async def respond_to_property_share(
        self,
        property_id: int,
        action: SharingAction,
        *,
        note: str | None = None,
    ) -> None:
        await self._respond_to_share(f"/share/property/{property_id}", action, note)

    async def list_pending_meter_shares(self) -> tuple[PendingMeterShare, ...]:
        root = await self._xml("/share/meter/pending/list", empty_404=True)
        return parse_pending_meters(root) if root is not None else ()

    async def respond_to_meter_share(
        self,
        meter_id: int,
        action: SharingAction,
        *,
        note: str | None = None,
    ) -> None:
        await self._respond_to_share(f"/share/meter/{meter_id}", action, note)

    async def list_notifications(self) -> tuple[Notification, ...]:
        # clear=false is important: clear=true mutates notification state.
        root = await self._xml("/notification/list", params={"clear": "false"}, empty_404=True)
        return parse_notifications(root) if root is not None else ()


def _date_params(**values: date | None) -> dict[str, str]:
    return {key: value.isoformat() for key, value in values.items() if value is not None}


def _chunks[T](values: tuple[T, ...], size: int) -> Iterable[tuple[T, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]
