# espm-python

A typed, asynchronous, read-only Python SDK for the ENERGY STAR Portfolio
Manager (ESPM) XML web services API.

The general transport rejects every HTTP method except `GET`. Three narrowly
allowlisted connection/share response operations can be enabled explicitly
with `EspmConfig(allow_mutations=True)`. The SDK does not contain validation,
compliance, snapshot, export, or other business logic.

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
- Property identifiers and verification records
- Buildings within properties
- Aggregate and individual meter details
- Paginated waste records
- Pending connection/property/meter shares and notifications
- Opt-in acceptance or rejection of pending connections and shares

Use `EspmEnvironment.TEST` for `https://portfoliomanager.energystar.gov/wstest`
and `EspmEnvironment.LIVE` for `https://portfoliomanager.energystar.gov/ws`.
