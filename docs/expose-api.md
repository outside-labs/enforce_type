# Optional expose-api value adapter

The selected integration keeps both base packages independent. expose-api owns
the adapter and an explicit optional extra using published enforce-type 0.1.0.
Its existing JSON model contract remains the public resource contract.

| Concern | enforce-type public operation | Adapter responsibility in expose-api |
| --- | --- | --- |
| Primitive values, UUID, enum and literal | Compile once, then JSON `load` / `dump` | Reuse leaf plans inside the existing model traversal |
| Float numbers | JSON load accepts finite integers; native check/dump requires a float | Normalize native integer values through JSON load to preserve API output behavior |
| Dataclass admission | Supports additional native and computed-field cases | Keep the API's nonrecursive, ordinary-constructor annotation surface |
| Construction/defaults | Full-model load constructs and checks the result | Keep API construction and complete default/post-init validation; partial patches do not construct the root |
| Identity | An ordinary value | Keep readable identity types, immutable patch keys and URL normalization |
| Field projection | Dumps all declared fields | Keep read-only input refusal and recursive write-only output omission |
| Errors | Value-free issues with static expected labels | Keep API issue paths/codes/order and omit dynamic/unknown key names |
| Ownership | Synchronous reusable plans | Keep authorization, atomic transforms, storage revisions and event projection in expose-api |

A whole-model `load`/`dump` replacement would bypass visibility and constructor
admission policies. The adapter instead selects compiled scalar plans beneath
the API's existing container, union and dataclass traversal. It does not expose
additional annotations, coercion, field constraints, collection limits or async
rules. This preserves the API's existing depth and error aggregation behavior.
No claim of faster execution is made; the value is explicit reuse with tested
HTTP and persistence policies.

`examples/api_values.py` demonstrates the public leaf operations available in
the published release. The adapter must additionally prove complete model,
HTTP, protected-resource, checked-storage and installed-artifact acceptance.
Creating a protected principal view must retain the selected schema.

Assessment sources: [enforce-type 0.1.0](https://github.com/wispsy/enforce_type/tree/v0.1.0)
and [accepted expose-api model contract](https://github.com/wispsy/expose_api/blob/5d284e18bce7ae9f07ba64ac9297dad55a3fc5b1/src/expose_api/models.py).
Selection and follow-up acceptance are tracked by
[API-01](https://github.com/wispsy/enforce_type/issues/14) and
[VAL-01–04](https://github.com/wispsy/expose_api/issues/52).
