from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EspmModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        """Serialize the model, omitting recursively preserved raw API fields by default."""
        value = self.model_dump(mode="json")
        return value if include_raw else _without_raw(value)


def _without_raw(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_raw(item) for key, item in value.items() if key != "raw"}
    if isinstance(value, list):
        return [_without_raw(item) for item in value]
    return value


class SharingAction(StrEnum):
    ACCEPT = "Accept"
    REJECT = "Reject"


class ResourceLink(EspmModel):
    id: int | None = None
    href: str
    hint: str | None = None
    http_method: str | None = None
    description: str | None = None


class Address(EspmModel):
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class Audit(EspmModel):
    created_by: str | None = None
    created_date: datetime | None = None
    last_updated_by: str | None = None
    last_updated_date: datetime | None = None


class Account(EspmModel):
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    organization: str | None = None
    job_title: str | None = None
    phone: str | None = None
    address: Address | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Customer(Account):
    pass


class GrossFloorArea(EspmModel):
    value: Decimal | None = None
    units: str | None = None
    temporary: bool | None = None
    default: bool | None = None


class Property(EspmModel):
    id: int
    name: str | None = None
    primary_function: str | None = None
    address: Address | None = None
    year_built: int | None = None
    construction_status: str | None = None
    number_of_buildings: int | None = None
    gross_floor_area: GrossFloorArea | None = None
    occupancy_percentage: int | None = None
    is_federal_property: bool | None = None
    notes: str | None = None
    access_level: str | None = None
    audit: Audit | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Building(Property):
    pass


class Hierarchy(EspmModel):
    account_id: int | None = None
    property_id: int | None = None
    property_use_id: int | None = None
    meter_id: int | None = None
    consumption_data_id: int | None = None


class UseDetail(EspmModel):
    name: str
    value: Any = None
    id: int | None = None
    units: str | None = None
    current_as_of: date | None = None
    temporary: bool | None = None
    default: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PropertyUse(EspmModel):
    id: int
    type: str
    name: str | None = None
    use_details: tuple[UseDetail, ...] = ()
    audit: Audit | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class UseDetailRevision(EspmModel):
    current_as_of: date | None = None
    details: tuple[UseDetail, ...] = ()
    raw: dict[str, Any] = Field(default_factory=dict)


class AdditionalIdentifierType(EspmModel):
    id: int | None = None
    name: str | None = None
    description: str | None = None
    group: str | None = None
    standard_approved: bool | None = None


class AdditionalIdentifier(EspmModel):
    id: int | None = None
    identifier_type: AdditionalIdentifierType | None = None
    description: str | None = None
    value: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Verification(EspmModel):
    period_ending_date: str | None = None
    verification_date: date | None = None
    name: str | None = None
    title: str | None = None
    organization: str | None = None
    phone: str | None = None
    email: str | None = None
    postal_code: str | None = None
    professional_designations: tuple[dict[str, Any], ...] = ()
    audit: Audit | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Meter(EspmModel):
    id: int
    type: str | None = None
    name: str | None = None
    unit_of_measure: str | None = None
    metered: bool | None = None
    first_bill_date: date | None = None
    in_use: bool | None = None
    inactive_date: date | None = None
    aggregate_meter: bool | None = None
    other_description: str | None = None
    access_level: str | None = None
    audit: Audit | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class MeterAssociationGroup(EspmModel):
    meter_ids: tuple[int, ...] = ()
    representation_type: str | None = None


class PropertyMeterAssociation(EspmModel):
    energy: MeterAssociationGroup | None = None
    water: MeterAssociationGroup | None = None
    waste: MeterAssociationGroup | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class DemandTracking(EspmModel):
    demand: Decimal | None = None
    demand_cost: Decimal | None = None


class ConsumptionRecord(EspmModel):
    id: int | None = None
    usage: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    estimated_value: bool | None = None
    cost: Decimal | None = None
    demand_tracking: DemandTracking | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class WasteDestination(EspmModel):
    landfill_percentage: Decimal | None = None
    incineration_percentage: Decimal | None = None
    waste_to_energy_percentage: Decimal | None = None
    unknown_percentage: Decimal | None = None


class WasteRecord(EspmModel):
    id: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    quantity: Decimal | None = None
    times_emptied: Decimal | None = None
    average_percent_full: Decimal | None = None
    cost: Decimal | None = None
    estimated_value: bool | None = None
    disposal_destination: WasteDestination | None = None
    audit: Audit | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AggregateMeterInfo(EspmModel):
    meter_id: int
    is_aggregate: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class IndividualMeter(EspmModel):
    id: int | None = None
    meter_id: int | None = None
    custom_id: str | None = None
    custom_id_name: str | None = None
    service_address: str | None = None
    in_use: bool | None = None
    inactive_date: date | None = None
    audit: Audit | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class MetricValue(EspmModel):
    value: Decimal | str | None = None
    month: int | None = None
    year: int | None = None


class PropertyMetric(EspmModel):
    name: str
    value: Decimal | str | None = None
    uom: str | None = None
    data_type: str | None = None
    monthly_values: tuple[MetricValue, ...] = ()


class PropertyMetrics(EspmModel):
    property_id: int
    year: int
    month: int
    measurement_system: str | None = None
    metrics: tuple[PropertyMetric, ...] = ()


class ReportingMetric(EspmModel):
    id: int
    name: str
    description: str | None = None
    data_type: str | None = None
    uom: str | None = None
    available_to_custom_metrics: bool | None = None
    group_id: int | None = None
    group_name: str | None = None


class ScoreReason(EspmModel):
    code: str | None = None
    message: str
    raw: dict[str, Any] = Field(default_factory=dict)


class PendingConnection(EspmModel):
    account_id: int
    username: str | None = None


class PendingPropertyShare(EspmModel):
    property_id: int
    account_id: int | None = None
    username: str | None = None


class PendingMeterShare(EspmModel):
    meter_id: int
    account_id: int | None = None
    username: str | None = None


class Notification(EspmModel):
    type: str | None = None
    message: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
