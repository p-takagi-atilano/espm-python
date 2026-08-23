from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from urllib.parse import urlparse

from lxml import etree

from espm.models import (
    Account,
    AdditionalIdentifier,
    AdditionalIdentifierType,
    Address,
    AggregateMeterInfo,
    Audit,
    Building,
    ConsumptionRecord,
    Customer,
    DemandTracking,
    GrossFloorArea,
    Hierarchy,
    IndividualMeter,
    Meter,
    MeterAssociationGroup,
    MetricValue,
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
    UseDetail,
    UseDetailRevision,
    Verification,
    WasteDestination,
    WasteRecord,
)

XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"


def build_sharing_response(action: str, note: str | None = None) -> bytes:
    root = etree.Element("sharingResponse")
    etree.SubElement(root, "action").text = action
    if note is not None:
        etree.SubElement(root, "note").text = note
    return cast(bytes, etree.tostring(root, xml_declaration=True, encoding="UTF-8"))


def parse_xml(content: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    return etree.fromstring(content, parser=parser)


def local_name(element: etree._Element) -> str:
    return cast(str, etree.QName(element).localname)


def child(element: etree._Element | None, name: str) -> etree._Element | None:
    if element is None:
        return None
    return next((item for item in element if local_name(item) == name), None)


def children(element: etree._Element | None, name: str) -> list[etree._Element]:
    if element is None:
        return []
    return [item for item in element if local_name(item) == name]


def text(element: etree._Element | None, name: str | None = None) -> str | None:
    target = child(element, name) if name is not None else element
    if target is None or target.get(XSI_NIL, "false").lower() == "true":
        return None
    value = target.text
    return value.strip() if value and value.strip() else None


def integer(value: str | None) -> int | None:
    return int(value) if value not in (None, "") else None


def decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def as_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def scalar(element: etree._Element | None) -> Any:
    value = text(element)
    if value is None:
        return None
    bool_value = boolean(value)
    if bool_value is not None:
        return bool_value
    number = decimal(value)
    return number if number is not None else value


def raw_element(element: etree._Element) -> dict[str, Any]:
    result: dict[str, Any] = {
        f"@{local_name_from_tag(key)}": value for key, value in element.attrib.items()
    }
    grouped: dict[str, list[Any]] = {}
    for item in element:
        grouped.setdefault(local_name(item), []).append(raw_element(item))
    for name, values in grouped.items():
        result[name] = values[0] if len(values) == 1 else values
    if not len(element):
        value = text(element)
        if result:
            if value is not None:
                result["#text"] = value
        elif value is not None:
            return {"#text": value}
    return result


def local_name_from_tag(tag: str) -> str:
    return etree.QName(tag).localname if tag.startswith("{") else tag


def parse_address(element: etree._Element | None) -> Address | None:
    if element is None:
        return None
    return Address(
        address1=element.get("address1") or text(element, "address1"),
        address2=element.get("address2") or text(element, "address2"),
        city=element.get("city") or text(element, "city"),
        state=element.get("state") or text(element, "state"),
        postal_code=element.get("postalCode") or text(element, "postalCode"),
        country=element.get("country") or text(element, "country"),
    )


def parse_audit(element: etree._Element | None) -> Audit | None:
    if element is None:
        return None
    return Audit(
        created_by=text(element, "createdBy"),
        created_date=as_datetime(text(element, "createdDate")),
        last_updated_by=text(element, "lastUpdatedBy"),
        last_updated_date=as_datetime(text(element, "lastUpdatedDate")),
    )


def parse_account(root: etree._Element, *, customer_id: int | None = None) -> Account:
    account_info = child(root, "accountInfo")
    account_address = child(account_info, "address")
    if account_address is None:
        account_address = child(root, "address")
    model = Customer if customer_id is not None else Account
    return model(
        id=customer_id or integer(text(root, "id")) or 0,
        username=text(root, "username"),
        first_name=text(root, "firstName"),
        last_name=text(root, "lastName"),
        email=text(root, "email"),
        organization=text(account_info, "organization"),
        job_title=text(account_info, "jobTitle"),
        phone=text(account_info, "phone"),
        address=parse_address(account_address),
        raw=raw_element(root),
    )


def link_id(href: str) -> int | None:
    pieces = [piece for piece in urlparse(href).path.split("/") if piece]
    for piece in reversed(pieces):
        if piece.isdigit():
            return int(piece)
    return None


def parse_links(root: etree._Element) -> tuple[ResourceLink, ...]:
    found = root.xpath(".//*[local-name()='link']")
    return tuple(
        ResourceLink(
            id=link_id(item.get("link", "")),
            href=item.get("link", ""),
            hint=item.get("hint"),
            http_method=item.get("httpMethod"),
            description=item.get("linkDescription"),
        )
        for item in found
        if item.get("link")
    )


def parse_property(root: etree._Element, property_id: int) -> Property:
    gfa = child(root, "grossFloorArea")
    return Property(
        id=property_id,
        name=text(root, "name"),
        primary_function=text(root, "primaryFunction"),
        address=parse_address(child(root, "address")),
        year_built=integer(text(root, "yearBuilt")),
        construction_status=text(root, "constructionStatus"),
        number_of_buildings=integer(text(root, "numberOfBuildings")),
        gross_floor_area=GrossFloorArea(
            value=decimal(text(gfa, "value")),
            units=gfa.get("units") if gfa is not None else None,
            temporary=boolean(gfa.get("temporary")) if gfa is not None else None,
            default=boolean(gfa.get("default")) if gfa is not None else None,
        )
        if gfa is not None
        else None,
        occupancy_percentage=integer(text(root, "occupancyPercentage")),
        is_federal_property=boolean(text(root, "isFederalProperty")),
        notes=text(root, "notes"),
        access_level=text(root, "accessLevel"),
        audit=parse_audit(child(root, "audit")),
        raw=raw_element(root),
    )


def parse_building(root: etree._Element, building_id: int) -> Building:
    return Building.model_validate(parse_property(root, building_id).model_dump())


def parse_hierarchy(root: etree._Element) -> Hierarchy:
    return Hierarchy(
        account_id=integer(text(root, "accountId")),
        property_id=integer(text(root, "propertyId")),
        property_use_id=integer(text(root, "propertyUseId")),
        meter_id=integer(text(root, "meterId")),
        consumption_data_id=integer(text(root, "consumptionDataId")),
    )


def parse_use_detail(element: etree._Element) -> UseDetail:
    return UseDetail(
        name=local_name(element),
        value=scalar(child(element, "value")),
        id=integer(element.get("id")),
        units=element.get("units"),
        current_as_of=as_date(element.get("currentAsOf")),
        temporary=boolean(element.get("temporary")),
        default=boolean(element.get("default")),
        raw=raw_element(element),
    )


def parse_property_use(root: etree._Element, property_use_id: int) -> PropertyUse:
    details = child(root, "useDetails")
    detail_elements = details if details is not None else ()
    return PropertyUse(
        id=property_use_id,
        type=local_name(root),
        name=text(root, "name"),
        use_details=tuple(parse_use_detail(item) for item in detail_elements),
        audit=parse_audit(child(root, "audit")),
        raw=raw_element(root),
    )


def parse_use_detail_revisions(root: etree._Element) -> tuple[UseDetailRevision, ...]:
    revisions = root.xpath(".//*[local-name()='revision']")
    return tuple(
        UseDetailRevision(
            current_as_of=as_date(item.get("currentAsOf") or text(item, "currentAsOf")),
            details=tuple(
                parse_use_detail(detail) for detail in item if local_name(detail) != "currentAsOf"
            ),
            raw=raw_element(item),
        )
        for item in revisions
    )


def parse_additional_identifiers(root: etree._Element) -> tuple[AdditionalIdentifier, ...]:
    result: list[AdditionalIdentifier] = []
    items = [root] if local_name(root) == "additionalIdentifier" else []
    items.extend(root.xpath(".//*[local-name()='additionalIdentifier']"))
    for item in items:
        type_element = child(item, "additionalIdentifierType")
        identifier_type = None
        if type_element is not None:
            identifier_type = AdditionalIdentifierType(
                id=integer(type_element.get("id")),
                name=type_element.get("name") or text(type_element, "name") or text(type_element),
                description=type_element.get("description") or text(type_element, "description"),
                group=type_element.get("group") or text(type_element, "group"),
                standard_approved=boolean(type_element.get("standardApproved")),
            )
        result.append(
            AdditionalIdentifier(
                id=integer(item.get("id")),
                identifier_type=identifier_type,
                description=text(item, "description"),
                value=text(item, "value"),
                raw=raw_element(item),
            )
        )
    return tuple(result)


def parse_verification(root: etree._Element) -> Verification:
    designation_list = child(root, "professionalDesignationList")
    designations = (
        tuple(raw_element(item) for item in designation_list)
        if designation_list is not None
        else ()
    )
    return Verification(
        period_ending_date=text(root, "periodEndingDate"),
        verification_date=as_date(text(root, "verificationDate")),
        name=text(root, "name"),
        title=text(root, "title"),
        organization=text(root, "organization"),
        phone=text(root, "phone"),
        email=text(root, "email"),
        postal_code=text(root, "postalCode"),
        professional_designations=designations,
        audit=parse_audit(child(root, "audit")),
        raw=raw_element(root),
    )


def parse_meter(root: etree._Element, meter_id: int) -> Meter:
    return Meter(
        id=meter_id,
        type=text(root, "type"),
        name=text(root, "name"),
        unit_of_measure=text(root, "unitOfMeasure"),
        metered=boolean(text(root, "metered")),
        first_bill_date=as_date(text(root, "firstBillDate")),
        in_use=boolean(text(root, "inUse")),
        inactive_date=as_date(text(root, "inactiveDate")),
        aggregate_meter=boolean(text(root, "aggregateMeter")),
        other_description=text(root, "otherDescription"),
        access_level=text(root, "accessLevel"),
        audit=parse_audit(child(root, "audit")),
        raw=raw_element(root),
    )


def association_group(root: etree._Element, name: str) -> MeterAssociationGroup | None:
    group = child(root, name)
    if group is None:
        return None
    meter_ids = group.xpath(".//*[local-name()='meterId']/text()")
    representation = group.xpath("string(.//*[local-name()='propertyRepresentationType'][1])")
    return MeterAssociationGroup(
        meter_ids=tuple(int(value) for value in meter_ids),
        representation_type=representation or None,
    )


def parse_meter_association(root: etree._Element) -> PropertyMeterAssociation:
    return PropertyMeterAssociation(
        energy=association_group(root, "energyMeterAssociation"),
        water=association_group(root, "waterMeterAssociation"),
        waste=association_group(root, "wasteMeterAssociation"),
        raw=raw_element(root),
    )


def parse_consumption(root: etree._Element) -> tuple[ConsumptionRecord, ...]:
    records = root.xpath(".//*[local-name()='meterConsumption']")
    result: list[ConsumptionRecord] = []
    for item in records:
        demand = child(item, "demandTracking")
        result.append(
            ConsumptionRecord(
                id=integer(text(item, "id")),
                usage=decimal(text(item, "usage")),
                start_date=as_date(text(item, "startDate")),
                end_date=as_date(text(item, "endDate")),
                estimated_value=boolean(item.get("estimatedValue")),
                cost=decimal(text(item, "cost")),
                demand_tracking=DemandTracking(
                    demand=decimal(text(demand, "demand")),
                    demand_cost=decimal(text(demand, "demandCost")),
                )
                if demand is not None
                else None,
                raw=raw_element(item),
            )
        )
    return tuple(result)


def parse_waste_data(root: etree._Element) -> tuple[WasteRecord, ...]:
    records: list[WasteRecord] = []
    for item in root.xpath(".//*[local-name()='wasteData']"):
        destination = child(item, "disposalDestination")
        records.append(
            WasteRecord(
                id=integer(text(item, "id")),
                start_date=as_date(text(item, "startDate")),
                end_date=as_date(text(item, "endDate")),
                quantity=decimal(text(item, "quantity")),
                times_emptied=decimal(text(item, "timesEmptied")),
                average_percent_full=decimal(text(item, "averagePercentFull")),
                cost=decimal(text(item, "cost")),
                estimated_value=boolean(item.get("estimatedValue")),
                disposal_destination=WasteDestination(
                    landfill_percentage=decimal(text(destination, "landfillPercentage")),
                    incineration_percentage=decimal(text(destination, "incinerationPercentage")),
                    waste_to_energy_percentage=decimal(
                        text(destination, "wasteToEnergyPercentage")
                    ),
                    unknown_percentage=decimal(text(destination, "unknownDestPercentage")),
                )
                if destination is not None
                else None,
                audit=parse_audit(child(item, "audit")),
                raw=raw_element(item),
            )
        )
    return tuple(records)


def parse_aggregate_meter(root: etree._Element, meter_id: int) -> AggregateMeterInfo:
    value = text(root, "aggregateMeter")
    if value is None and local_name(root) == "aggregateMeter":
        value = text(root)
    return AggregateMeterInfo(
        meter_id=meter_id,
        is_aggregate=boolean(value),
        raw=raw_element(root),
    )


def parse_individual_meter(root: etree._Element) -> IndividualMeter:
    return IndividualMeter(
        id=integer(text(root, "id")),
        meter_id=integer(text(root, "meterId")),
        custom_id=text(root, "customId"),
        custom_id_name=text(root, "customIdName"),
        service_address=text(root, "serviceAddress"),
        in_use=boolean(text(root, "inUse")),
        inactive_date=as_date(text(root, "inactiveDate")),
        audit=parse_audit(child(root, "audit")),
        raw=raw_element(root),
    )


def metric_scalar(element: etree._Element | None) -> Decimal | str | None:
    value = text(element)
    if value is None:
        return None
    number = decimal(value)
    return number if number is not None else value


def parse_metrics(root: etree._Element, property_id: int, year: int, month: int) -> PropertyMetrics:
    metrics: list[PropertyMetric] = []
    for item in children(root, "metric"):
        monthly = tuple(
            MetricValue(
                value=metric_scalar(child(point, "value")),
                month=integer(point.get("month")),
                year=integer(point.get("year")),
            )
            for point in children(item, "monthlyMetric")
        )
        metrics.append(
            PropertyMetric(
                name=item.get("name", ""),
                value=metric_scalar(child(item, "value")),
                uom=item.get("uom"),
                data_type=item.get("dataType"),
                monthly_values=monthly,
            )
        )
    return PropertyMetrics(
        property_id=integer(root.get("propertyId")) or property_id,
        year=integer(root.get("year")) or year,
        month=integer(root.get("month")) or month,
        measurement_system=root.get("measurementSystem"),
        metrics=tuple(metrics),
    )


def parse_metrics_list(root: etree._Element) -> tuple[PropertyMetrics, ...]:
    return tuple(
        parse_metrics(
            item,
            integer(item.get("propertyId")) or 0,
            integer(item.get("year")) or 0,
            integer(item.get("month")) or 0,
        )
        for item in root.xpath(".//*[local-name()='propertyMetrics']")
    )


def parse_reporting_metrics(root: etree._Element) -> tuple[ReportingMetric, ...]:
    result: list[ReportingMetric] = []
    for group in root.xpath(".//*[local-name()='group']"):
        group_id = integer(group.get("id"))
        group_name = group.get("name")
        for item in group.xpath("./*[local-name()='metrics']/*[local-name()='metric']"):
            metric_id = integer(item.get("id"))
            metric_name = item.get("name")
            if metric_id is None or metric_name is None:
                continue
            result.append(
                ReportingMetric(
                    id=metric_id,
                    name=metric_name,
                    description=item.get("description"),
                    data_type=item.get("dataType"),
                    uom=item.get("uom"),
                    available_to_custom_metrics=boolean(item.get("availableToCustomMetrics")),
                    group_id=group_id,
                    group_name=group_name,
                )
            )
    return tuple(result)


def parse_score_reasons(root: etree._Element) -> tuple[ScoreReason, ...]:
    candidates = root.xpath(".//*[local-name()='alert' or local-name()='reason']")
    return tuple(
        ScoreReason(
            code=item.get("code") or text(item, "code"),
            message=text(item, "message") or text(item, "description") or text(item) or "",
            raw=raw_element(item),
        )
        for item in candidates
    )


def parse_pending_connections(root: etree._Element) -> tuple[PendingConnection, ...]:
    return tuple(
        PendingConnection(
            account_id=integer(text(item, "accountId")) or 0,
            username=text(item, "username"),
        )
        for item in root.xpath(".//*[local-name()='account']")
    )


def parse_pending_properties(root: etree._Element) -> tuple[PendingPropertyShare, ...]:
    return tuple(
        PendingPropertyShare(
            property_id=integer(text(item, "propertyId")) or 0,
            account_id=integer(text(item, "accountId")),
            username=text(item, "username"),
        )
        for item in root.xpath(".//*[local-name()='property']")
    )


def parse_pending_meters(root: etree._Element) -> tuple[PendingMeterShare, ...]:
    return tuple(
        PendingMeterShare(
            meter_id=integer(text(item, "meterId")) or 0,
            account_id=integer(text(item, "accountId")),
            username=text(item, "username"),
        )
        for item in root.xpath(".//*[local-name()='meter']")
    )


def parse_notifications(root: etree._Element) -> tuple[Notification, ...]:
    return tuple(
        Notification(
            type=item.get("type") or text(item, "type"),
            message=text(item, "message") or text(item, "description"),
            raw=raw_element(item),
        )
        for item in root.xpath(".//*[local-name()='notification']")
    )


def next_link(root: etree._Element) -> str | None:
    for item in root.xpath(".//*[local-name()='link']"):
        description = (item.get("linkDescription") or "").lower()
        if "next" in description:
            return cast(str | None, item.get("link"))
    return None


def parse_api_errors(root: etree._Element) -> tuple[str, tuple[str, ...]]:
    errors = root.xpath(".//*[local-name()='error']")
    messages: list[str] = []
    codes: list[str] = []
    for item in errors:
        message = (
            item.get("errorDescription")
            or text(item, "errorDescription")
            or text(item, "message")
            or text(item)
        )
        code = item.get("errorNumber") or item.get("code") or text(item, "errorNumber")
        if message:
            messages.append(message)
        if code:
            codes.append(code)
    return "; ".join(messages), tuple(codes)
