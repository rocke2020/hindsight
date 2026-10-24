# Hindsight OSS vs Enterprise

## Overview

Hindsight Enterprise is not limited to a hosted cloud service. Vectorize offers Enterprise capabilities on its shared cloud, in a dedicated deployment in its own cloud, in your cloud account, and on your own Kubernetes infrastructure, including air-gapped installations. Enterprise is a commercial offering; the deployment location is a separate choice. See the [deployment comparison](https://docs.hindsight.vectorize.io/enterprise/deployment/overview/).

The free, MIT-licensed OSS edition already contains the memory workflow: retain, recall, reflect, observations, mental models, knowledge pages, APIs, SDKs, and a control plane. The clearest additional commercial components are Memlake, an object-storage memory engine; advanced Memory Defense detectors; integrated enterprise identity; and privacy workflows under the General Data Protection Regulation (GDPR). Audit logging, ordinary webhooks, basic secret redaction and blocking, and tenant-isolation extensions are also present in this OSS checkout, even where commercial documentation lists similar features under Enterprise.

This comparison distinguishes a feature sold in an Enterprise package from a feature absent from open source. It is based on official documentation and source inspection, not on a running Enterprise installation or an independent performance benchmark.

## 1. Scope, terminology, and evidence

This compares current editions and delivery options, rather than historical releases such as v0.10 versus v1.0. A source snapshot, a published package version, and a commercial subscription are different identifiers.

| Item | Scope used here |
|---|---|
| Research date | 2026-10-19 |
| OSS checkout | `5331da2f4db369528bb122075341a7de9c3df6df`, commit dated 2026-10-16 |
| Package metadata | `hindsight-api-slim` declares `1.0.0`; HEAD is not itself tagged, so this report does not assert that every published `1.0.0` artifact contains every feature in this checkout |
| Enterprise evidence | Current public Vectorize documentation; no private source, contract, licensed container, or deployment inspected |
| Included | Memory capabilities, storage, security, identity, tenancy, privacy, observability, delivery, operating responsibility, and cost categories |
| Acceptance evidence | Source-backed OSS entries, linked official Enterprise descriptions, explicit deployment alternatives, documented disagreements, and valid local source links |

OSS means open-source software: the MIT-licensed code that you can operate yourself. Cloud means Vectorize's managed service. Enterprise means the commercial feature and support offering, available through several deployment options. BYOC means bring your own cloud: infrastructure in an account you own, operated by Vectorize through access you grant. On-premises means infrastructure you own and operate. An air-gapped deployment has no internet connectivity. An entitlement is a commercial permission that enables a feature in the commercial service. A memory bank is Hindsight's separate memory scope for a user, agent, or project.

Security terminology: SSO is single sign-on; OIDC and SAML are protocols for federating sign-in to an identity provider; MFA is multi-factor authentication; PII is personally identifiable information. MCP is the Model Context Protocol used to expose tools to agents. SIEM means security information and event management, the systems that collect and analyze security events.

In the tables, “present in OSS” means an implementation and/or explicit configuration exists in this inspected checkout. It does not mean that a specific running server has enabled it or passed an end-to-end test. “Commercial” means the official offering documents it as an additional capability; it does not prohibit implementing an alternative against OSS extension interfaces.

Source anchors: [package metadata](../../hindsight-api-slim/pyproject.toml), [MIT license](../../LICENSE), [official edition overview in this checkout](../../hindsight-docs/docs/cloud-enterprise/overview.md), and [extension registry](../../hindsight-extensions/README.md).

## 2. Enterprise deployment and delivery

Enterprise can run on your hardware. “Self-hosted” therefore describes both free OSS operated by you and a paid on-premises Enterprise installation, with different supplied software and support.

| Option | Location and isolation | Who operates it | Commercial relationship |
|---|---|---|---|
| OSS self-hosted | Your laptop, server, cloud account, or cluster; you design isolation | You | MIT software; you fund infrastructure and model usage |
| Standard Hindsight Cloud | Vectorize's shared, multi-tenant service | Vectorize | Usage-based managed service |
| Cloud with Enterprise features | The shared cloud with additional commercial capabilities enabled | Vectorize | Enterprise agreement; not a dedicated installation |
| Enterprise private cloud | Dedicated deployment in Vectorize's cloud account | Vectorize | Commercial dedicated service |
| Enterprise BYOC | Dedicated deployment in your AWS, GCP, or Azure account | Vectorize, using access you grant | Commercial software and operation in your account |
| Enterprise on-premises | Your Kubernetes infrastructure, including disconnected environments | Your team, with Vectorize's assistance | Commercial software supplied for customer operation |

The infrastructure/ownership distinctions above follow the [official deployment matrix](https://docs.hindsight.vectorize.io/enterprise/deployment/overview/); the [BYOC guide](https://docs.hindsight.vectorize.io/enterprise/deployment/byoc/) describes access and operation in your account.

For on-premises delivery, the documented application is installed with a Helm chart and container images. It includes the API, workers, console, identity service, PostgreSQL, model services, and optional Memlake. A disconnected installation needs mirrored images and locally reachable models and dependencies; purchasing Enterprise does not itself provide your cluster, GPUs, storage, DNS, or internal certificates. See [on-premises architecture and requirements](https://docs.hindsight.vectorize.io/enterprise/deployment/on-premises/).

BYOC and private cloud can use the cloud providers' private endpoint services. OSS can also run behind networking that you configure; Enterprise adds Vectorize's supported deployment and operating arrangement. Private networking is consequently not a restriction that forces OSS traffic over the public internet. See the network-access row in the [verified deployment comparison](https://docs.hindsight.vectorize.io/enterprise/deployment/overview/).

## 3. Feature comparison

The core memory product is available in OSS. Enterprise adds commercial storage, identity, security, privacy, and service components, while several supporting features overlap with OSS.

| Capability | OSS self-hosted, inspected snapshot | Enterprise offering | Practical distinction / evidence |
|---|---|---|---|
| Retain, recall, reflect | Present | Included | Same public operation model; [engine](../../hindsight-api-slim/hindsight_api/engine/memory_engine.py) |
| Semantic, keyword, graph, temporal retrieval | Present | Included; Memlake provides another implementation | Backend choice can change retrieval execution; [search](../../hindsight-api-slim/hindsight_api/engine/search/) |
| Observations and consolidation | Present | Included | Not inherently a paid reasoning tier; [architecture](../../CLAUDE.md) |
| Directives, mental models, knowledge pages | Present | Included | Core memory capabilities; [HTTP API](../../hindsight-api-slim/hindsight_api/api/http.py) |
| REST API, MCP, SDKs, CLI | Present | Included | Common client interfaces; deployment URLs and credentials differ |
| Control plane UI | Present | Included, with commercial administration surfaces | Having a console is not Enterprise-exclusive; [OSS UI](../../hindsight-control-plane/) |
| PostgreSQL memory storage | Present | Available for dedicated deployments | You operate the OSS database; commercial responsibility depends on deployment |
| Oracle backend | Public code and configuration | Available in supported deployment arrangements | Not evidence of a closed-source-only Oracle implementation; [configuration](../../hindsight-docs/docs/developer/configuration.mdx) |
| Memlake memory storage | Extension interface is public; Memlake implementation was not found in the inspected OSS memory-store implementation | Commercial backend; also used by much of Cloud | An extension contract does not supply its commercial implementation; see section 4 |
| Model/provider configuration | You configure and pay for providers or local models | Managed or deployment-specific model arrangement | No demonstrated universal quality advantage from the edition label alone |
| Shared API-key authentication | Present, optional configuration | Included with richer key management | [Built-in authentication](../../hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py) |
| Schema-per-user tenant isolation | Public static-key and Supabase extensions, separately packaged | Organization and key administration in the commercial product | OSS is not limited to one unauthenticated user; see section 5 |
| Teams and Owner/Admin/Member roles | Not supplied by the built-in shared-key login | Commercial console capability | Also advertised on ordinary Cloud plans; not unique to Enterprise |
| Bank-scoped, expiring, delegated child keys | Built-in shared-key extension does not provide the documented commercial management workflow | Commercial key-management capability | Also advertised on ordinary Cloud plans; custom OSS auth remains possible |
| Native OIDC/SAML sign-in | Not provided by the built-in shared-key console login | Integrated enterprise identity | An external OSS gateway is a separate integration |
| Organization-wide MFA enforcement | Not provided by the built-in shared-key console login | Commercial identity policy | With SSO, the identity provider owns MFA |
| Regex secret/PII redaction | Present; opt-in per bank | Included | Current OSS docs describe 45 patterns |
| Block writes matching basic secret patterns | Present in extension and retain pipeline | Included | The statement that all blocking is paid-only is too broad |
| Expanded patterns, Base64 decoding, LLM screening | Not supplied by the bundled regex detector | Advanced Memory Defense | Detector coverage, rather than basic redaction alone, is the commercial addition |
| Prompt-injection, size-anomaly, protected-tag detectors | Not supplied by the bundled regex detector | Advanced Memory Defense | Public interfaces allow other extensions, but do not implement these detectors |
| Bank activity audit log | Present; configurable, default off | Packaged and gated commercially in the service | Core audit implementation is not absent from OSS |
| Ordinary signed webhooks and retries | Present | Included; commercial security events add payloads and attribution | Compare event schemas rather than just the word “webhooks” |
| LLM traces, metrics, telemetry | Present | Operated and supported according to deployment | Observability infrastructure is not inherently Enterprise-only |
| Ordinary memory/document deletion and export | Public APIs exist | Included | These operations are not the full subject-rights workflow below |
| GDPR erasure/export/retention workflow and receipts | Not supplied as the documented integrated privacy product | Commercial Data Privacy capability | Includes subject tagging and privacy action history; see section 8 |
| Managed upgrades, backups, response commitments | You arrange these | Contract and deployment-dependent | Service responsibility, not a different retain/recall API |

Core API parity is described in the [official edition overview](https://hindsight.vectorize.io/cloud-enterprise/overview). Commercial team and key capabilities are documented separately in [Team Management](https://docs.hindsight.vectorize.io/enterprise/team-management/) and [API Keys](https://docs.hindsight.vectorize.io/enterprise/api-keys/). Their appearance in Enterprise documentation does not prove that ordinary Cloud excludes them; the [official Cloud feature article](../../hindsight-docs/blog/2026-09-03-hindsight-cloud-enterprise-features.md) explicitly places roles and scoped keys on all Cloud plans.

## 4. Memory engine, storage, and scale

Memlake is the most substantial documented architectural addition. It changes memory persistence and retrieval execution; it does not require a new public agent API.

In the OSS default path, the memory-store factory loads a configured extension or creates `PostgresMemories`. That public interface is the integration seam for another store, not a bundled Memlake server. The inspected implementation directory contains the database-backed implementation and its helpers. Source: [factory](../../hindsight-api-slim/hindsight_api/engine/memories/__init__.py), [contract](../../hindsight-api-slim/hindsight_api/engine/memories/base.py), and [default implementation](../../hindsight-api-slim/hindsight_api/engine/memories/postgres.py).

| Aspect | OSS database-backed path | Enterprise with Memlake |
|---|---|---|
| Durable memory location | Database-managed rows and indexes | Object storage |
| Retrieval process | SQL/database-backed search machinery | Rust query nodes and indexes |
| Index construction | Database indexes and application processing | Separate indexer workload |
| Compute state | Database topology determines durable/stateful components | Query-node memory and disk are caches |
| Scaling emphasis | Application workers plus database capacity and tuning | Query capacity and indexing scale independently of object-storage capacity |
| Organizational storage boundary | Database/schema arrangement you configure | Separate organization buckets described by the vendor |
| Control metadata | Database | Database still holds operational metadata |
| Public clients | REST, SDKs, MCP | Same interfaces; backend managed server-side |

The [Memlake overview](https://docs.hindsight.vectorize.io/enterprise/memlake/) documents the storage and deployment boundary. The [architecture](https://docs.hindsight.vectorize.io/enterprise/memlake/architecture/) describes immutable log/index objects, conditional object writes, query-node caching, and indexing independent of query serving. These are vendor-described properties, not independently verified guarantees in this report.

Memlake does not eliminate Hindsight's application database. Nor is every use of S3 in OSS a use of Memlake: OSS already supports object storage for uploaded source files, configured through `HINDSIGHT_API_FILE_STORAGE_TYPE`. Storing uploaded files in S3 does not move memory facts, their links, and search indexes to Memlake. Source: [file-storage configuration](../../hindsight-docs/docs/developer/configuration.mdx).

Performance comparisons need the memory count per bank, number of banks, model choice, concurrency, cache state, query budget, and hardware. The vendor publishes large-bank results, but this report does not turn them into a general OSS limit or promise equivalent production latency. See the published [performance methodology/results](https://docs.hindsight.vectorize.io/enterprise/memlake/performance/) and [tradeoffs](https://docs.hindsight.vectorize.io/enterprise/memlake/tradeoffs/).

## 5. Identity, access, and tenancy

OSS has authentication and tenant-extension mechanisms. Enterprise adds a supplied identity and administration product; the built-in OSS shared key is not equivalent to named users, federated login, or role-based administration.

| Area | OSS implementation inspected | Commercial product |
|---|---|---|
| Service API authentication | `ApiKeyTenantExtension` checks an environment-configured Bearer key and returns one configured schema | Named and scoped credentials, expiry, management, and delegation |
| Browser sign-in | `HINDSIGHT_CP_ACCESS_KEY` protects the console with a shared-key session | User accounts, teams, and enterprise identity integration |
| Multiple isolated users | Static-key extension maps configured identities to schemas; Supabase extension validates JWTs and uses per-user schemas | Supplied organization/user/key lifecycle |
| OIDC/SAML federation | External gateway or custom extension is an integration you own | Built-in setup and domain routing |
| MFA | External identity layer if you build/integrate one | Organization enforcement, or enforcement at the SSO identity provider |

Sources: [built-in tenant classes](../../hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py), [console middleware](../../hindsight-control-plane/src/middleware.ts), [console sessions](../../hindsight-control-plane/src/lib/auth/session.ts), [static-key tenant extension](../../hindsight-extensions/static-keys-tenant/README.md), and [Supabase tenant extension](../../hindsight-extensions/supabase-tenant/README.md).

The extra tenant extensions are public code but are not automatically installed with every server image. They require packaging and matching API/worker configuration. Using them does not automatically supply the commercial Team page, role model, or scoped-child-key management workflow.

Enterprise federation supports OIDC and SAML. Its documentation treats native MFA enforcement and SSO as alternatives for one organization: when SSO is active, MFA belongs to the identity provider. It would be misleading to promise that the two enforcement mechanisms simply stack. Source: [SSO and MFA behavior](https://docs.hindsight.vectorize.io/enterprise/sso/).

Session policy also differs: the inspected OSS shared-key implementation has a 24-hour token lifetime, whereas the commercial Cloud feature article describes a 30-minute inactivity timeout. These are different policies; “all plans” in a Cloud article should not be read as the behavior of the OSS session implementation.

## 6. Memory Defense

The basic protection boundary is detection coverage, not the existence of a block action. The current bundled OSS detector can either redact matching content or block the matching item.

| Capability | Current OSS bundled detector/UI | Enterprise documentation |
|---|---|---|
| Common secrets and PII | Regex patterns; OSS docs describe 45 | Included, plus a broader provider catalog |
| `redact` | Supported | Supported |
| `block` for a basic pattern match | Supported; retain pipeline honors the result | Supported, although some comparison text incorrectly presents all blocking as paid-only for this OSS snapshot |
| Per-bank policy | API and public console editor | Policy administration with commercial detector entitlements |
| Base64 expansion before screening | Not implemented by the bundled regex detector | Commercial redaction layer |
| LLM screening of conversational secrets | Not implemented by the bundled regex detector | Commercial redaction layer |
| Prompt-injection detector | Not implemented by the bundled regex detector | Commercial detector |
| Size-anomaly and protected-tag detectors | Not implemented by the bundled regex detector | Commercial detectors |
| Basic security notifications | `memory_defense.triggered`, plus operation audit entries if enabled | Richer security-event trail and commercial payloads |
| EU-specific PII detector pack | Not supplied by the bundled regex detector | Documented commercial privacy/security capability |

The default OSS extension is installed but inactive until the bank has an enabled policy and a relevant rule. It selects the `sensitive_data` rule, applies the regex scanner, and returns the configured action. The retain orchestrator handles `DefenseAction.BLOCK` by excluding that item; OSS documentation specifies a `422` response when every submitted item is blocked. The public console also supports choosing `allow`, `redact`, and `block`. Sources: [OSS guide](../../hindsight-docs/docs/developer/memory-defense/index.md), [regex implementation](../../hindsight-api-slim/hindsight_api/extensions/builtin/memory_defense_regex.py), [retain enforcement](../../hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py), and [console editor](../../hindsight-control-plane/src/components/memory-defense-section.tsx).

Enabling an OSS policy screens future retains. It does not scan existing memories retroactively. Basic pattern blocking also does not imply semantic prompt-injection detection: the bundled extension only runs its supported rule.

The commercial [redaction guide](https://docs.hindsight.vectorize.io/enterprise/security/redaction/) describes additional provider patterns, Base64 processing, and LLM screening. The [other-detectors guide](https://docs.hindsight.vectorize.io/enterprise/security/detectors/) covers injection and integrity controls. Those are documented additional implementations, rather than automatic capabilities acquired by setting an unsupported rule name in the OSS regex extension.

An OSS bank-policy fragment illustrating the distinction is:

```json
{
  "memory_defense": {
    "enabled": true,
    "rules": [
      { "on": "sensitive_data", "action": "block" }
    ]
  }
}
```

This is the bank configuration fragment, not a complete HTTP request body. The exact PATCH envelope must follow the bank configuration API. No live bank was changed for this report.

## 7. Audit logs, webhooks, and observability

OSS already contains these supporting systems. Commercial packaging can gate them in the hosted service, but that is different from their code being unavailable to a self-hosted operator.

| Area | OSS evidence | Commercial boundary |
|---|---|---|
| Bank activity audit | Public audit writer, schema, endpoints, and UI; deployment default is off | Commercial docs gate access in the service; this does not erase the OSS implementation |
| Per-bank audit override | `audit_log_enabled` can override the deployment default in either direction | Managed access policy is part of the commercial product |
| Webhook registration/delivery | Public models, manager, API, delivery tracking, and retries | Commercial security event types may have additional semantics |
| Delivery verification | HMAC signatures, IDs for deduplication, and a timestamped signature variant | Destination-specific integration still needs correct receiver configuration |
| Basic defense event | `memory_defense.triggered` | Commercial security docs use `memory_defense.violation` with richer attribution |
| LLM request traces | Public capture/query code and configuration; default enabled with one-day retention in this snapshot | Managed operation and service policy are separate questions |

Audit capture is configured through `HINDSIGHT_API_AUDIT_LOG_ENABLED` or a per-bank override. The default being false is an operating default, not evidence of a license requirement. The retained fields include operation, transport, timing, request/response, and metadata. This ordinary activity log should not be conflated with the separately documented Enterprise privacy ledger or specialized security-event product. Sources: [audit implementation](../../hindsight-api-slim/hindsight_api/engine/audit.py) and [audit/tracing configuration](../../hindsight-docs/docs/developer/configuration.mdx).

The OSS webhook guide documents durable delivery scheduling, retries, signed payloads, and delivery IDs. Basic Memory Defense notifications include the decision and matching pattern labels. That is sufficient to establish public webhook infrastructure; it does not establish schema parity with Enterprise security events, named-key attribution, or receipt fields. Sources: [webhook guide](../../hindsight-docs/docs/developer/api/webhooks.mdx), [delivery manager](../../hindsight-api-slim/hindsight_api/webhooks/manager.py), and [event models](../../hindsight-api-slim/hindsight_api/webhooks/models.py).

The Enterprise [audit guide](https://docs.hindsight.vectorize.io/enterprise/security/audit-logs/) and [security Webhook/SIEM guide](https://docs.hindsight.vectorize.io/enterprise/security/webhooks-siem/) describe the commercial surfaces. Their labels must be read in that product context. In particular, an OSS `memory_defense.triggered` consumer should not assume it can parse the documented Enterprise `memory_defense.violation` payload unchanged.

## 8. Privacy workflows

Enterprise privacy is a workflow product, not merely access to a delete endpoint. OSS deletion/export primitives do not by themselves supply documented subject-rights handling, scheduled retention, and privacy receipts.

| Privacy operation | OSS primitives / inspected boundary | Enterprise workflow described publicly |
|---|---|---|
| Remove memories or documents | Public deletion operations | Subject-oriented erasure flow |
| Export information | Public document/memory interfaces | Subject access export with derived information and processing context |
| Remove data by age or inactivity | An operator can build application policy; the documented subject workflow is not supplied by these primitives | Scheduled subject/tag-scoped retention rules |
| Handle derived information | Depends on the OSS operation used; do not infer full subject erasure from one delete | Documented treatment of observations and mental models |
| Record privacy actions | Ordinary audit functionality is separate | Privacy Events records and receipts |

The commercial feature identifies subjects through stable tags supplied during ingestion; it does not discover every subject by automatically parsing names and email addresses. Correct ingestion tags are therefore part of the workflow. The documented flow includes preview then erasure, subject export, recurring retention, and a durable history of privacy actions. These are product descriptions, not a legal compliance assessment or runtime validation. Source: [Data Privacy](https://docs.hindsight.vectorize.io/enterprise/security/data-privacy/).

The inspected OSS API supplies ordinary memory/document operations, while the advanced privacy UI and the named commercial end-to-end workflow were not identified in the inspected public surfaces. This bounded source finding is not proof that no contributor could build equivalent functionality on OSS. Source: [HTTP API](../../hindsight-api-slim/hindsight_api/api/http.py).

## 9. Cost, operation, and support

Free OSS removes the Hindsight software subscription, not the cost of running a memory system. Enterprise cost and operating responsibility depend on the contract and deployment option.

| Cost / responsibility | OSS self-hosted | Enterprise / commercial deployment |
|---|---|---|
| Hindsight software | MIT-licensed public code | Commercial agreement for additional components and service |
| Compute, database, disks, object storage | You pay and operate | Vendor-funded within the service or customer-funded in BYOC/on-premises, according to contract |
| LLM, embeddings, reranking | Your provider bills or local model resources | Managed or customer-model arrangement; verify the deployment quote |
| Release and migration work | You schedule and execute | Vendor-led or shared, depending on deployment |
| Backups, restore tests, monitoring | You arrange them | Responsibility matrix varies; on-premises remains shared/customer-operated |
| Support | Community and your own maintenance | Contracted support channels and response commitments |
| Identity or policy customization | Your integration and maintenance | Supplied commercial components within their supported scope |

The public repository's license and package metadata establish the OSS licensing boundary; they do not price your infrastructure or third-party model/database products. Sources: [license](../../LICENSE) and [package](../../hindsight-api-slim/pyproject.toml).

The [operations guide](https://docs.hindsight.vectorize.io/enterprise/deployment/operations/) distinguishes who handles infrastructure, releases, migration, monitoring, backups, and restores. In on-premises deployments, your team still operates the infrastructure; “Enterprise” does not transfer every operational duty to Vectorize. The [support guide](https://docs.hindsight.vectorize.io/enterprise/support/) describes commercial support, but exact terms must come from the signed agreement.

No fixed Enterprise price, minimum commitment, seat count, contractual uptime guarantee, or offline licensing requirement is established by this research. They should not be invented from feature tables or ordinary Cloud pricing. The public [Enterprise overview](https://docs.hindsight.vectorize.io/enterprise/) describes contract/invoice arrangements rather than an OSS-style free download of all Enterprise components.

## 10. Documentation discrepancies and verification limits

The documentation contains concrete differences from this source snapshot. For OSS implementation questions, this report uses the inspected public code and its configuration; for private product behavior, it records the vendor's statement and leaves untested details explicit.

| Topic | Commercial statement / ambiguity | Current OSS evidence | Conclusion justified here |
|---|---|---|---|
| Basic blocking | The Enterprise redaction page says a Basic `block` becomes `redact`; its comparison lists block enforcement as Enterprise-only | Bundled detector returns the chosen action; orchestrator handles BLOCK; OSS guide documents rejection | The statement does not describe this inspected OSS path |
| Basic policy UI | Enterprise comparison lists per-bank console policies as paid-only | Public `MemoryDefenseSection` reads, edits, and saves the basic policy | Basic policy editing is present; richer commercial policy controls may differ |
| Webhook infrastructure | Enterprise SIEM page says Basic has no webhook infrastructure | Public delivery manager, models, API, guide, and defense events | Cannot claim all webhooks are closed-source-only |
| Audit logs | Commercial audit page labels the feature Enterprise | Public writer, schema, endpoints, UI, and configuration | Service entitlement differs from OSS source availability |
| Pattern counts | Enterprise pages use 44 basic patterns and 220 total; current OSS docs use 45 | Current OSS guide and commercial pages are not numerically aligned | Use the pinned detector/catalog for coverage; do not treat the numbers as a stable edition contract |
| “All plans” | Cloud article includes roles, scoped keys, and idle timeouts on all plans | OSS shared-key console and built-in auth use different mechanisms | “All Cloud plans” does not mean “bundled in OSS” |
| Enterprise equals dedicated | Overview language emphasizes dedicated installations | Deployment matrix also includes shared Cloud with Enterprise features | Enterprise entitlement does not always imply single tenancy |
| Object storage | Both OSS upload configuration and Memlake mention S3/GCS/Azure | Uploaded-file storage and memory-index storage are separate paths | Configuring OSS file storage does not install Memlake |

References for the disputed statements: [commercial security comparison](https://docs.hindsight.vectorize.io/enterprise/security/overview/), [commercial redaction behavior](https://docs.hindsight.vectorize.io/enterprise/security/redaction/), [commercial webhook statement](https://docs.hindsight.vectorize.io/enterprise/security/webhooks-siem/), and the OSS implementation links in sections 4, 6, and 7. The discrepancies could reflect release or product-context differences; their cause has not been established.

Verification limits: no Enterprise build was installed, no memory was written or deleted, no private contract or production configuration was examined, and no model or performance test was run. Execution quality, exact licensing mechanics, offline activation, private implementation details, parity in a particular commercial release, and independent scale/latency results were not verified. Stronger claims about these would be `[UNVERIFIED ASSUMPTION]`. Public source inspection cannot prove a universal absence across private releases.

## 11. Selection guide

Choose according to the capability and responsibility you need, rather than assuming that production use, a console, authentication, or basic notifications require Enterprise.

| Need | Option to evaluate | Reason |
|---|---|---|
| Core agent memory with an infrastructure team | OSS self-hosted | Core memory workflow and operating controls are public |
| Basic secrets redaction/blocking, activity audit, ordinary events | OSS first | Present in this checkout; configuration and runtime acceptance are still required |
| Named users and a few isolated schemas without the commercial console | OSS tenant extensions | Public implementations exist, with packaging/operating work |
| Managed convenience without a dedicated environment | Ordinary Cloud | Service operation is the principal choice; check commercial feature entitlements |
| Enterprise identity/privacy/security on a shared service | Cloud with Enterprise features | Adds commercial controls without dedicated infrastructure |
| Supported Memlake or integrated advanced security/privacy | Enterprise | These are documented additional product components |
| Dedicated environment operated by the vendor | Private cloud | Isolation without owning the account |
| Data/resources in your cloud account with vendor operation | BYOC | Customer ownership with delegated operation |
| Customer operation or no internet access | On-premises Enterprise, or OSS with your own integrations | Enterprise can be supplied for your cluster; OSS offers public code with your own integration work |

Before buying, ask Vectorize to confirm the precise Enterprise image/chart release, included detectors, Memlake availability, identity/key capabilities, offline requirements, upgrade/backup ownership, and fees for the selected deployment. These details are not resolved by a generic “Enterprise” label.

## 12. Sources

The links below separate the pinned local implementation evidence from vendor descriptions. All local paths are relative to this file; they refer to the checkout identified in section 1 and can change after a checkout update.

| Source | What it supports |
|---|---|
| [OSS license](../../LICENSE) and [package metadata](../../hindsight-api-slim/pyproject.toml) | License and package version |
| [Public edition overview](../../hindsight-docs/docs/cloud-enterprise/overview.md) | OSS/Cloud/Enterprise framing |
| [Memory-store factory](../../hindsight-api-slim/hindsight_api/engine/memories/__init__.py) and [default store](../../hindsight-api-slim/hindsight_api/engine/memories/postgres.py) | OSS storage boundary |
| [Extensions registry](../../hindsight-extensions/README.md) | Public extension slots and packaging |
| [Built-in auth](../../hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py) and [console session](../../hindsight-control-plane/src/lib/auth/session.ts) | API key and shared-key console behavior |
| [OSS configuration](../../hindsight-docs/docs/developer/configuration.mdx) | Audit, tracing, model/database configuration, uploaded-file storage |
| [Basic defense implementation](../../hindsight-api-slim/hindsight_api/extensions/builtin/memory_defense_regex.py) and [retain orchestrator](../../hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py) | Basic redaction/block behavior |
| [OSS webhook guide](../../hindsight-docs/docs/developer/api/webhooks.mdx) | Public webhook capability |
| [Enterprise deployment choices](https://docs.hindsight.vectorize.io/enterprise/deployment/overview/) | Four commercial delivery options |
| [On-premises](https://docs.hindsight.vectorize.io/enterprise/deployment/on-premises/) and [BYOC](https://docs.hindsight.vectorize.io/enterprise/deployment/byoc/) | Customer-hosted commercial delivery |
| [Memlake overview](https://docs.hindsight.vectorize.io/enterprise/memlake/), [architecture](https://docs.hindsight.vectorize.io/enterprise/memlake/architecture/), [tradeoffs](https://docs.hindsight.vectorize.io/enterprise/memlake/tradeoffs/) | Commercial storage design and limitations |
| [SSO](https://docs.hindsight.vectorize.io/enterprise/sso/), [API keys](https://docs.hindsight.vectorize.io/enterprise/api-keys/), [team management](https://docs.hindsight.vectorize.io/enterprise/team-management/) | Commercial identity and administration |
| [Memory Defense overview](https://docs.hindsight.vectorize.io/enterprise/security/overview/), [redaction](https://docs.hindsight.vectorize.io/enterprise/security/redaction/), [detectors](https://docs.hindsight.vectorize.io/enterprise/security/detectors/) | Commercial security components and disputed Basic claims |
| [Audit logs](https://docs.hindsight.vectorize.io/enterprise/security/audit-logs/) and [Webhook/SIEM](https://docs.hindsight.vectorize.io/enterprise/security/webhooks-siem/) | Commercial audit/security-event descriptions |
| [Data Privacy](https://docs.hindsight.vectorize.io/enterprise/security/data-privacy/) | Commercial subject-rights workflow |
| [Operations](https://docs.hindsight.vectorize.io/enterprise/deployment/operations/) and [support](https://docs.hindsight.vectorize.io/enterprise/support/) | Responsibility and support boundaries |
