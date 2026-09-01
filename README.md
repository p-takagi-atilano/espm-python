# espm-python

A typed, asynchronous, read-only Python SDK for the ENERGY STAR Portfolio
Manager (ESPM) XML web services API.

The general transport rejects every HTTP method except `GET`. Three narrowly
allowlisted connection/share response operations can be enabled explicitly
with `EspmConfig(allow_mutations=True)`. The SDK does not contain validation,
compliance, snapshot, export, or other business logic.

Every returned resource is a typed Pydantic model. Models retain unknown ESPM
fields in `raw` for forward compatibility. Use `model.to_dict()` for compact
JSON-compatible output or `model.to_dict(include_raw=True)` when unsupported
source fields are needed.

```python
import asyncio
from espm import EspmClient, EspmConfig, EspmEnvironment


async def main() -> None:
    config = EspmConfig(
        username="my-test-username",
        password="my-test-password",
        environment=EspmEnvironment.TEST,
    )
    async with EspmClient(config) as client:
        account = await client.get_account()
        properties = await client.list_properties(account.id)
        print(properties)


asyncio.run(main())
```

## Supported queries

- Account and connected customers
- Account properties, property details, hierarchy, and changed properties
- Property uses and use-detail revisions
- Meters, meter hierarchy, and property-meter associations
- Paginated meter consumption data
- Paginated property, property-use, use-detail, meter, and consumption change feeds
- Annual and monthly property metrics, including transparent batching of the
  ESPM limit of ten metrics per request
- Reporting metric discovery, use-detail metrics, and reasons for missing scores
- ESPM-calculated property data-quality flags, including estimated/default/temporary values,
  meter completeness alerts, meter coverage, checker status, and high/low Source EUI alerts
- Property identifiers and verification records
- Buildings within properties
- Aggregate and individual meter details
- Paginated waste records
- Pending connection/property/meter shares and notifications
- Opt-in acceptance or rejection of pending connections and shares
- Ordered, concurrency-bounded bulk queries for properties, property uses,
  meters, meter consumption, property metrics, and property data quality

Bulk methods return `BulkResult` objects containing the requested ESPM `id`
and typed `value`. Results preserve input order and perform no filtering or
interpretation:

```python
from datetime import date

meter_batches = await client.bulk_get_meter_consumption(
    [123, 456],
    start_date=date(2025, 1, 1),
    end_date=date(2025, 12, 31),
)

data_quality = await client.get_property_data_quality(123, year=2025)
portfolio_quality = await client.bulk_get_property_data_quality([123, 456], year=2025)
```

Use `EspmEnvironment.TEST` for `https://portfoliomanager.energystar.gov/wstest`
and `EspmEnvironment.LIVE` for `https://portfoliomanager.energystar.gov/ws`.

## Related projects

- Using Node.js? Check out [portfolio-manager](https://github.com/dopry/portfolio-manager), an
  unofficial Node.js SDK and CLI for the ENERGY STAR Portfolio Manager API.
