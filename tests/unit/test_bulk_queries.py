from datetime import date

import httpx
import respx

from espm import DATA_QUALITY_METRICS, EspmClient, EspmConfig

BASE = "https://example.test/ws"


@respx.mock
async def test_property_data_quality_uses_documented_metrics_in_api_sized_batches() -> None:
    route = respx.get(f"{BASE}/property/100/metrics").mock(
        return_value=httpx.Response(
            200,
            content=b"""
            <propertyMetrics propertyId="100" year="2025" month="12">
              <metric name="estimatedValuesEnergy" dataType="string"><value>Yes</value></metric>
              <metric name="alertEnergyMeterGap" dataType="string"><value>Ok</value></metric>
            </propertyMetrics>""",
        )
    )

    async with client() as espm:
        result = await espm.get_property_data_quality(100, year=2025)

    assert len(route.calls) == 3
    requested = tuple(
        name.strip()
        for call in route.calls
        for name in call.request.headers["PM-Metrics"].split(",")
    )
    assert requested == DATA_QUALITY_METRICS
    assert all(len(call.request.headers["PM-Metrics"].split(",")) <= 10 for call in route.calls)
    assert dict(route.calls[0].request.url.params) == {
        "year": "2025",
        "month": "12",
        "measurementSystem": "EPA",
    }
    assert [metric.name for metric in result.metrics] == [
        "estimatedValuesEnergy",
        "alertEnergyMeterGap",
    ]


def client() -> EspmClient:
    return EspmClient(EspmConfig(username="user", password="secret", base_url=BASE))


@respx.mock
async def test_bulk_property_and_property_use_queries_preserve_ids_and_order() -> None:
    for property_id in (2, 1):
        respx.get(f"{BASE}/property/{property_id}").mock(
            return_value=httpx.Response(
                200,
                content=f"<property><name>Property {property_id}</name></property>".encode(),
            )
        )
        respx.get(f"{BASE}/property/{property_id}/propertyUse/list").mock(
            return_value=httpx.Response(
                200,
                content=(
                    f'<response><links><link id="{property_id + 10}" '
                    f'link="/propertyUse/{property_id + 10}" /></links></response>'
                ).encode(),
            )
        )
        respx.get(f"{BASE}/propertyUse/{property_id + 10}").mock(
            return_value=httpx.Response(
                200,
                content=(
                    f"<propertyUse><name>Use {property_id}</name><type>office</type></propertyUse>"
                ).encode(),
            )
        )

    async with client() as espm:
        properties = await espm.bulk_get_properties([2, 1])
        use_lists = await espm.bulk_list_property_uses([2, 1])
        uses = await espm.bulk_get_property_uses([12, 11])

    assert [item.id for item in properties] == [2, 1]
    assert [item.value.name for item in properties] == ["Property 2", "Property 1"]
    assert [item.value[0].id for item in use_lists] == [12, 11]
    assert [item.value.name for item in uses] == ["Use 2", "Use 1"]


@respx.mock
async def test_bulk_meter_consumption_and_metric_queries_forward_shared_options() -> None:
    for property_id in (1, 2):
        meter_id = property_id + 20
        meter_list = respx.get(f"{BASE}/property/{property_id}/meter/list").mock(
            return_value=httpx.Response(
                200,
                content=(
                    f'<response><links><link id="{meter_id}" link="/meter/{meter_id}" />'
                    f"</links></response>"
                ).encode(),
            )
        )
        respx.get(f"{BASE}/meter/{meter_id}").mock(
            return_value=httpx.Response(
                200,
                content=f"<meter><name>Meter {meter_id}</name></meter>".encode(),
            )
        )
        consumption = respx.get(f"{BASE}/meter/{meter_id}/consumptionData").mock(
            return_value=httpx.Response(
                200,
                content=(
                    f"<meterData><meterConsumption><id>{meter_id + 100}</id>"
                    f"<usage>10</usage><startDate>2025-01-01</startDate>"
                    f"<endDate>2025-01-31</endDate></meterConsumption></meterData>"
                ).encode(),
            )
        )
        metrics = respx.get(f"{BASE}/property/{property_id}/metrics").mock(
            return_value=httpx.Response(
                200,
                content=(
                    f'<propertyMetrics propertyId="{property_id}" year="2025" month="12">'
                    f'<metric name="score"><value>{80 + property_id}</value></metric>'
                    f"</propertyMetrics>"
                ).encode(),
            )
        )

    async with client() as espm:
        meter_lists = await espm.bulk_list_meters([1, 2], my_access_only=True)
        meters = await espm.bulk_get_meters([21, 22])
        records = await espm.bulk_get_meter_consumption(
            [21, 22],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        metric_results = await espm.bulk_get_property_metrics(
            [1, 2], year=2025, month=12, metrics=["score"]
        )

    assert [item.value[0].id for item in meter_lists] == [21, 22]
    assert [item.value.name for item in meters] == ["Meter 21", "Meter 22"]
    assert [item.value[0].id for item in records] == [121, 122]
    assert [item.id for item in metric_results] == [1, 2]
    assert all(call.request.url.params["myAccessOnly"] == "true" for call in meter_list.calls)
    assert consumption.calls[0].request.url.params["startDate"] == "2025-01-01"
    assert metrics.calls[0].request.headers["PM-Metrics"] == "score"
