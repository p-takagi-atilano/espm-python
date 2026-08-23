from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from espm import (
    EspmApiError,
    EspmAuthenticationError,
    EspmAuthorizationError,
    EspmClient,
    EspmConfig,
    EspmNotFoundError,
    EspmReadOnlyError,
    SharingAction,
)

BASE = "https://example.test/ws"


def client() -> EspmClient:
    return EspmClient(EspmConfig(username="user", password="secret", base_url=BASE))


@respx.mock
async def test_account_and_property_queries() -> None:
    respx.get(f"{BASE}/account").mock(
        return_value=httpx.Response(
            200,
            content=b"""
      <account><id>42</id><username>tester</username><accountInfo>
      <organization>Example Org</organization></accountInfo></account>""",
        )
    )
    respx.get(f"{BASE}/account/42/property/list").mock(
        return_value=httpx.Response(
            200,
            content=b"""
      <response><links><link link="/property/100" hint="Alpha" httpMethod="GET" />
      </links></response>""",
        )
    )
    respx.get(f"{BASE}/property/100").mock(
        return_value=httpx.Response(
            200,
            content=b"""
      <property><name>Alpha</name><primaryFunction>Office</primaryFunction>
      <address address1="1 Main" city="Seattle" state="WA" postalCode="98101" country="US" />
      <yearBuilt>1999</yearBuilt><grossFloorArea units="Square Feet" temporary="false">
      <value>12500.5</value></grossFloorArea><occupancyPercentage>90</occupancyPercentage>
      <isFederalProperty>false</isFederalProperty><accessLevel>Read</accessLevel></property>""",
        )
    )

    async with client() as espm:
        account = await espm.get_account()
        links = await espm.list_properties(account.id)
        prop = await espm.get_property(links[0].id or 0)

    assert account.id == 42
    assert links[0].hint == "Alpha"
    assert prop.gross_floor_area is not None
    assert prop.gross_floor_area.value == Decimal("12500.5")
    assert prop.address is not None and prop.address.postal_code == "98101"


@respx.mock
async def test_property_use_is_polymorphic() -> None:
    respx.get(f"{BASE}/propertyUse/77").mock(
        return_value=httpx.Response(
            200,
            content=b"""
      <office><name>Main Office</name><useDetails>
      <weeklyOperatingHours id="8" currentAsOf="2025-01-01" default="false">
      <value>55</value></weeklyOperatingHours>
      <percentOfficeCooled currentAsOf="2025-01-01"><value>50% or more</value></percentOfficeCooled>
      </useDetails></office>""",
        )
    )
    async with client() as espm:
        use = await espm.get_property_use(77)
    assert use.type == "office"
    assert use.use_details[0].value == Decimal("55")
    assert use.use_details[1].value == "50% or more"


@respx.mock
async def test_meter_association_and_consumption() -> None:
    respx.get(f"{BASE}/association/property/100/meter").mock(
        return_value=httpx.Response(
            200,
            content=b"""
      <meterPropertyAssociationList><energyMeterAssociation><meters><meterId>9</meterId>
      <meterId>10</meterId></meters><propertyRepresentation>
      <propertyRepresentationType>Whole Property</propertyRepresentationType>
      </propertyRepresentation></energyMeterAssociation></meterPropertyAssociationList>""",
        )
    )
    route = respx.get(f"{BASE}/meter/9/consumptionData")
    route.side_effect = [
        httpx.Response(
            200,
            content=(
                b"<meterData>"
                + b"".join(
                    f'<meterConsumption estimatedValue="false"><id>{i}</id><usage>1.25</usage>'
                    f"<startDate>2025-01-01</startDate><endDate>2025-01-31</endDate>"
                    f"</meterConsumption>".encode()
                    for i in range(120)
                )
                + b"</meterData>"
            ),
        ),
        httpx.Response(
            200,
            content=b"""
          <meterData><meterConsumption estimatedValue="true"><id>121</id><usage>2.5</usage>
          <startDate>2025-02-01</startDate><endDate>2025-02-28</endDate>
          </meterConsumption></meterData>""",
        ),
    ]
    async with client() as espm:
        association = await espm.get_property_meter_association(100)
        records = await espm.get_meter_consumption(
            9, start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
        )
    assert association.energy is not None
    assert association.energy.meter_ids == (9, 10)
    assert len(records) == 121
    assert records[-1].estimated_value is True
    assert route.call_count == 2


@respx.mock
async def test_metrics_batch_at_ten_and_parse_nil() -> None:
    route = respx.get(f"{BASE}/property/100/metrics")
    route.side_effect = [
        httpx.Response(
            200,
            content=b"""
          <propertyMetrics propertyId="100" year="2025" month="12" measurementSystem="EPA">
          <metric name="m0" dataType="numeric"><value>1.2</value></metric></propertyMetrics>""",
        ),
        httpx.Response(
            200,
            content=b"""
          <propertyMetrics propertyId="100" year="2025" month="12" measurementSystem="EPA"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <metric name="m10" dataType="numeric"><value xsi:nil="true" /></metric>
          </propertyMetrics>""",
        ),
    ]
    async with client() as espm:
        result = await espm.get_property_metrics(
            100, year=2025, month=12, metrics=[f"m{i}" for i in range(11)]
        )
    assert route.call_count == 2
    assert result.metrics[0].value == Decimal("1.2")
    assert result.metrics[1].value is None


async def test_transport_rejects_non_get() -> None:
    async with client() as espm:
        with pytest.raises(EspmReadOnlyError):
            await espm._request("POST", "/property")


@respx.mock
async def test_documented_empty_404_becomes_empty_collection() -> None:
    respx.get(f"{BASE}/account/42/property/list").mock(
        return_value=httpx.Response(404, content=b"<response><errors /></response>")
    )
    async with client() as espm:
        assert await espm.list_properties(42) == ()


@respx.mock
async def test_api_error_parses_attribute_description() -> None:
    respx.get(f"{BASE}/property/100/metrics").mock(
        return_value=httpx.Response(
            400,
            content=b"""
            <response status="Error"><errors><error errorNumber="-200"
            errorDescription="not a valid metric." /></errors></response>
            """,
        )
    )
    async with client() as espm:
        with pytest.raises(EspmApiError, match="not a valid metric"):
            await espm.get_property_metrics(100, year=2025, month=12, metrics=["invalid"])


@respx.mock
async def test_meter_query_parses_dates_flags_and_audit() -> None:
    respx.get(f"{BASE}/meter/9").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <meter><type>Natural Gas</type><name>Boiler Gas</name>
            <unitOfMeasure>therms</unitOfMeasure><metered>true</metered>
            <firstBillDate>2024-01-01</firstBillDate><inUse>false</inUse>
            <inactiveDate>2025-06-30</inactiveDate><aggregateMeter>false</aggregateMeter>
            <accessLevel>Read</accessLevel><audit><createdBy>owner</createdBy>
            <createdDate>2024-01-02T03:04:05Z</createdDate></audit></meter>
            """,
        )
    )
    async with client() as espm:
        meter = await espm.get_meter(9)

    assert meter.name == "Boiler Gas"
    assert meter.first_bill_date == date(2024, 1, 1)
    assert meter.in_use is False
    assert meter.inactive_date == date(2025, 6, 30)
    assert meter.audit is not None
    assert meter.audit.created_by == "owner"


@respx.mock
async def test_pending_share_queries_parse_resource_ids() -> None:
    respx.get(f"{BASE}/connect/account/pending/list").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <pendingList><account><accountId>20</accountId><username>customer</username>
            </account></pendingList>
            """,
        )
    )
    respx.get(f"{BASE}/share/property/pending/list").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <pendingList><property><propertyId>100</propertyId><accountId>20</accountId>
            <username>customer</username></property></pendingList>
            """,
        )
    )
    respx.get(f"{BASE}/share/meter/pending/list").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <pendingList><meter><meterId>9</meterId><accountId>20</accountId>
            <username>customer</username></meter></pendingList>
            """,
        )
    )

    async with client() as espm:
        connections = await espm.list_pending_connections()
        properties = await espm.list_pending_property_shares()
        meters = await espm.list_pending_meter_shares()

    assert connections[0].account_id == 20
    assert properties[0].property_id == 100
    assert meters[0].meter_id == 9


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, EspmAuthenticationError),
        (403, EspmAuthorizationError),
        (404, EspmNotFoundError),
    ],
)
@respx.mock
async def test_http_errors_are_normalized(status_code: int, error_type: type[EspmApiError]) -> None:
    respx.get(f"{BASE}/property/100").mock(
        return_value=httpx.Response(
            status_code,
            content=b'<response status="Error"><errors><error errorNumber="-1" '
            b'errorDescription="denied" /></errors></response>',
        )
    )
    async with client() as espm:
        with pytest.raises(error_type, match="denied"):
            await espm.get_property(100)


@respx.mock
async def test_notification_query_never_clears_remote_state() -> None:
    route = respx.get(f"{BASE}/notification/list").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <notificationList><notification type="Unshare">
            <message>Property access removed</message></notification></notificationList>
            """,
        )
    )
    async with client() as espm:
        notifications = await espm.list_notifications()

    assert route.calls[0].request.url.params["clear"] == "false"
    assert notifications[0].message == "Property access removed"


async def test_share_mutations_require_explicit_opt_in() -> None:
    async with client() as espm:
        with pytest.raises(EspmReadOnlyError, match="allow_mutations=True"):
            await espm.respond_to_connection(20, SharingAction.ACCEPT)


@respx.mock
@pytest.mark.parametrize(
    ("path", "operation"),
    [
        ("/connect/account/20", "connection"),
        ("/share/property/100", "property"),
        ("/share/meter/9", "meter"),
    ],
)
async def test_allowlisted_share_mutations_send_expected_xml(path: str, operation: str) -> None:
    route = respx.post(f"{BASE}{path}").mock(
        return_value=httpx.Response(200, content=b'<response status="Ok" />')
    )
    config = EspmConfig(
        username="user",
        password="secret",
        base_url=BASE,
        allow_mutations=True,
    )
    async with EspmClient(config) as espm:
        if operation == "connection":
            await espm.respond_to_connection(20, SharingAction.ACCEPT, note="Approved")
        elif operation == "property":
            await espm.respond_to_property_share(100, SharingAction.ACCEPT, note="Approved")
        else:
            await espm.respond_to_meter_share(9, SharingAction.ACCEPT, note="Approved")

    request = route.calls[0].request
    assert request.headers["Content-Type"] == "application/xml"
    assert b"<action>Accept</action>" in request.content
    assert b"<note>Approved</note>" in request.content


@respx.mock
async def test_share_rejection_escapes_note_xml() -> None:
    route = respx.post(f"{BASE}/share/property/100").mock(
        return_value=httpx.Response(200, content=b'<response status="Ok" />')
    )
    config = EspmConfig(username="user", password="secret", base_url=BASE, allow_mutations=True)
    async with EspmClient(config) as espm:
        await espm.respond_to_property_share(
            100, SharingAction.REJECT, note="Wrong owner & account"
        )

    assert b"<action>Reject</action>" in route.calls[0].request.content
    assert b"Wrong owner &amp; account" in route.calls[0].request.content
