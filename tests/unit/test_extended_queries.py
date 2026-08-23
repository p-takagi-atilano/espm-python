from datetime import date
from decimal import Decimal

import httpx
import respx

from espm import EspmClient, EspmConfig

BASE = "https://example.test/ws"


def client() -> EspmClient:
    return EspmClient(EspmConfig(username="user", password="secret", base_url=BASE))


@respx.mock
async def test_change_feeds_use_documented_routes_and_dates() -> None:
    paths = [
        "/customer/42/propertyUse/whatChanged",
        "/customer/42/useDetails/whatChanged",
        "/customer/42/meter/whatChanged",
        "/property/100/meter/whatChanged",
        "/customer/42/meter/consumptionData/whatChanged",
    ]
    routes = [
        respx.get(f"{BASE}{path}").mock(
            return_value=httpx.Response(
                200,
                content=b'<response><links><link link="/propertyUse/7" /></links></response>',
            )
        )
        for path in paths
    ]
    since = date(2025, 1, 2)
    async with client() as espm:
        await espm.list_changed_property_uses(42, since)
        await espm.list_changed_use_details(42, since)
        await espm.list_changed_meters(42, since)
        await espm.list_changed_property_meters(100, since)
        await espm.list_changed_consumption_meters(42, since)

    assert all(route.calls[0].request.url.params["date"] == "2025-01-02" for route in routes)


@respx.mock
async def test_change_feed_follows_next_page_link() -> None:
    route = respx.get(f"{BASE}/customer/42/property/whatChanged")
    route.side_effect = [
        httpx.Response(
            200,
            content=b"""
            <response><links><link id="100" link="/property/100" />
            <link linkDescription="Next page" link="/customer/42/property/whatChanged?page=2" />
            </links></response>""",
        ),
        httpx.Response(
            200,
            content=b"""
            <response><links><link id="101" link="/property/101" /></links></response>""",
        ),
    ]
    async with client() as espm:
        changed = await espm.list_changed_properties(42, date(2025, 1, 1))

    assert [item.id for item in changed] == [100, 101]
    assert route.calls[1].request.url.params["page"] == "2"


@respx.mock
async def test_hierarchy_and_direct_use_detail_queries() -> None:
    hierarchy_xml = b"""
      <hierarchy><accountId>42</accountId><propertyId>100</propertyId>
      <propertyUseId>7</propertyUseId><meterId>9</meterId></hierarchy>"""
    respx.get(f"{BASE}/idHierarchy/propertyUse/7").mock(
        return_value=httpx.Response(200, content=hierarchy_xml)
    )
    respx.get(f"{BASE}/idHierarchy/useDetails/8").mock(
        return_value=httpx.Response(200, content=hierarchy_xml)
    )
    respx.get(f"{BASE}/idHierarchy/consumptionData/11").mock(
        return_value=httpx.Response(200, content=hierarchy_xml)
    )
    respx.get(f"{BASE}/useDetails/8").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <weeklyOperatingHours id="8" currentAsOf="2025-01-01" units="Hours">
            <value>55</value></weeklyOperatingHours>""",
        )
    )
    async with client() as espm:
        use_hierarchy = await espm.get_property_use_hierarchy(7)
        detail_hierarchy = await espm.get_use_detail_hierarchy(8)
        consumption_hierarchy = await espm.get_consumption_hierarchy(11)
        detail = await espm.get_use_detail(8)

    assert use_hierarchy.property_id == 100
    assert detail_hierarchy.property_use_id == 7
    assert consumption_hierarchy.meter_id == 9
    assert detail.id == 8 and detail.value == Decimal("55")


@respx.mock
async def test_property_identifiers_and_verification() -> None:
    respx.get(f"{BASE}/property/100/identifier/list").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <additionalIdentifiers><additionalIdentifier id="3">
            <additionalIdentifierType id="2" name="Seattle Building ID"
            standardApproved="true" /><value>BLDG-123</value>
            </additionalIdentifier></additionalIdentifiers>""",
        )
    )
    respx.get(f"{BASE}/property/100/identifier/3").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <additionalIdentifier id="3"><additionalIdentifierType id="2"
            name="Seattle Building ID"/><value>BLDG-123</value></additionalIdentifier>""",
        )
    )
    respx.get(f"{BASE}/property/100/verification").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <verification><periodEndingDate>2025-12</periodEndingDate>
            <verificationDate>2026-03-01</verificationDate><name>Verifier</name>
            <organization>Engineering Co</organization><email>v@example.com</email>
            </verification>""",
        )
    )
    async with client() as espm:
        identifiers = await espm.list_property_identifiers(100)
        identifier = await espm.get_property_identifier(100, 3)
        verification = await espm.get_property_verification(100)

    assert identifiers[0].identifier_type is not None
    assert identifiers[0].identifier_type.standard_approved is True
    assert identifier.value == "BLDG-123"
    assert verification is not None
    assert verification.verification_date == date(2026, 3, 1)


@respx.mock
async def test_building_queries() -> None:
    respx.get(f"{BASE}/property/100/building/list").mock(
        return_value=httpx.Response(
            200,
            content=b'<response><links><link id="101" link="/building/101" /></links></response>',
        )
    )
    respx.get(f"{BASE}/building/101").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <building><name>North Wing</name><primaryFunction>Office</primaryFunction>
            <yearBuilt>2001</yearBuilt></building>""",
        )
    )
    respx.get(f"{BASE}/building/101/property/list").mock(
        return_value=httpx.Response(
            200,
            content=b'<response><links><link id="100" link="/property/100" /></links></response>',
        )
    )
    async with client() as espm:
        buildings = await espm.list_buildings(100)
        building = await espm.get_building(101)
        parents = await espm.list_building_properties(101)

    assert buildings[0].id == 101
    assert building.name == "North Wing"
    assert parents[0].id == 100


@respx.mock
async def test_aggregate_individual_and_paginated_waste_queries() -> None:
    respx.get(f"{BASE}/meter/9/aggregateMeter").mock(
        return_value=httpx.Response(
            200, content=b"<meter><aggregateMeter>true</aggregateMeter></meter>"
        )
    )
    respx.get(f"{BASE}/meter/9/individual/list").mock(
        return_value=httpx.Response(
            200,
            content=(
                b'<response><links><link id="4" link="/meter/individual/4" /></links></response>'
            ),
        )
    )
    respx.get(f"{BASE}/meter/individual/4").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <individualMeter><id>4</id><meterId>9</meterId><customId>A-1</customId>
            <inUse>true</inUse></individualMeter>""",
        )
    )
    waste_route = respx.get(f"{BASE}/meter/9/wasteData")
    waste_route.side_effect = [
        httpx.Response(
            200,
            content=(
                b"<wasteDataList>"
                + b"".join(
                    f"<wasteData><id>{index}</id><startDate>2025-01-01</startDate>"
                    f"<quantity>2.5</quantity></wasteData>".encode()
                    for index in range(120)
                )
                + b"</wasteDataList>"
            ),
        ),
        httpx.Response(
            200,
            content=b"""
            <wasteDataList><wasteData estimatedValue="true"><id>121</id>
            <startDate>2025-02-01</startDate><quantity>3.5</quantity>
            <disposalDestination><landfillPercentage>60</landfillPercentage>
            <wasteToEnergyPercentage>40</wasteToEnergyPercentage></disposalDestination>
            </wasteData></wasteDataList>""",
        ),
    ]
    async with client() as espm:
        aggregate = await espm.get_aggregate_meter(9)
        individuals = await espm.list_individual_meters(9)
        individual = await espm.get_individual_meter(4)
        waste = await espm.get_meter_waste_data(9)

    assert aggregate.is_aggregate is True
    assert individuals[0].id == 4
    assert individual.custom_id == "A-1"
    assert len(waste) == 121
    assert waste[-1].disposal_destination is not None
    assert waste[-1].disposal_destination.landfill_percentage == Decimal("60")


@respx.mock
async def test_reporting_metric_discovery_and_additional_metric_queries() -> None:
    reporting_route = respx.get(f"{BASE}/reports/metrics").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <reportMetrics><group id="1" name="Energy"><metrics>
            <metric id="10" name="score" description="ENERGY STAR score"
            dataType="numeric" availableToCustomMetrics="true" />
            </metrics></group></reportMetrics>""",
        )
    )
    respx.get(f"{BASE}/property/100/reasonsForNoWaterScore").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <alerts><alert><name>Insufficient Data</name>
            <description>Water data is incomplete.</description></alert></alerts>""",
        )
    )
    respx.get(f"{BASE}/property/100/useDetails/metrics").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <propertyMetrics propertyId="100" year="2025" month="12">
            <metric name="weeklyOperatingHours" uom="Hours"><value>55</value></metric>
            </propertyMetrics>""",
        )
    )
    async with client() as espm:
        reporting = await espm.list_reporting_metrics(
            group_ids=[1, 2], available_to_custom_metrics=True
        )
        reasons = await espm.get_reasons_for_no_water_score(100, year=2025, month=12)
        use_metrics = await espm.get_property_use_detail_metrics(100, year=2025, month=12)

    assert reporting_route.calls[0].request.url.params["groupIds"] == "1,2"
    assert reporting[0].name == "score"
    assert reporting[0].available_to_custom_metrics is True
    assert reasons[0].message == "Water data is incomplete."
    assert use_metrics.metrics[0].value == Decimal("55")
