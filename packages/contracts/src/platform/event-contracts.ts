/**
 * Cross-system event and asynchronous-command registry for SYS-01 .. SYS-08.
 *
 * This file is the executable source of truth for Topic ACL registration,
 * AsyncAPI generation, fixtures and consumer/provider contract tests.  It is
 * intentionally independent from the legacy MVP exports so it can be reviewed
 * and frozen before the package entrypoint is changed.
 *
 * Contract rules:
 * - one eventType owns exactly one versioned Topic;
 * - schemaVersion is the payload/envelope schema version (there is no
 *   eventVersion field);
 * - payload.producer never authenticates a sender: Broker principal + Topic ACL
 *   is authoritative;
 * - additive, optional fields are the only compatible changes within v1;
 * - a breaking change requires a new eventType/topic/schemaVersion contract.
 */

export const PLATFORM_EVENT_SCHEMA_DIALECT =
  "https://json-schema.org/draft/2020-12/schema" as const;

export const PLATFORM_SYSTEMS = [
  "SYS-01",
  "SYS-02",
  "SYS-03",
  "SYS-04",
  "SYS-05",
  "SYS-06",
  "SYS-07",
  "SYS-08",
] as const;

export type PlatformSystem = (typeof PLATFORM_SYSTEMS)[number];

export const PLATFORM_PRODUCERS = [
  ...PLATFORM_SYSTEMS,
  "REVIEW_CENTER",
  "REGISTERED_DOMAIN_ADAPTER",
] as const;

export type PlatformProducer = (typeof PLATFORM_PRODUCERS)[number];

export const PLATFORM_ENVIRONMENTS = ["DEV", "TEST", "STAGING", "PROD"] as const;
export type PlatformEnvironment = (typeof PLATFORM_ENVIRONMENTS)[number];

export type PlatformMessageKind = "EVENT" | "COMMAND" | "COMPATIBILITY_ALIAS";

export interface JsonSchema {
  readonly $schema?: string;
  readonly $id?: string;
  readonly title?: string;
  readonly description?: string;
  readonly type?:
    | "object"
    | "array"
    | "string"
    | "integer"
    | "number"
    | "boolean"
    | "null";
  readonly const?: string | number | boolean | null;
  readonly enum?: readonly (string | number | boolean | null)[];
  readonly format?: string;
  readonly pattern?: string;
  readonly minimum?: number;
  readonly maximum?: number;
  readonly minLength?: number;
  readonly minItems?: number;
  readonly uniqueItems?: boolean;
  readonly properties?: Readonly<Record<string, JsonSchema>>;
  readonly required?: readonly string[];
  readonly items?: JsonSchema;
  readonly additionalProperties?: boolean | JsonSchema;
  readonly anyOf?: readonly JsonSchema[];
  readonly oneOf?: readonly JsonSchema[];
}

export interface PlatformEventEnvelope<TPayload = Record<string, unknown>> {
  readonly eventId: string;
  readonly eventType: string;
  readonly schemaVersion: number;
  readonly occurredAt: string;
  readonly publishedAt: string;
  readonly producer: PlatformProducer;
  readonly environment: PlatformEnvironment;
  readonly audience: readonly PlatformSystem[];
  readonly enterpriseId: string | null;
  readonly aggregateType: string;
  readonly aggregateId: string;
  readonly aggregateVersion: number;
  readonly traceId: string;
  readonly causationId: string | null;
  readonly correlationId: string;
  readonly idempotencyKey: string;
  readonly payload: TPayload;
}

export interface PlatformAggregateContract {
  readonly type: string;
  readonly idField: string;
  readonly versionField?: string;
  readonly fixedVersion?: number;
  readonly sampleId: string;
  readonly sampleVersion: number;
}

export interface PlatformCompatibilityPolicy {
  readonly withinSchemaVersion: "ADDITIVE_OPTIONAL_FIELDS_ONLY";
  readonly breakingChange: "NEW_EVENT_TYPE_TOPIC_AND_SCHEMA_VERSION";
  readonly unknownSchema: "SECURITY_QUARANTINE_AND_DEAD_LETTER";
  readonly replay: "SAME_EVENT_ID_AND_BYTE_STABLE_PAYLOAD";
}

export interface PlatformEventContract {
  readonly messageKind: PlatformMessageKind;
  readonly eventType: string;
  readonly topic: string;
  readonly producer: PlatformProducer;
  readonly consumers: readonly PlatformSystem[];
  readonly audience: readonly PlatformSystem[];
  readonly schemaVersion: number;
  readonly aggregate: PlatformAggregateContract;
  readonly payloadSchema: JsonSchema;
  readonly example: PlatformEventEnvelope<Record<string, unknown>>;
  /** Stable business-key template. Placeholders are wrapped in braces. */
  readonly idempotencyKey: string;
  readonly idempotencyExample: string;
  readonly businessUniqueness: string;
  readonly conflictPolicy: "SAME_KEY_SAME_PAYLOAD_RETURNS_ORIGINAL_DIFFERENT_PAYLOAD_QUARANTINED";
  readonly compatibility: PlatformCompatibilityPolicy;
  readonly piiPolicy: string;
  readonly notes?: string;
}

const COMPATIBILITY_POLICY: PlatformCompatibilityPolicy = {
  withinSchemaVersion: "ADDITIVE_OPTIONAL_FIELDS_ONLY",
  breakingChange: "NEW_EVENT_TYPE_TOPIC_AND_SCHEMA_VERSION",
  unknownSchema: "SECURITY_QUARANTINE_AND_DEAD_LETTER",
  replay: "SAME_EVENT_ID_AND_BYTE_STABLE_PAYLOAD",
};

const string = (description?: string, pattern?: string): JsonSchema => ({
  type: "string",
  minLength: 1,
  ...(description === undefined ? {} : { description }),
  ...(pattern === undefined ? {} : { pattern }),
});

const id = (prefix?: string): JsonSchema =>
  string(
    prefix === undefined ? "Stable opaque business identifier" : `Stable ${prefix} identifier`,
    prefix === undefined ? "^[A-Za-z][A-Za-z0-9_-]+$" : `^${prefix}[A-Za-z0-9_-]+$`,
  );

const dateTime = (description?: string): JsonSchema => ({
  type: "string",
  format: "date-time",
  ...(description === undefined ? {} : { description }),
});

const integer = (minimum = 0, description?: string): JsonSchema => ({
  type: "integer",
  minimum,
  ...(description === undefined ? {} : { description }),
});

const boolean: JsonSchema = { type: "boolean" };

const enumeration = <T extends readonly string[]>(values: T, description?: string): JsonSchema => ({
  type: "string",
  enum: values,
  ...(description === undefined ? {} : { description }),
});

const nullable = (schema: JsonSchema): JsonSchema => ({
  anyOf: [schema, { type: "null" }],
});

const array = (items: JsonSchema, minItems = 0): JsonSchema => ({
  type: "array",
  items,
  minItems,
});

const record = (
  properties: Readonly<Record<string, JsonSchema>>,
  required: readonly string[],
  description?: string,
): JsonSchema => ({
  type: "object",
  properties,
  required,
  additionalProperties: false,
  ...(description === undefined ? {} : { description }),
});

const openRecord = (description: string): JsonSchema => ({
  type: "object",
  description,
  additionalProperties: true,
});

const hash = string("Lower-case SHA-256 digest", "^[a-f0-9]{64}$");
const version = integer(1, "Monotonically increasing source version");
const amountFen = integer(0, "Non-negative integer amount in fen");
const points = integer(0, "Non-negative integer points amount");
const currency = enumeration(["CNY"] as const);

interface ContractDefinition {
  readonly messageKind?: PlatformMessageKind;
  readonly eventType: string;
  readonly topic: string;
  readonly producer: PlatformProducer;
  readonly consumers: readonly PlatformSystem[];
  readonly aggregate: PlatformAggregateContract;
  readonly payloadSchema: JsonSchema;
  readonly payloadExample: Record<string, unknown>;
  readonly idempotencyKey: string;
  readonly idempotencyExample: string;
  readonly businessUniqueness: string;
  readonly piiPolicy?: string;
  readonly notes?: string;
}

function defineContract(definition: ContractDefinition): PlatformEventContract {
  const schemaVersion = 1;
  const payloadSchema: JsonSchema = {
    ...definition.payloadSchema,
    $schema: PLATFORM_EVENT_SCHEMA_DIALECT,
    $id: `https://contracts.wotaotao.com/events/${definition.topic}/payload.schema.json`,
    title: `${definition.eventType} payload v${schemaVersion}`,
  };
  const example: PlatformEventEnvelope<Record<string, unknown>> = {
    eventId: `evt_${definition.eventType.replace(/[^A-Za-z0-9]/g, "_").toLowerCase()}_001`,
    eventType: definition.eventType,
    schemaVersion,
    occurredAt: "2026-08-10T02:00:00Z",
    publishedAt: "2026-08-10T02:00:01Z",
    producer: definition.producer,
    environment: "DEV",
    audience: definition.consumers,
    enterpriseId:
      typeof definition.payloadExample.enterpriseId === "string"
        ? definition.payloadExample.enterpriseId
        : null,
    aggregateType: definition.aggregate.type,
    aggregateId: definition.aggregate.sampleId,
    aggregateVersion: definition.aggregate.sampleVersion,
    traceId: "trace_contract_fixture_001",
    causationId: null,
    correlationId: "corr_contract_fixture_001",
    idempotencyKey: definition.idempotencyExample,
    payload: definition.payloadExample,
  };

  return {
    messageKind: definition.messageKind ?? "EVENT",
    eventType: definition.eventType,
    topic: definition.topic,
    producer: definition.producer,
    consumers: definition.consumers,
    audience: definition.consumers,
    schemaVersion,
    aggregate: definition.aggregate,
    payloadSchema,
    example,
    idempotencyKey: definition.idempotencyKey,
    idempotencyExample: definition.idempotencyExample,
    businessUniqueness: definition.businessUniqueness,
    conflictPolicy: "SAME_KEY_SAME_PAYLOAD_RETURNS_ORIGINAL_DIFFERENT_PAYLOAD_QUARANTINED",
    compatibility: COMPATIBILITY_POLICY,
    piiPolicy:
      definition.piiPolicy ??
      "No credentials, tokens, cookies, complete payout details, contact details or raw evidence.",
    ...(definition.notes === undefined ? {} : { notes: definition.notes }),
  };
}

const aggregate = (
  type: string,
  idField: string,
  sampleId: string,
  versionField: string | undefined,
  sampleVersion = 1,
  fixedVersion?: number,
): PlatformAggregateContract => ({
  type,
  idField,
  sampleId,
  sampleVersion,
  ...(versionField === undefined ? {} : { versionField }),
  ...(fixedVersion === undefined ? {} : { fixedVersion }),
});

const enterpriseId = id("ent_");
const sourceVersion = version;

const IDENTITY_EVENT_CONTRACTS = [
  defineContract({
    eventType: "UserRegistered",
    topic: "platform.identity.user.registered.v1",
    producer: "SYS-01",
    consumers: ["SYS-01"],
    aggregate: aggregate("User", "userId", "usr_contract_001", "userVersion"),
    payloadSchema: record(
      {
        userId: id("usr_"),
        userVersion: version,
        registrationMethod: enumeration(["PHONE", "OAUTH"] as const),
        clientType: enumeration(["WORKBENCH", "MALL", "OPC", "ADMIN"] as const),
        registeredAt: dateTime(),
      },
      ["userId", "userVersion", "registrationMethod", "clientType", "registeredAt"],
    ),
    payloadExample: {
      userId: "usr_contract_001",
      userVersion: 1,
      registrationMethod: "PHONE",
      clientType: "WORKBENCH",
      registeredAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "USER_REGISTERED:{userId}:{userVersion}",
    idempotencyExample: "USER_REGISTERED:usr_contract_001:1",
    businessUniqueness: "userId + userVersion",
    piiPolicy: "No phone number, verification code, OAuth code or session token.",
  }),
  defineContract({
    eventType: "EnterpriseInitialized",
    topic: "platform.enterprise.initialized.v1",
    producer: "SYS-01",
    consumers: ["SYS-03", "SYS-04", "SYS-05", "SYS-06", "SYS-08"],
    aggregate: aggregate("Enterprise", "enterpriseId", "ent_contract_001", "initializationVersion"),
    payloadSchema: record(
      {
        enterpriseId,
        profileId: id("epr_"),
        profileVersion: version,
        initializationVersion: version,
        industryCode: string(),
        primaryProductCodes: array(string(), 1),
        enterpriseStatus: enumeration(["ACTIVE", "REVIEW_REQUIRED", "SUSPENDED"] as const),
        initializedAt: dateTime(),
      },
      [
        "enterpriseId",
        "profileId",
        "profileVersion",
        "initializationVersion",
        "industryCode",
        "primaryProductCodes",
        "enterpriseStatus",
        "initializedAt",
      ],
    ),
    payloadExample: {
      enterpriseId: "ent_contract_001",
      profileId: "epr_contract_001",
      profileVersion: 1,
      initializationVersion: 1,
      industryCode: "RETAIL",
      primaryProductCodes: ["HOME_GOODS"],
      enterpriseStatus: "ACTIVE",
      initializedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "INIT_ENTERPRISE_BENEFITS:{enterpriseId}",
    idempotencyExample: "INIT_ENTERPRISE_BENEFITS:ent_contract_001",
    businessUniqueness: "enterpriseId initializationVersion=1; SYS-08 creates FREE benefits once",
  }),
  defineContract({
    eventType: "EnterpriseProfileUpdated",
    topic: "platform.enterprise.profile_updated.v1",
    producer: "SYS-01",
    consumers: ["SYS-03", "SYS-04", "SYS-05", "SYS-06"],
    aggregate: aggregate("EnterpriseProfile", "profileId", "epr_contract_001", "profileVersion", 2),
    payloadSchema: record(
      {
        enterpriseId,
        profileId: id("epr_"),
        profileVersion: version,
        industryCode: string(),
        primaryProductCodes: array(string(), 1),
        profileStatus: enumeration(["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"] as const),
        snapshotHash: hash,
        updatedAt: dateTime(),
      },
      [
        "enterpriseId",
        "profileId",
        "profileVersion",
        "industryCode",
        "primaryProductCodes",
        "profileStatus",
        "snapshotHash",
        "updatedAt",
      ],
    ),
    payloadExample: {
      enterpriseId: "ent_contract_001",
      profileId: "epr_contract_001",
      profileVersion: 2,
      industryCode: "RETAIL",
      primaryProductCodes: ["HOME_GOODS", "LIFESTYLE"],
      profileStatus: "APPROVED",
      snapshotHash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      updatedAt: "2026-08-10T02:05:00Z",
    },
    idempotencyKey: "ENTERPRISE_PROFILE:{enterpriseId}:{profileVersion}",
    idempotencyExample: "ENTERPRISE_PROFILE:ent_contract_001:2",
    businessUniqueness: "enterpriseId + profileVersion; old versions remain addressable",
  }),
  defineContract({
    eventType: "EnterpriseReviewChanged",
    topic: "platform.enterprise.review-changed.v1",
    producer: "SYS-01",
    consumers: ["SYS-03", "SYS-04", "SYS-05"],
    aggregate: aggregate(
      "EnterpriseReviewSubmission",
      "reviewSubmissionId",
      "ers_contract_001",
      "decisionVersion",
    ),
    payloadSchema: record(
      {
        reviewSubmissionId: id("ers_"),
        enterpriseId,
        profileVersion: version,
        changeType: enumeration(["SUBMITTED", "RESUBMITTED", "APPROVED", "REJECTED"] as const),
        reviewStatus: enumeration(["PENDING", "APPROVED", "REJECTED"] as const),
        decisionVersion: version,
        reasonCode: nullable(string()),
        changedAt: dateTime(),
      },
      [
        "reviewSubmissionId",
        "enterpriseId",
        "profileVersion",
        "changeType",
        "reviewStatus",
        "decisionVersion",
        "reasonCode",
        "changedAt",
      ],
    ),
    payloadExample: {
      reviewSubmissionId: "ers_contract_001",
      enterpriseId: "ent_contract_001",
      profileVersion: 2,
      changeType: "APPROVED",
      reviewStatus: "APPROVED",
      decisionVersion: 1,
      reasonCode: null,
      changedAt: "2026-08-10T02:10:00Z",
    },
    idempotencyKey: "ENTERPRISE_REVIEW:{reviewSubmissionId}:{decisionVersion}",
    idempotencyExample: "ENTERPRISE_REVIEW:ers_contract_001:1",
    businessUniqueness: "reviewSubmissionId + decisionVersion",
  }),
  defineContract({
    eventType: "EnterpriseWhitelistChanged",
    topic: "platform.enterprise.whitelist-changed.v1",
    producer: "SYS-01",
    consumers: ["SYS-03", "SYS-04", "SYS-05", "SYS-06", "SYS-08"],
    aggregate: aggregate("EnterpriseWhitelist", "scopeRef", "wls_contract_001", "version"),
    payloadSchema: record(
      {
        scopeRef: id("wls_"),
        enterpriseId,
        abilityCode: string(),
        status: enumeration(["ACTIVE", "EXPIRED", "REVOKED"] as const),
        version,
        effectiveAt: dateTime(),
        expiresAt: nullable(dateTime()),
        reasonCode: string(),
      },
      [
        "scopeRef",
        "enterpriseId",
        "abilityCode",
        "status",
        "version",
        "effectiveAt",
        "expiresAt",
        "reasonCode",
      ],
    ),
    payloadExample: {
      scopeRef: "wls_contract_001",
      enterpriseId: "ent_contract_001",
      abilityCode: "DOUYIN_PUBLISH",
      status: "ACTIVE",
      version: 1,
      effectiveAt: "2026-08-10T02:00:00Z",
      expiresAt: "2026-09-10T02:00:00Z",
      reasonCode: "PILOT_APPROVED",
    },
    idempotencyKey: "ENTERPRISE_WHITELIST:{scopeRef}:{version}",
    idempotencyExample: "ENTERPRISE_WHITELIST:wls_contract_001:1",
    businessUniqueness: "scopeRef + version; active enterprise/user/ability scope is unique",
  }),
  defineContract({
    eventType: "EnterpriseMemberChanged",
    topic: "platform.enterprise.member_changed.v1",
    producer: "SYS-01",
    consumers: ["SYS-03", "SYS-04", "SYS-05", "SYS-06", "SYS-08"],
    aggregate: aggregate("EnterpriseMember", "enterpriseMemberId", "emr_contract_001", "version", 2),
    payloadSchema: record(
      {
        enterpriseMemberId: id("emr_"),
        enterpriseId,
        userId: id("usr_"),
        changeType: enumeration(
          ["BOUND", "ROLE_CHANGED", "SUSPENDED", "RESUMED", "REMOVED"] as const,
        ),
        roleCodes: array(string(), 1),
        dataScope: openRecord("Normalized, non-secret authorization data scope"),
        memberStatus: enumeration(["ACTIVE", "SUSPENDED", "REMOVED"] as const),
        source: enumeration(["PLATFORM_CONTROLLED_BINDING", "FUTURE_INVITATION"] as const),
        version,
        effectiveAt: dateTime(),
        reasonCode: string(),
      },
      [
        "enterpriseMemberId",
        "enterpriseId",
        "userId",
        "changeType",
        "roleCodes",
        "dataScope",
        "memberStatus",
        "source",
        "version",
        "effectiveAt",
        "reasonCode",
      ],
    ),
    payloadExample: {
      enterpriseMemberId: "emr_contract_001",
      enterpriseId: "ent_contract_001",
      userId: "usr_contract_001",
      changeType: "ROLE_CHANGED",
      roleCodes: ["ENTERPRISE_ADMIN"],
      dataScope: { storeIds: ["store_contract_001"] },
      memberStatus: "ACTIVE",
      source: "PLATFORM_CONTROLLED_BINDING",
      version: 2,
      effectiveAt: "2026-08-10T02:00:00Z",
      reasonCode: "ADMIN_APPROVED",
    },
    idempotencyKey: "ENTERPRISE_MEMBER:{enterpriseMemberId}:{version}",
    idempotencyExample: "ENTERPRISE_MEMBER:emr_contract_001:2",
    businessUniqueness: "enterpriseMemberId + version; one active enterprise/user relationship",
  }),
  defineContract({
    eventType: "FeatureFlagChanged",
    topic: "platform.feature-flag.changed.v1",
    producer: "SYS-01",
    consumers: ["SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-06", "SYS-07", "SYS-08"],
    aggregate: aggregate("FeatureFlag", "flagCode", "DOUYIN_AUTO_PUBLISH", "version", 2),
    payloadSchema: record(
      {
        flagCode: string(),
        scopeType: enumeration(["GLOBAL", "ENTERPRISE", "USER"] as const),
        scopeId: nullable(string()),
        value: boolean,
        version,
        changeType: enumeration(["UPDATED", "ROLLED_BACK"] as const),
        reasonCode: string(),
        effectiveAt: dateTime(),
      },
      ["flagCode", "scopeType", "scopeId", "value", "version", "changeType", "reasonCode", "effectiveAt"],
    ),
    payloadExample: {
      flagCode: "DOUYIN_AUTO_PUBLISH",
      scopeType: "ENTERPRISE",
      scopeId: "ent_contract_001",
      value: true,
      version: 2,
      changeType: "UPDATED",
      reasonCode: "PILOT_OPEN",
      effectiveAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "FEATURE_FLAG:{flagCode}:{scopeType}:{scopeId}:{version}",
    idempotencyExample: "FEATURE_FLAG:DOUYIN_AUTO_PUBLISH:ENTERPRISE:ent_contract_001:2",
    businessUniqueness: "flagCode + scopeType + scopeId + version",
  }),
  defineContract({
    eventType: "AgentToolExecutionReported",
    topic: "platform.agent.tool-execution-reported.v1",
    producer: "REGISTERED_DOMAIN_ADAPTER",
    consumers: ["SYS-01"],
    aggregate: aggregate("AgentRun", "agentRunId", "arun_contract_001", "resultVersion"),
    payloadSchema: record(
      {
        agentRunId: id("arun_"),
        toolRunId: id("trun_"),
        toolCallId: nullable(id("tcall_")),
        toolCode: string(),
        domainSystem: enumeration(["SYS-04", "SYS-05"] as const),
        enterpriseId,
        businessRefs: array(record({ type: string(), id: string(), version }, ["type", "id", "version"]), 1),
        inputVersion: version,
        status: enumeration(["SUCCEEDED", "FAILED", "CANCELLED", "PARTIAL"] as const),
        billingPoint: nullable(string()),
        retryable: boolean,
        resultVersion: version,
        toolAuthorizationRef: string(),
        resultSummary: nullable(string("Non-sensitive result summary")),
        failureCode: nullable(string()),
        reportedAt: dateTime(),
        traceId: string(),
      },
      [
        "agentRunId",
        "toolRunId",
        "toolCallId",
        "toolCode",
        "domainSystem",
        "enterpriseId",
        "businessRefs",
        "inputVersion",
        "status",
        "billingPoint",
        "retryable",
        "resultVersion",
        "toolAuthorizationRef",
        "resultSummary",
        "failureCode",
        "reportedAt",
        "traceId",
      ],
    ),
    payloadExample: {
      agentRunId: "arun_contract_001",
      toolRunId: "trun_contract_001",
      toolCallId: "tcall_contract_001",
      toolCode: "CONTENT_PUBLISH",
      domainSystem: "SYS-05",
      enterpriseId: "ent_contract_001",
      businessRefs: [{ type: "ChannelPublication", id: "cpub_contract_001", version: 1 }],
      inputVersion: 1,
      status: "SUCCEEDED",
      billingPoint: "PUBLICATION_ACCEPTED",
      retryable: false,
      resultVersion: 1,
      toolAuthorizationRef: "tauth_contract_001",
      resultSummary: "Publication result recorded",
      failureCode: null,
      reportedAt: "2026-08-10T02:00:00Z",
      traceId: "trace_contract_fixture_001",
    },
    idempotencyKey: "AGENT_TOOL_RESULT:{agentRunId}:{toolRunId}:{resultVersion}",
    idempotencyExample: "AGENT_TOOL_RESULT:arun_contract_001:trun_contract_001:1",
    businessUniqueness: "agentRunId + toolRunId + resultVersion",
    notes:
      "SYS-04 MarketingAgentExecutionReported and SYS-05 ContentPublishingAgentExecutionReported are aliases normalized into this message with the same toolRunId/resultVersion/payloadHash.",
  }),
  defineContract({
    eventType: "AgentRunStatusChanged",
    topic: "platform.agent.run-status-changed.v1",
    producer: "SYS-01",
    consumers: ["SYS-04", "SYS-05", "SYS-06"],
    aggregate: aggregate("AgentRun", "agentRunId", "arun_contract_001", "agentRunVersion", 2),
    payloadSchema: record(
      {
        agentRunId: id("arun_"),
        enterpriseId,
        agentCode: string(),
        oldStatus: enumeration(["CREATED", "RUNNING", "PARTIAL", "SUCCEEDED", "FAILED", "CANCELLED"] as const),
        newStatus: enumeration(["CREATED", "RUNNING", "PARTIAL", "SUCCEEDED", "FAILED", "CANCELLED"] as const),
        agentRunVersion: version,
        completedToolCount: integer(),
        failedToolCount: integer(),
        businessRefs: array(record({ type: string(), id: string(), version }, ["type", "id", "version"])),
        changedAt: dateTime(),
      },
      [
        "agentRunId",
        "enterpriseId",
        "agentCode",
        "oldStatus",
        "newStatus",
        "agentRunVersion",
        "completedToolCount",
        "failedToolCount",
        "businessRefs",
        "changedAt",
      ],
    ),
    payloadExample: {
      agentRunId: "arun_contract_001",
      enterpriseId: "ent_contract_001",
      agentCode: "CONTENT_PUBLISHING_AGENT",
      oldStatus: "RUNNING",
      newStatus: "SUCCEEDED",
      agentRunVersion: 2,
      completedToolCount: 1,
      failedToolCount: 0,
      businessRefs: [{ type: "ChannelPublication", id: "cpub_contract_001", version: 1 }],
      changedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "AGENT_RUN_STATUS:{agentRunId}:{agentRunVersion}",
    idempotencyExample: "AGENT_RUN_STATUS:arun_contract_001:2",
    businessUniqueness: "agentRunId + agentRunVersion; SYS-01 is the only run-status aggregator",
  }),
  defineContract({
    eventType: "ConsumerTrialAccessChanged",
    topic: "commerce.consumer.trial-access-changed.v1",
    producer: "SYS-02",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("ConsumerTrialAccess", "trialAccessId", "cta_contract_001", "version", 2),
    payloadSchema: record(
      {
        trialAccessId: id("cta_"),
        subjectType: enumeration(["USER", "PHONE_HASH", "INVITATION"] as const),
        subjectRefHash: hash,
        status: enumeration(["ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED"] as const),
        version,
        effectiveAt: dateTime(),
        expiresAt: nullable(dateTime()),
        changedAt: dateTime(),
      },
      ["trialAccessId", "subjectType", "subjectRefHash", "status", "version", "effectiveAt", "expiresAt", "changedAt"],
    ),
    payloadExample: {
      trialAccessId: "cta_contract_001",
      subjectType: "USER",
      subjectRefHash: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      status: "ACTIVE",
      version: 2,
      effectiveAt: "2026-08-10T02:00:00Z",
      expiresAt: "2026-09-10T02:00:00Z",
      changedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "CONSUMER_TRIAL_ACCESS:{trialAccessId}:{version}",
    idempotencyExample: "CONSUMER_TRIAL_ACCESS:cta_contract_001:2",
    businessUniqueness: "trialAccessId + version",
    piiPolicy: "Only a one-way subjectRefHash; never a phone number or invitation code.",
    notes: "This event never grants enterprise whitelist abilities.",
  }),
] as const;

const COMMERCE_EVENT_CONTRACTS = [
  defineContract({
    eventType: "ProductPublished",
    topic: "commerce.product.published.v1",
    producer: "SYS-03",
    consumers: ["SYS-02", "SYS-04", "SYS-05", "SYS-06"],
    aggregate: aggregate("Product", "productId", "prd_contract_001", "productVersion", 3),
    payloadSchema: record(
      {
        productId: id("prd_"),
        productVersion: version,
        enterpriseId,
        storeId: id("store_"),
        salesModel: enumeration(["SELF_OPERATED", "MERCHANT", "SUPPLIER"] as const),
        sellerEnterpriseId: enterpriseId,
        supplierId: nullable(string()),
        payeeType: enumeration(["PLATFORM", "MERCHANT", "SUPPLIER"] as const),
        skuVersionRefs: array(record({ skuId: id("sku_"), skuVersion: version }, ["skuId", "skuVersion"]), 1),
        publicStatus: enumeration(["PUBLISHED", "UNPUBLISHED"] as const),
        publishedProductSnapshotRef: id("pps_"),
        snapshotHash: hash,
        publishedAt: dateTime(),
      },
      [
        "productId",
        "productVersion",
        "enterpriseId",
        "storeId",
        "salesModel",
        "sellerEnterpriseId",
        "supplierId",
        "payeeType",
        "skuVersionRefs",
        "publicStatus",
        "publishedProductSnapshotRef",
        "snapshotHash",
        "publishedAt",
      ],
    ),
    payloadExample: {
      productId: "prd_contract_001",
      productVersion: 3,
      enterpriseId: "ent_contract_001",
      storeId: "store_contract_001",
      salesModel: "MERCHANT",
      sellerEnterpriseId: "ent_contract_001",
      supplierId: null,
      payeeType: "MERCHANT",
      skuVersionRefs: [{ skuId: "sku_contract_001", skuVersion: 2 }],
      publicStatus: "PUBLISHED",
      publishedProductSnapshotRef: "pps_contract_001",
      snapshotHash: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      publishedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "PRODUCT_PUBLISHED:{productId}:{productVersion}",
    idempotencyExample: "PRODUCT_PUBLISHED:prd_contract_001:3",
    businessUniqueness: "productId + productVersion; snapshotRef content hash is immutable",
    notes: "Consumers must read the immutable trading snapshot by ref/version/hash and must not infer salesModel.",
  }),
  defineContract({
    eventType: "InventoryChanged",
    topic: "commerce.inventory.changed.v1",
    producer: "SYS-03",
    consumers: ["SYS-02", "SYS-06"],
    aggregate: aggregate("Inventory", "skuId", "sku_contract_001", "inventoryVersion", 4),
    payloadSchema: record(
      {
        enterpriseId,
        storeId: id("store_"),
        skuId: id("sku_"),
        availableQuantity: integer(),
        inventoryVersion: version,
        reasonCode: string(),
        changedAt: dateTime(),
      },
      ["enterpriseId", "storeId", "skuId", "availableQuantity", "inventoryVersion", "reasonCode", "changedAt"],
    ),
    payloadExample: {
      enterpriseId: "ent_contract_001",
      storeId: "store_contract_001",
      skuId: "sku_contract_001",
      availableQuantity: 98,
      inventoryVersion: 4,
      reasonCode: "MANUAL_ADJUSTMENT",
      changedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "INVENTORY_CHANGED:{skuId}:{inventoryVersion}",
    idempotencyExample: "INVENTORY_CHANGED:sku_contract_001:4",
    businessUniqueness: "skuId + inventoryVersion",
    notes: "This invalidates display caches; checkout still performs an authoritative reservation.",
  }),
  defineContract({
    eventType: "InventoryReservationCreated",
    topic: "commerce.inventory-reservation.created.v1",
    producer: "SYS-03",
    consumers: ["SYS-02"],
    aggregate: aggregate("InventoryReservation", "reservationId", "ires_contract_001", "reservationVersion"),
    payloadSchema: record(
      {
        commandId: id("cmd_"),
        reservationId: id("ires_"),
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        enterpriseId,
        reservationVersion: version,
        expiresAt: dateTime(),
        itemSummaryHash: hash,
        result: enumeration(["RESERVED"] as const),
        createdAt: dateTime(),
        traceId: string(),
      },
      [
        "commandId",
        "reservationId",
        "orderId",
        "subOrderId",
        "enterpriseId",
        "reservationVersion",
        "expiresAt",
        "itemSummaryHash",
        "result",
        "createdAt",
        "traceId",
      ],
    ),
    payloadExample: {
      commandId: "cmd_inventory_reserve_001",
      reservationId: "ires_contract_001",
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      enterpriseId: "ent_contract_001",
      reservationVersion: 1,
      expiresAt: "2026-08-10T02:15:00Z",
      itemSummaryHash: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      result: "RESERVED",
      createdAt: "2026-08-10T02:00:00Z",
      traceId: "trace_contract_fixture_001",
    },
    idempotencyKey: "INVENTORY_RESERVE:{orderId}",
    idempotencyExample: "INVENTORY_RESERVE:ord_contract_001",
    businessUniqueness: "one active reservationId per orderId; commandId is globally unique",
  }),
  defineContract({
    eventType: "InventoryReservationCommitted",
    topic: "commerce.inventory-reservation.committed.v1",
    producer: "SYS-03",
    consumers: ["SYS-02"],
    aggregate: aggregate("InventoryReservation", "reservationId", "ires_contract_001", "reservationVersion", 2),
    payloadSchema: record(
      {
        commandId: id("cmd_"),
        reservationId: id("ires_"),
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        enterpriseId,
        paymentId: id("pay_"),
        orderVersion: version,
        reservationVersion: version,
        result: enumeration(["COMMITTED"] as const),
        committedAt: dateTime(),
        traceId: string(),
      },
      [
        "commandId",
        "reservationId",
        "orderId",
        "subOrderId",
        "enterpriseId",
        "paymentId",
        "orderVersion",
        "reservationVersion",
        "result",
        "committedAt",
        "traceId",
      ],
    ),
    payloadExample: {
      commandId: "cmd_inventory_commit_001",
      reservationId: "ires_contract_001",
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      enterpriseId: "ent_contract_001",
      paymentId: "pay_contract_001",
      orderVersion: 2,
      reservationVersion: 2,
      result: "COMMITTED",
      committedAt: "2026-08-10T02:02:00Z",
      traceId: "trace_contract_fixture_001",
    },
    idempotencyKey: "INVENTORY_COMMIT:{reservationId}:{paymentId}",
    idempotencyExample: "INVENTORY_COMMIT:ires_contract_001:pay_contract_001",
    businessUniqueness: "reservationId + paymentId; COMMITTED and RELEASED are mutually exclusive",
  }),
  defineContract({
    eventType: "InventoryReservationReleased",
    topic: "commerce.inventory-reservation.released.v1",
    producer: "SYS-03",
    consumers: ["SYS-02"],
    aggregate: aggregate("InventoryReservation", "reservationId", "ires_contract_001", "releaseVersion", 2),
    payloadSchema: record(
      {
        commandId: id("cmd_"),
        reservationId: id("ires_"),
        orderId: id("ord_"),
        enterpriseId,
        reason: enumeration(["USER_CANCEL", "EXPIRED", "PAYMENT_CLOSED", "ORDER_CREATE_FAILED"] as const),
        orderVersion: version,
        releaseVersion: version,
        result: enumeration(["RELEASED"] as const),
        releasedAt: dateTime(),
        traceId: string(),
      },
      [
        "commandId",
        "reservationId",
        "orderId",
        "enterpriseId",
        "reason",
        "orderVersion",
        "releaseVersion",
        "result",
        "releasedAt",
        "traceId",
      ],
    ),
    payloadExample: {
      commandId: "cmd_inventory_release_001",
      reservationId: "ires_contract_001",
      orderId: "ord_contract_001",
      enterpriseId: "ent_contract_001",
      reason: "USER_CANCEL",
      orderVersion: 2,
      releaseVersion: 2,
      result: "RELEASED",
      releasedAt: "2026-08-10T02:05:00Z",
      traceId: "trace_contract_fixture_001",
    },
    idempotencyKey: "INVENTORY_RELEASE:{reservationId}:{reason}",
    idempotencyExample: "INVENTORY_RELEASE:ires_contract_001:USER_CANCEL",
    businessUniqueness: "reservationId + legal reason family; COMMITTED and RELEASED are mutually exclusive",
  }),
  defineContract({
    eventType: "ContentProductClicked",
    topic: "commerce.content.product-clicked.v1",
    producer: "SYS-02",
    consumers: ["SYS-04", "SYS-06"],
    aggregate: aggregate("AttributionCandidate", "attributionCandidateId", "atc_contract_001", undefined),
    payloadSchema: record(
      {
        attributionCandidateId: id("atc_"),
        contentId: id("cnt_"),
        channelPublicationId: id("cpub_"),
        productId: id("prd_"),
        promoterEnterpriseId: enterpriseId,
        customerId: nullable(id("cus_")),
        anonymousId: nullable(id("anon_")),
        clickedAt: dateTime(),
      },
      [
        "attributionCandidateId",
        "contentId",
        "channelPublicationId",
        "productId",
        "promoterEnterpriseId",
        "customerId",
        "anonymousId",
        "clickedAt",
      ],
    ),
    payloadExample: {
      attributionCandidateId: "atc_contract_001",
      contentId: "cnt_contract_001",
      channelPublicationId: "cpub_contract_001",
      productId: "prd_contract_001",
      promoterEnterpriseId: "ent_contract_002",
      customerId: null,
      anonymousId: "anon_contract_001",
      clickedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "CONTENT_PRODUCT_CLICK:{attributionCandidateId}",
    idempotencyExample: "CONTENT_PRODUCT_CLICK:atc_contract_001",
    businessUniqueness: "attributionCandidateId; eventId is an independent delivery dedupe key",
    piiPolicy: "Only customer/anonymous safe references; no contact data or device fingerprint.",
  }),
  defineContract({
    eventType: "OrderAttributionFrozen",
    topic: "commerce.order.attribution-frozen.v1",
    producer: "SYS-02",
    consumers: ["SYS-04", "SYS-06", "SYS-08"],
    aggregate: aggregate("OrderAttribution", "attributionId", "atr_contract_001", "version"),
    payloadSchema: record(
      {
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        attributionId: id("atr_"),
        version,
        reviewStatus: enumeration(["PENDING", "APPROVED", "REJECTED"] as const),
        sourceType: string(),
        sellerEnterpriseId: enterpriseId,
        promoterEnterpriseId: nullable(enterpriseId),
        membershipOwnerEnterpriseId: nullable(enterpriseId),
        attributionRuleVersion: version,
        distributionRuleVersionId: nullable(string()),
        distributionContextStatus: enumeration(["RESOLVED", "PENDING_DISTRIBUTION_RULE"] as const),
        distributionContextVersion: nullable(version),
        distributionContextHash: nullable(hash),
        snapshotHash: hash,
        frozenAt: dateTime(),
      },
      [
        "orderId",
        "subOrderId",
        "attributionId",
        "version",
        "reviewStatus",
        "sourceType",
        "sellerEnterpriseId",
        "promoterEnterpriseId",
        "membershipOwnerEnterpriseId",
        "attributionRuleVersion",
        "distributionRuleVersionId",
        "distributionContextStatus",
        "distributionContextVersion",
        "distributionContextHash",
        "snapshotHash",
        "frozenAt",
      ],
    ),
    payloadExample: {
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      attributionId: "atr_contract_001",
      version: 1,
      reviewStatus: "APPROVED",
      sourceType: "CONTENT_CLICK",
      sellerEnterpriseId: "ent_contract_001",
      promoterEnterpriseId: "ent_contract_002",
      membershipOwnerEnterpriseId: "ent_contract_001",
      attributionRuleVersion: 1,
      distributionRuleVersionId: "dru_contract_001",
      distributionContextStatus: "RESOLVED",
      distributionContextVersion: 1,
      distributionContextHash: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      snapshotHash: "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
      frozenAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "ORDER_ATTRIBUTION:{attributionId}:{version}",
    idempotencyExample: "ORDER_ATTRIBUTION:atr_contract_001:1",
    businessUniqueness: "attributionId + version; version 1 is frozen with the order transaction",
    piiPolicy: "No buyer PII, membership percentage or internal identity mapping.",
  }),
  defineContract({
    eventType: "OrderAttributionAdjusted",
    topic: "commerce.order.attribution-adjusted.v1",
    producer: "SYS-02",
    consumers: ["SYS-04", "SYS-06", "SYS-08"],
    aggregate: aggregate("OrderAttribution", "attributionId", "atr_contract_001", "newVersion", 2),
    payloadSchema: record(
      {
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        attributionId: id("atr_"),
        adjustmentId: id("adj_"),
        oldVersion: version,
        newVersion: version,
        oldSellerEnterpriseId: enterpriseId,
        newSellerEnterpriseId: enterpriseId,
        oldPromoterEnterpriseId: nullable(enterpriseId),
        newPromoterEnterpriseId: nullable(enterpriseId),
        oldMembershipOwnerEnterpriseId: nullable(enterpriseId),
        newMembershipOwnerEnterpriseId: nullable(enterpriseId),
        oldDistributionRuleVersionId: nullable(string()),
        newDistributionRuleVersionId: nullable(string()),
        oldDistributionContextStatus: enumeration(["RESOLVED", "PENDING_DISTRIBUTION_RULE"] as const),
        newDistributionContextStatus: enumeration(["RESOLVED", "PENDING_DISTRIBUTION_RULE"] as const),
        oldSnapshotHash: hash,
        newSnapshotHash: hash,
        approvalRef: string(),
        effectiveAt: dateTime(),
      },
      [
        "orderId",
        "subOrderId",
        "attributionId",
        "adjustmentId",
        "oldVersion",
        "newVersion",
        "oldSellerEnterpriseId",
        "newSellerEnterpriseId",
        "oldPromoterEnterpriseId",
        "newPromoterEnterpriseId",
        "oldMembershipOwnerEnterpriseId",
        "newMembershipOwnerEnterpriseId",
        "oldDistributionRuleVersionId",
        "newDistributionRuleVersionId",
        "oldDistributionContextStatus",
        "newDistributionContextStatus",
        "oldSnapshotHash",
        "newSnapshotHash",
        "approvalRef",
        "effectiveAt",
      ],
    ),
    payloadExample: {
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      attributionId: "atr_contract_001",
      adjustmentId: "adj_contract_001",
      oldVersion: 1,
      newVersion: 2,
      oldSellerEnterpriseId: "ent_contract_001",
      newSellerEnterpriseId: "ent_contract_001",
      oldPromoterEnterpriseId: null,
      newPromoterEnterpriseId: "ent_contract_002",
      oldMembershipOwnerEnterpriseId: "ent_contract_001",
      newMembershipOwnerEnterpriseId: "ent_contract_001",
      oldDistributionRuleVersionId: null,
      newDistributionRuleVersionId: "dru_contract_001",
      oldDistributionContextStatus: "PENDING_DISTRIBUTION_RULE",
      newDistributionContextStatus: "RESOLVED",
      oldSnapshotHash: "1111111111111111111111111111111111111111111111111111111111111111",
      newSnapshotHash: "2222222222222222222222222222222222222222222222222222222222222222",
      approvalRef: "approval_contract_001",
      effectiveAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "ORDER_ATTRIBUTION_ADJUST:{adjustmentId}:{newVersion}",
    idempotencyExample: "ORDER_ATTRIBUTION_ADJUST:adj_contract_001:2",
    businessUniqueness: "adjustmentId + newVersion; corrections append and never overwrite",
  }),
  defineContract({
    eventType: "OrderPaid",
    topic: "commerce.order.paid.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-04", "SYS-06", "SYS-08"],
    aggregate: aggregate("Order", "orderId", "ord_contract_001", "orderVersion", 2),
    payloadSchema: record(
      {
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        paymentId: id("pay_"),
        sellerEnterpriseId: enterpriseId,
        storeId: id("store_"),
        salesModel: enumeration(["SELF_OPERATED", "MERCHANT", "SUPPLIER"] as const),
        supplierId: nullable(string()),
        payeeType: enumeration(["PLATFORM", "MERCHANT", "SUPPLIER"] as const),
        attributionId: id("atr_"),
        buyerMatchRef: nullable(string()),
        paidFen: amountFen,
        currency,
        orderVersion: version,
        outcomeVersion: version,
        merchantOrderSnapshotRef: id("mos_"),
        merchantOrderSnapshotVersion: version,
        merchantOrderSnapshotHash: hash,
        analyticsSnapshotRef: id("oas_"),
        analyticsSnapshotVersion: version,
        analyticsSnapshotHash: hash,
        paidAt: dateTime(),
      },
      [
        "orderId",
        "subOrderId",
        "paymentId",
        "sellerEnterpriseId",
        "storeId",
        "salesModel",
        "supplierId",
        "payeeType",
        "attributionId",
        "buyerMatchRef",
        "paidFen",
        "currency",
        "orderVersion",
        "outcomeVersion",
        "merchantOrderSnapshotRef",
        "merchantOrderSnapshotVersion",
        "merchantOrderSnapshotHash",
        "analyticsSnapshotRef",
        "analyticsSnapshotVersion",
        "analyticsSnapshotHash",
        "paidAt",
      ],
    ),
    payloadExample: {
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      paymentId: "pay_contract_001",
      sellerEnterpriseId: "ent_contract_001",
      storeId: "store_contract_001",
      salesModel: "MERCHANT",
      supplierId: null,
      payeeType: "MERCHANT",
      attributionId: "atr_contract_001",
      buyerMatchRef: "buyer_match_contract_001",
      paidFen: 12900,
      currency: "CNY",
      orderVersion: 2,
      outcomeVersion: 1,
      merchantOrderSnapshotRef: "mos_contract_001",
      merchantOrderSnapshotVersion: 1,
      merchantOrderSnapshotHash: "3333333333333333333333333333333333333333333333333333333333333333",
      analyticsSnapshotRef: "oas_contract_001",
      analyticsSnapshotVersion: 1,
      analyticsSnapshotHash: "4444444444444444444444444444444444444444444444444444444444444444",
      paidAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "PAYMENT_SUCCESS:{paymentId}:{channelTransactionId}",
    idempotencyExample: "PAYMENT_SUCCESS:pay_contract_001:txn_contract_001",
    businessUniqueness: "paymentId + outcomeVersion; payment channel transaction is independently unique",
    piiPolicy: "No buyer userId, phone, address or payment credentials; snapshots are access-controlled refs.",
  }),
  defineContract({
    eventType: "OrderCancelled",
    topic: "commerce.order.cancelled.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06"],
    aggregate: aggregate("Order", "orderId", "ord_contract_001", "orderVersion", 2),
    payloadSchema: record(
      {
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        sellerEnterpriseId: enterpriseId,
        orderVersion: version,
        reason: string(),
        paymentStatus: enumeration(["UNPAID", "CLOSED"] as const),
        cancelledAt: dateTime(),
      },
      ["orderId", "subOrderId", "sellerEnterpriseId", "orderVersion", "reason", "paymentStatus", "cancelledAt"],
    ),
    payloadExample: {
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      sellerEnterpriseId: "ent_contract_001",
      orderVersion: 2,
      reason: "BUYER_CANCELLED",
      paymentStatus: "UNPAID",
      cancelledAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "ORDER_CANCEL:{orderId}",
    idempotencyExample: "ORDER_CANCEL:ord_contract_001",
    businessUniqueness: "orderId + CANCEL action",
    notes: "This drives a release command but never substitutes for InventoryReservationReleased.",
  }),
  defineContract({
    eventType: "OrderShipmentRegistered",
    topic: "commerce.order.shipment-registered.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06"],
    aggregate: aggregate("Order", "orderId", "ord_contract_001", "orderVersion", 3),
    payloadSchema: record(
      {
        commandId: id("cmd_"),
        fulfillmentId: id("ful_"),
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        sellerEnterpriseId: enterpriseId,
        storeId: id("store_"),
        carrierCode: string(),
        trackingNoMasked: string(),
        shippedAt: dateTime(),
        fulfillmentVersion: version,
        orderVersion: version,
        registeredAt: dateTime(),
      },
      [
        "commandId",
        "fulfillmentId",
        "orderId",
        "subOrderId",
        "sellerEnterpriseId",
        "storeId",
        "carrierCode",
        "trackingNoMasked",
        "shippedAt",
        "fulfillmentVersion",
        "orderVersion",
        "registeredAt",
      ],
    ),
    payloadExample: {
      commandId: "cmd_shipment_register_001",
      fulfillmentId: "ful_contract_001",
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      sellerEnterpriseId: "ent_contract_001",
      storeId: "store_contract_001",
      carrierCode: "SF",
      trackingNoMasked: "SF****1234",
      shippedAt: "2026-08-10T02:00:00Z",
      fulfillmentVersion: 1,
      orderVersion: 3,
      registeredAt: "2026-08-10T02:00:01Z",
    },
    idempotencyKey: "SHIPMENT_REGISTER:{fulfillmentId}:{fulfillmentVersion}",
    idempotencyExample: "SHIPMENT_REGISTER:ful_contract_001:1",
    businessUniqueness: "fulfillmentId + fulfillmentVersion; one first shipment for a P0 subOrderId",
    piiPolicy: "Only a masked tracking number; the complete tracking number remains encrypted in SYS-03.",
  }),
  defineContract({
    eventType: "OrderReceived",
    topic: "commerce.order.received.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06", "SYS-08"],
    aggregate: aggregate("Order", "orderId", "ord_contract_001", "orderVersion", 4),
    payloadSchema: record(
      {
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        sellerEnterpriseId: enterpriseId,
        orderVersion: version,
        source: enumeration(["BUYER_CONFIRMED", "AUTO_CONFIRMED"] as const),
        receivedAt: dateTime(),
      },
      ["orderId", "subOrderId", "sellerEnterpriseId", "orderVersion", "source", "receivedAt"],
    ),
    payloadExample: {
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      sellerEnterpriseId: "ent_contract_001",
      orderVersion: 4,
      source: "BUYER_CONFIRMED",
      receivedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "ORDER_RECEIVED:{orderId}",
    idempotencyExample: "ORDER_RECEIVED:ord_contract_001",
    businessUniqueness: "orderId + CONFIRM_RECEIPT action",
    notes: "Starts the aftersale observation period; it is not settlement eligibility.",
  }),
  defineContract({
    eventType: "OrderSettlementEligible",
    topic: "commerce.order.settlement-eligible.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06", "SYS-08"],
    aggregate: aggregate("SubOrder", "subOrderId", "subord_contract_001", "eligibilityVersion"),
    payloadSchema: record(
      {
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        sellerEnterpriseId: enterpriseId,
        eligibilityVersion: version,
        eligibleAt: dateTime(),
        eligibilitySnapshotRef: id("els_"),
        eligibilitySnapshotHash: hash,
        aftersaleWindowRuleVersion: version,
      },
      [
        "orderId",
        "subOrderId",
        "sellerEnterpriseId",
        "eligibilityVersion",
        "eligibleAt",
        "eligibilitySnapshotRef",
        "eligibilitySnapshotHash",
        "aftersaleWindowRuleVersion",
      ],
    ),
    payloadExample: {
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      sellerEnterpriseId: "ent_contract_001",
      eligibilityVersion: 1,
      eligibleAt: "2026-08-17T02:00:00Z",
      eligibilitySnapshotRef: "els_contract_001",
      eligibilitySnapshotHash: "5555555555555555555555555555555555555555555555555555555555555555",
      aftersaleWindowRuleVersion: 1,
    },
    idempotencyKey: "ORDER_SETTLEMENT_ELIGIBLE:{subOrderId}:{eligibilityVersion}",
    idempotencyExample: "ORDER_SETTLEMENT_ELIGIBLE:subord_contract_001:1",
    businessUniqueness: "subOrderId + eligibilityVersion; source snapshot is immutable",
  }),
  defineContract({
    eventType: "AftersaleStatusChanged",
    topic: "commerce.aftersale.status-changed.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06", "SYS-08"],
    aggregate: aggregate("Aftersale", "aftersaleId", "afs_contract_001", "version", 2),
    payloadSchema: record(
      {
        aftersaleId: id("afs_"),
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        enterpriseId,
        status: string(),
        responsibleParty: enumeration(["BUYER", "MERCHANT", "PLATFORM", "SUPPLIER"] as const),
        approvedFen: amountFen,
        version,
        decisionVersion: version,
        approvalRef: nullable(string()),
        changedAt: dateTime(),
      },
      [
        "aftersaleId",
        "orderId",
        "subOrderId",
        "enterpriseId",
        "status",
        "responsibleParty",
        "approvedFen",
        "version",
        "decisionVersion",
        "approvalRef",
        "changedAt",
      ],
    ),
    payloadExample: {
      aftersaleId: "afs_contract_001",
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      enterpriseId: "ent_contract_001",
      status: "APPROVED",
      responsibleParty: "MERCHANT",
      approvedFen: 2900,
      version: 2,
      decisionVersion: 1,
      approvalRef: "approval_contract_002",
      changedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "AFTERSALE_STATUS:{aftersaleId}:{version}",
    idempotencyExample: "AFTERSALE_STATUS:afs_contract_001:2",
    businessUniqueness: "aftersaleId + version",
  }),
  defineContract({
    eventType: "RefundRequested",
    topic: "commerce.refund.requested.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06", "SYS-08"],
    aggregate: aggregate("Refund", "refundId", "rfd_contract_001", "requestVersion"),
    payloadSchema: record(
      {
        refundId: id("rfd_"),
        aftersaleId: id("afs_"),
        orderId: id("ord_"),
        enterpriseId,
        paymentId: id("pay_"),
        amountFen,
        requestVersion: version,
        approvalRef: nullable(string()),
        requestedAt: dateTime(),
      },
      ["refundId", "aftersaleId", "orderId", "enterpriseId", "paymentId", "amountFen", "requestVersion", "approvalRef", "requestedAt"],
    ),
    payloadExample: {
      refundId: "rfd_contract_001",
      aftersaleId: "afs_contract_001",
      orderId: "ord_contract_001",
      enterpriseId: "ent_contract_001",
      paymentId: "pay_contract_001",
      amountFen: 2900,
      requestVersion: 1,
      approvalRef: "approval_contract_002",
      requestedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "REFUND_REQUEST:{refundId}:{requestVersion}",
    idempotencyExample: "REFUND_REQUEST:rfd_contract_001:1",
    businessUniqueness: "refundId + requestVersion",
    notes: "Requested never means that a channel refund succeeded.",
  }),
  defineContract({
    eventType: "RefundStatusChanged",
    topic: "commerce.refund.status-changed.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06", "SYS-08"],
    aggregate: aggregate("Refund", "refundId", "rfd_contract_001", "version", 2),
    payloadSchema: record(
      {
        refundId: id("rfd_"),
        aftersaleId: id("afs_"),
        orderId: id("ord_"),
        enterpriseId,
        status: enumeration(["REQUESTED", "PROCESSING", "SUCCEEDED", "FAILED"] as const),
        amountFen,
        channelRefundRef: nullable(string("Masked channel refund reference")),
        version,
        changedAt: dateTime(),
        failureCode: nullable(string()),
      },
      [
        "refundId",
        "aftersaleId",
        "orderId",
        "enterpriseId",
        "status",
        "amountFen",
        "channelRefundRef",
        "version",
        "changedAt",
        "failureCode",
      ],
    ),
    payloadExample: {
      refundId: "rfd_contract_001",
      aftersaleId: "afs_contract_001",
      orderId: "ord_contract_001",
      enterpriseId: "ent_contract_001",
      status: "SUCCEEDED",
      amountFen: 2900,
      channelRefundRef: "wx_refund_****001",
      version: 2,
      changedAt: "2026-08-10T02:02:00Z",
      failureCode: null,
    },
    idempotencyKey: "REFUND_STATUS:{refundId}:{version}",
    idempotencyExample: "REFUND_STATUS:rfd_contract_001:2",
    businessUniqueness: "refundId + version",
    piiPolicy: "Only a masked channel reference; no payment credential or raw callback.",
  }),
  defineContract({
    eventType: "OrderRefunded",
    topic: "commerce.order.refunded.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-04", "SYS-06", "SYS-08"],
    aggregate: aggregate("Order", "orderId", "ord_contract_001", "orderVersion", 5),
    payloadSchema: record(
      {
        orderId: id("ord_"),
        subOrderId: id("subord_"),
        refundId: id("rfd_"),
        sellerEnterpriseId: enterpriseId,
        storeId: id("store_"),
        attributionId: id("atr_"),
        buyerMatchRef: nullable(string()),
        refundedFen: amountFen,
        cumulativeRefundedFen: amountFen,
        currency,
        orderVersion: version,
        outcomeVersion: version,
        analyticsSnapshotRef: id("oas_"),
        analyticsSnapshotVersion: version,
        analyticsSnapshotHash: hash,
        completedAt: dateTime(),
      },
      [
        "orderId",
        "subOrderId",
        "refundId",
        "sellerEnterpriseId",
        "storeId",
        "attributionId",
        "buyerMatchRef",
        "refundedFen",
        "cumulativeRefundedFen",
        "currency",
        "orderVersion",
        "outcomeVersion",
        "analyticsSnapshotRef",
        "analyticsSnapshotVersion",
        "analyticsSnapshotHash",
        "completedAt",
      ],
    ),
    payloadExample: {
      orderId: "ord_contract_001",
      subOrderId: "subord_contract_001",
      refundId: "rfd_contract_001",
      sellerEnterpriseId: "ent_contract_001",
      storeId: "store_contract_001",
      attributionId: "atr_contract_001",
      buyerMatchRef: "buyer_match_contract_001",
      refundedFen: 2900,
      cumulativeRefundedFen: 2900,
      currency: "CNY",
      orderVersion: 5,
      outcomeVersion: 2,
      analyticsSnapshotRef: "oas_contract_002",
      analyticsSnapshotVersion: 2,
      analyticsSnapshotHash: "6666666666666666666666666666666666666666666666666666666666666666",
      completedAt: "2026-08-10T02:02:00Z",
    },
    idempotencyKey: "REFUND_RESULT:{refundId}:{channelRefundTransactionId}",
    idempotencyExample: "REFUND_RESULT:rfd_contract_001:rtxn_contract_001",
    businessUniqueness: "refundId + outcomeVersion; cumulative amount cannot exceed original paid amount",
    piiPolicy: "No buyer PII; analytics detail is retrieved by immutable access-controlled snapshot ref.",
  }),
  defineContract({
    eventType: "ReviewReplyChanged",
    topic: "commerce.review.reply-changed.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06"],
    aggregate: aggregate("Review", "reviewId", "rev_contract_001", "replyVersion"),
    payloadSchema: record(
      {
        reviewId: id("rev_"),
        enterpriseId,
        storeId: id("store_"),
        replyVersion: version,
        publicReply: string("Moderated public reply"),
        status: enumeration(["PUBLIC", "HIDDEN"] as const),
        changedAt: dateTime(),
      },
      ["reviewId", "enterpriseId", "storeId", "replyVersion", "publicReply", "status", "changedAt"],
    ),
    payloadExample: {
      reviewId: "rev_contract_001",
      enterpriseId: "ent_contract_001",
      storeId: "store_contract_001",
      replyVersion: 1,
      publicReply: "感谢反馈，我们会持续改进。",
      status: "PUBLIC",
      changedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "REVIEW_REPLY:{reviewId}:{replyVersion}",
    idempotencyExample: "REVIEW_REPLY:rev_contract_001:1",
    businessUniqueness: "reviewId + replyVersion; old replies remain immutable",
  }),
  defineContract({
    eventType: "ReviewGovernanceChanged",
    topic: "commerce.review.governance-changed.v1",
    producer: "SYS-02",
    consumers: ["SYS-03", "SYS-06"],
    aggregate: aggregate("Review", "reviewId", "rev_contract_001", "governanceVersion", 2),
    payloadSchema: record(
      {
        reviewId: id("rev_"),
        enterpriseId,
        governanceVersion: version,
        publicStatus: enumeration(["PUBLIC", "HIDDEN", "RESTORED"] as const),
        publicReasonCode: string(),
        appealStatus: enumeration(["NONE", "PENDING", "APPROVED", "REJECTED"] as const),
        approvalRef: nullable(string()),
        changedAt: dateTime(),
      },
      [
        "reviewId",
        "enterpriseId",
        "governanceVersion",
        "publicStatus",
        "publicReasonCode",
        "appealStatus",
        "approvalRef",
        "changedAt",
      ],
    ),
    payloadExample: {
      reviewId: "rev_contract_001",
      enterpriseId: "ent_contract_001",
      governanceVersion: 2,
      publicStatus: "RESTORED",
      publicReasonCode: "APPEAL_APPROVED",
      appealStatus: "APPROVED",
      approvalRef: "approval_contract_003",
      changedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "REVIEW_GOVERNANCE:{reviewId}:{governanceVersion}",
    idempotencyExample: "REVIEW_GOVERNANCE:rev_contract_001:2",
    businessUniqueness: "reviewId + governanceVersion",
    piiPolicy: "Only public moderation reason; internal evidence and reasons remain in SYS-02.",
  }),
] as const;

const CRM_EVENT_CONTRACTS = [
  defineContract({
    eventType: "LeadCreated",
    topic: "crm.lead.created.v1",
    producer: "SYS-04",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("Lead", "leadId", "lead_contract_001", "leadVersion"),
    payloadSchema: record(
      {
        leadId: id("lead_"), enterpriseId, sourceRecordId: string(), sourceType: string(), status: string(),
        customerId: nullable(id("cus_")),
        validityStatus: enumeration(["VALID", "INVALID", "PENDING_AUTHORIZATION"] as const),
        authorizationStatus: string(), globalRefusalStatus: string(), leadVersion: version,
        analyticsSnapshotRef: id("mas_"), analyticsSnapshotVersion: version, analyticsSnapshotHash: hash,
        createdAt: dateTime(),
      },
      ["leadId", "enterpriseId", "sourceRecordId", "sourceType", "status", "customerId", "validityStatus", "authorizationStatus", "globalRefusalStatus", "leadVersion", "analyticsSnapshotRef", "analyticsSnapshotVersion", "analyticsSnapshotHash", "createdAt"],
    ),
    payloadExample: {
      leadId: "lead_contract_001", enterpriseId: "ent_contract_001", sourceRecordId: "src_contract_001",
      sourceType: "MANUAL_IMPORT", status: "NEW", customerId: null, validityStatus: "VALID",
      authorizationStatus: "AUTHORIZED", globalRefusalStatus: "NONE", leadVersion: 1,
      analyticsSnapshotRef: "mas_contract_lead_001", analyticsSnapshotVersion: 1,
      analyticsSnapshotHash: "7777777777777777777777777777777777777777777777777777777777777777",
      createdAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "CRM_LEAD:{leadId}:{leadVersion}", idempotencyExample: "CRM_LEAD:lead_contract_001:1",
    businessUniqueness: "leadId + leadVersion; source create key is independently unique",
    piiPolicy: "No name, company, phone, contact detail or authorization evidence body.",
  }),
  defineContract({
    eventType: "LeadStatusChanged",
    topic: "crm.lead.status_changed.v1",
    producer: "SYS-04",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("Lead", "leadId", "lead_contract_001", "leadVersion", 2),
    payloadSchema: record(
      {
        leadId: id("lead_"), enterpriseId, customerId: nullable(id("cus_")), oldStatus: string(), newStatus: string(),
        validityStatus: enumeration(["VALID", "INVALID", "PENDING_AUTHORIZATION"] as const),
        authorizationStatus: string(), globalRefusalStatus: string(), reasonCode: string(), leadVersion: version,
        analyticsSnapshotRef: id("mas_"), analyticsSnapshotVersion: version, analyticsSnapshotHash: hash,
        changedAt: dateTime(),
      },
      ["leadId", "enterpriseId", "customerId", "oldStatus", "newStatus", "validityStatus", "authorizationStatus", "globalRefusalStatus", "reasonCode", "leadVersion", "analyticsSnapshotRef", "analyticsSnapshotVersion", "analyticsSnapshotHash", "changedAt"],
    ),
    payloadExample: {
      leadId: "lead_contract_001", enterpriseId: "ent_contract_001", customerId: "cus_contract_001",
      oldStatus: "NEW", newStatus: "QUALIFIED", validityStatus: "VALID", authorizationStatus: "AUTHORIZED",
      globalRefusalStatus: "NONE", reasonCode: "HUMAN_QUALIFIED", leadVersion: 2,
      analyticsSnapshotRef: "mas_contract_lead_002", analyticsSnapshotVersion: 2,
      analyticsSnapshotHash: "8888888888888888888888888888888888888888888888888888888888888888",
      changedAt: "2026-08-10T02:05:00Z",
    },
    idempotencyKey: "CRM_LEAD_STATUS:{leadId}:{leadVersion}", idempotencyExample: "CRM_LEAD_STATUS:lead_contract_001:2",
    businessUniqueness: "leadId + leadVersion", piiPolicy: "No contact fields or evidence bodies.",
  }),
  defineContract({
    eventType: "CustomerUpdated",
    topic: "crm.customer.updated.v1",
    producer: "SYS-04",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("Customer", "customerId", "cus_contract_001", "customerVersion", 3),
    payloadSchema: record(
      {
        customerId: id("cus_"), enterpriseId, mainStage: string(), globalRefusalStatus: string(),
        ownerId: nullable(id("usr_")), customerVersion: version,
        analyticsSnapshotRef: id("mas_"), analyticsSnapshotVersion: version, analyticsSnapshotHash: hash,
        updatedAt: dateTime(),
      },
      ["customerId", "enterpriseId", "mainStage", "globalRefusalStatus", "ownerId", "customerVersion", "analyticsSnapshotRef", "analyticsSnapshotVersion", "analyticsSnapshotHash", "updatedAt"],
    ),
    payloadExample: {
      customerId: "cus_contract_001", enterpriseId: "ent_contract_001", mainStage: "OPPORTUNITY",
      globalRefusalStatus: "NONE", ownerId: "usr_contract_002", customerVersion: 3,
      analyticsSnapshotRef: "mas_contract_customer_003", analyticsSnapshotVersion: 3,
      analyticsSnapshotHash: "9999999999999999999999999999999999999999999999999999999999999999",
      updatedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "CRM_CUSTOMER:{customerId}:{customerVersion}", idempotencyExample: "CRM_CUSTOMER:cus_contract_001:3",
    businessUniqueness: "customerId + customerVersion", piiPolicy: "No name, company, tags, phone or contact identifiers.",
  }),
  defineContract({
    eventType: "CustomerAssigned",
    topic: "crm.customer.assigned.v1",
    producer: "SYS-04",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("Customer", "customerId", "cus_contract_001", "assignmentVersion", 2),
    payloadSchema: record(
      { customerId: id("cus_"), enterpriseId, assigneeUserId: id("usr_"), assignmentMode: string(), ruleVersion: version, assignmentVersion: version, assignedAt: dateTime() },
      ["customerId", "enterpriseId", "assigneeUserId", "assignmentMode", "ruleVersion", "assignmentVersion", "assignedAt"],
    ),
    payloadExample: { customerId: "cus_contract_001", enterpriseId: "ent_contract_001", assigneeUserId: "usr_contract_002", assignmentMode: "RULE", ruleVersion: 1, assignmentVersion: 2, assignedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "CRM_CUSTOMER_ASSIGN:{customerId}:{assignmentVersion}", idempotencyExample: "CRM_CUSTOMER_ASSIGN:cus_contract_001:2",
    businessUniqueness: "one active owner per customer; customerId + assignmentVersion",
  }),
  defineContract({
    eventType: "OpportunityStageChanged",
    topic: "crm.opportunity.stage-changed.v1",
    producer: "SYS-04",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("Opportunity", "opportunityId", "opp_contract_001", "opportunityVersion", 2),
    payloadSchema: record(
      { opportunityId: id("opp_"), enterpriseId, customerId: id("cus_"), oldStage: string(), newStage: string(), opportunityVersion: version, reasonCode: string(), changedAt: dateTime() },
      ["opportunityId", "enterpriseId", "customerId", "oldStage", "newStage", "opportunityVersion", "reasonCode", "changedAt"],
    ),
    payloadExample: { opportunityId: "opp_contract_001", enterpriseId: "ent_contract_001", customerId: "cus_contract_001", oldStage: "QUALIFIED", newStage: "QUOTED", opportunityVersion: 2, reasonCode: "QUOTE_CONFIRMED", changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "CRM_OPPORTUNITY_STAGE:{opportunityId}:{opportunityVersion}", idempotencyExample: "CRM_OPPORTUNITY_STAGE:opp_contract_001:2",
    businessUniqueness: "opportunityId + opportunityVersion",
  }),
  defineContract({
    eventType: "CallCompleted",
    topic: "crm.call.completed.v1",
    producer: "SYS-04",
    consumers: ["SYS-06"],
    aggregate: aggregate("Call", "callId", "call_contract_001", "resultVersion"),
    payloadSchema: record(
      {
        callId: id("call_"), callTaskId: id("ctask_"), callCampaignId: id("ccmp_"), enterpriseId,
        customerId: id("cus_"), resultVersion: version, status: enumeration(["COMPLETED"] as const), connected: boolean,
        durationSeconds: integer(), intentLevel: string(), humanFollowupRequired: boolean,
        isRealAiCall: { type: "boolean", const: true }, analyticsSnapshotRef: id("mas_"),
        analyticsSnapshotVersion: version, analyticsSnapshotHash: hash, completedAt: dateTime(),
      },
      ["callId", "callTaskId", "callCampaignId", "enterpriseId", "customerId", "resultVersion", "status", "connected", "durationSeconds", "intentLevel", "humanFollowupRequired", "isRealAiCall", "analyticsSnapshotRef", "analyticsSnapshotVersion", "analyticsSnapshotHash", "completedAt"],
    ),
    payloadExample: {
      callId: "call_contract_001", callTaskId: "ctask_contract_001", callCampaignId: "ccmp_contract_001",
      enterpriseId: "ent_contract_001", customerId: "cus_contract_001", resultVersion: 1, status: "COMPLETED",
      connected: true, durationSeconds: 92, intentLevel: "HIGH", humanFollowupRequired: true, isRealAiCall: true,
      analyticsSnapshotRef: "mas_contract_call_001", analyticsSnapshotVersion: 1,
      analyticsSnapshotHash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      completedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "AI_CALL_RESULT:{providerAccountId}:{callId}:{resultVersion}", idempotencyExample: "AI_CALL_RESULT:provider_account_contract_001:call_contract_001:1",
    businessUniqueness: "trusted providerAccountId + callId + resultVersion",
    piiPolicy: "No recording, transcript, summary, phone or provider credential; analytics uses an immutable safe snapshot.",
  }),
  defineContract({
    eventType: "WeChatHandoffRequested",
    topic: "crm.wechat.handoff-requested.v1",
    producer: "SYS-04",
    consumers: ["SYS-06"],
    aggregate: aggregate("WeChatHandoff", "handoffRef", "whf_contract_001", "handoffVersion"),
    payloadSchema: record(
      {
        handoffRef: id("whf_"), conversationId: id("conv_"), enterpriseId, customerId: nullable(id("cus_")),
        reasonCode: string(), status: enumeration(["REQUESTED"] as const), handoffVersion: version,
        analyticsSnapshotRef: id("mas_"), analyticsSnapshotVersion: version, analyticsSnapshotHash: hash,
        requestedAt: dateTime(),
      },
      ["handoffRef", "conversationId", "enterpriseId", "customerId", "reasonCode", "status", "handoffVersion", "analyticsSnapshotRef", "analyticsSnapshotVersion", "analyticsSnapshotHash", "requestedAt"],
    ),
    payloadExample: {
      handoffRef: "whf_contract_001", conversationId: "conv_contract_001", enterpriseId: "ent_contract_001",
      customerId: "cus_contract_001", reasonCode: "CUSTOMER_REQUESTED_HUMAN", status: "REQUESTED", handoffVersion: 1,
      analyticsSnapshotRef: "mas_contract_handoff_001", analyticsSnapshotVersion: 1,
      analyticsSnapshotHash: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      requestedAt: "2026-08-10T02:00:00Z",
    },
    idempotencyKey: "WECHAT_HANDOFF:{handoffRef}:{handoffVersion}", idempotencyExample: "WECHAT_HANDOFF:whf_contract_001:1",
    businessUniqueness: "handoffRef + handoffVersion; one active handoff task per conversation",
    piiPolicy: "No messageId, external WeChat ID, message body or conversation body.",
  }),
  defineContract({
    eventType: "GlobalMarketingRefusalChanged",
    topic: "crm.marketing.global-refusal-changed.v1",
    producer: "SYS-04",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("Customer", "customerId", "cus_contract_001", "refusalVersion", 2),
    payloadSchema: record(
      { customerId: id("cus_"), enterpriseId, status: enumeration(["ACTIVE", "RELEASED"] as const), reasonCode: string(), refusalVersion: version, approvalRef: nullable(string()), changedAt: dateTime() },
      ["customerId", "enterpriseId", "status", "reasonCode", "refusalVersion", "approvalRef", "changedAt"],
    ),
    payloadExample: { customerId: "cus_contract_001", enterpriseId: "ent_contract_001", status: "RELEASED", reasonCode: "NEW_CONSENT_VERIFIED", refusalVersion: 2, approvalRef: "approval_contract_004", changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "CRM_GLOBAL_REFUSAL:{customerId}:{refusalVersion}", idempotencyExample: "CRM_GLOBAL_REFUSAL:cus_contract_001:2",
    businessUniqueness: "customerId + refusalVersion",
  }),
  defineContract({
    eventType: "ContactSuppressionChanged",
    topic: "crm.marketing.contact-suppression-changed.v1",
    producer: "SYS-04",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("ContactSuppression", "suppressionId", "sup_contract_001", "suppressionVersion", 2),
    payloadSchema: record(
      { suppressionId: id("sup_"), customerId: id("cus_"), enterpriseId, channelScope: string(), status: enumeration(["ACTIVE", "RELEASED"] as const), reasonCode: string(), suppressionVersion: version, changedAt: dateTime() },
      ["suppressionId", "customerId", "enterpriseId", "channelScope", "status", "reasonCode", "suppressionVersion", "changedAt"],
    ),
    payloadExample: { suppressionId: "sup_contract_001", customerId: "cus_contract_001", enterpriseId: "ent_contract_001", channelScope: "WECHAT", status: "RELEASED", reasonCode: "NEW_CONSENT_VERIFIED", suppressionVersion: 2, changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "CRM_CONTACT_SUPPRESSION:{suppressionId}:{suppressionVersion}", idempotencyExample: "CRM_CONTACT_SUPPRESSION:sup_contract_001:2",
    businessUniqueness: "suppressionId + suppressionVersion; channel suppression does not change the CRM main stage",
  }),
] as const;

const PUBLICATION_OPC_EVENT_CONTRACTS = [
  defineContract({
    eventType: "ContentVersionSubmitted", topic: "content.version.submitted.v1", producer: "SYS-05",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("ContentChannelVersion", "channelVersionId", "cver_contract_001", "contentVersion", 2),
    payloadSchema: record(
      { contentId: id("cnt_"), channelVersionId: id("cver_"), enterpriseId, channel: enumeration(["WOTAO", "DOUYIN"] as const), contentVersion: version, submissionId: id("csub_"), snapshotHash: hash, submittedBy: id("usr_"), submittedAt: dateTime() },
      ["contentId", "channelVersionId", "enterpriseId", "channel", "contentVersion", "submissionId", "snapshotHash", "submittedBy", "submittedAt"],
    ),
    payloadExample: { contentId: "cnt_contract_001", channelVersionId: "cver_contract_001", enterpriseId: "ent_contract_001", channel: "DOUYIN", contentVersion: 2, submissionId: "csub_contract_001", snapshotHash: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", submittedBy: "usr_contract_001", submittedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "CONTENT_SUBMIT:{channelVersionId}:{contentVersion}", idempotencyExample: "CONTENT_SUBMIT:cver_contract_001:2",
    businessUniqueness: "channelVersionId + contentVersion; submitted snapshot is immutable", piiPolicy: "No full media or evidence body; only safe references and hash.",
  }),
  defineContract({
    eventType: "ContentReviewCompleted", topic: "content.review.completed.v1", producer: "REVIEW_CENTER",
    consumers: ["SYS-05", "SYS-06"],
    aggregate: aggregate("ContentReview", "reviewId", "crev_contract_001", "decisionVersion"),
    payloadSchema: record(
      { reviewId: id("crev_"), contentId: id("cnt_"), channelVersionId: id("cver_"), enterpriseId, contentVersion: version, decision: enumeration(["APPROVED", "REJECTED"] as const), decisionVersion: version, reasonCodes: array(string()), evidenceHash: hash, completedAt: dateTime() },
      ["reviewId", "contentId", "channelVersionId", "enterpriseId", "contentVersion", "decision", "decisionVersion", "reasonCodes", "evidenceHash", "completedAt"],
    ),
    payloadExample: { reviewId: "crev_contract_001", contentId: "cnt_contract_001", channelVersionId: "cver_contract_001", enterpriseId: "ent_contract_001", contentVersion: 2, decision: "APPROVED", decisionVersion: 1, reasonCodes: [], evidenceHash: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", completedAt: "2026-08-10T02:05:00Z" },
    idempotencyKey: "CONTENT_REVIEW:{reviewId}:{decisionVersion}", idempotencyExample: "CONTENT_REVIEW:crev_contract_001:1",
    businessUniqueness: "reviewId + decisionVersion; one decision per submitted content version",
  }),
  defineContract({
    eventType: "PublicationConfirmed", topic: "publication.confirmed.v1", producer: "SYS-05",
    consumers: ["SYS-01", "SYS-06", "SYS-08"],
    aggregate: aggregate("PublicationPlan", "publicationPlanId", "pplan_contract_001", "planVersion"),
    payloadSchema: record(
      { confirmationId: id("pcfm_"), publicationPlanId: id("pplan_"), enterpriseId, planVersion: version, channelPublications: array(record({ channelPublicationId: id("cpub_"), channel: enumeration(["WOTAO", "DOUYIN"] as const), contentVersionId: id("cver_") }, ["channelPublicationId", "channel", "contentVersionId"]), 2), confirmedBy: id("usr_"), confirmationRef: string(), confirmedAt: dateTime() },
      ["confirmationId", "publicationPlanId", "enterpriseId", "planVersion", "channelPublications", "confirmedBy", "confirmationRef", "confirmedAt"],
    ),
    payloadExample: { confirmationId: "pcfm_contract_001", publicationPlanId: "pplan_contract_001", enterpriseId: "ent_contract_001", planVersion: 1, channelPublications: [{ channelPublicationId: "cpub_wotao_contract_001", channel: "WOTAO", contentVersionId: "cver_wotao_contract_001" }, { channelPublicationId: "cpub_contract_001", channel: "DOUYIN", contentVersionId: "cver_contract_001" }], confirmedBy: "usr_contract_001", confirmationRef: "confirmation_contract_001", confirmedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "PUBLICATION_CONFIRM:{confirmationId}", idempotencyExample: "PUBLICATION_CONFIRM:pcfm_contract_001",
    businessUniqueness: "confirmationId maps to at most one active publicationPlanId; plan + channel is unique",
  }),
  defineContract({
    eventType: "PublicationServiceOrderChanged", topic: "ledger.publication-service-order.changed.v1", producer: "SYS-08",
    consumers: ["SYS-01", "SYS-05"],
    aggregate: aggregate("PublicationServiceOrder", "serviceOrderId", "pso_contract_001", "sourceVersion", 2),
    payloadSchema: record(
      { serviceOrderId: id("pso_"), enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), paymentId: nullable(id("pay_")), priceFen: amountFen, status: enumeration(["PENDING_PAYMENT", "PAID", "RESERVED", "COMMITTED", "REFUNDING", "REFUNDED", "CLOSED"] as const), sourceVersion, changedAt: dateTime() },
      ["serviceOrderId", "enterpriseId", "publicationPlanId", "channelPublicationId", "paymentId", "priceFen", "status", "sourceVersion", "changedAt"],
    ),
    payloadExample: { serviceOrderId: "pso_contract_001", enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", paymentId: "pay_service_contract_001", priceFen: 500, status: "PAID", sourceVersion: 2, changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "PUBLICATION_SERVICE_ORDER:{channelPublicationId}:{sourceVersion}", idempotencyExample: "PUBLICATION_SERVICE_ORDER:cpub_contract_001:2",
    businessUniqueness: "one serviceOrderId per channelPublicationId; sourceVersion is monotonic",
    notes: "PAID does not authorize execution; SYS-05 must receive the matching ChannelPublicationReserved.",
  }),
  defineContract({
    eventType: "ChannelPublicationReserved", topic: "ledger.publication.charge-reserved.v1", producer: "SYS-08",
    consumers: ["SYS-05", "SYS-06"],
    aggregate: aggregate("PublicationChargeReservation", "chargeReservationId", "pcr_contract_001", "sourceVersion"),
    payloadSchema: record(
      { chargeReservationId: id("pcr_"), enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), channel: enumeration(["DOUYIN"] as const), sourceType: enumeration(["BENEFIT_QUOTA", "PUBLICATION_SERVICE_ORDER", "AUTHORIZED_BALANCE"] as const), quotaBatchId: nullable(string()), serviceOrderId: nullable(id("pso_")), paymentId: nullable(id("pay_")), authorizedBalanceRef: nullable(string()), sourceVersion, expiresAt: dateTime(), reservedAt: dateTime() },
      ["chargeReservationId", "enterpriseId", "publicationPlanId", "channelPublicationId", "channel", "sourceType", "quotaBatchId", "serviceOrderId", "paymentId", "authorizedBalanceRef", "sourceVersion", "expiresAt", "reservedAt"],
    ),
    payloadExample: { chargeReservationId: "pcr_contract_001", enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", channel: "DOUYIN", sourceType: "PUBLICATION_SERVICE_ORDER", quotaBatchId: null, serviceOrderId: "pso_contract_001", paymentId: "pay_service_contract_001", authorizedBalanceRef: null, sourceVersion: 1, expiresAt: "2026-08-10T03:00:00Z", reservedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "PUBLICATION_CHARGE:{channelPublicationId}", idempotencyExample: "PUBLICATION_CHARGE:cpub_contract_001",
    businessUniqueness: "one active chargeReservationId per channelPublicationId",
    notes: "PUBLICATION_CHARGE is the frozen API/event business key; legacy PUB_CHARGE_RESERVE is not accepted.",
  }),
  defineContract({
    eventType: "ChannelPublicationFirstVisible", topic: "publication.channel.first_visible.v1", producer: "SYS-05",
    consumers: ["SYS-06", "SYS-07", "SYS-08"],
    aggregate: aggregate("ChannelPublication", "channelPublicationId", "cpub_contract_001", "sourceVersion", 3),
    payloadSchema: record(
      { enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), executionId: id("exec_"), channel: enumeration(["WOTAO", "DOUYIN"] as const), externalWorkRef: string(), douyinExecutionMode: nullable(enumeration(["SELF_ACCOUNT", "PLATFORM_OPERATED", "OPC_RENTED"] as const)), accountOwnershipType: nullable(enumeration(["ENTERPRISE_OWNED", "PLATFORM_OWNED", "OPC_RENTED"] as const)), accountAssignmentId: nullable(id("aasg_")), firstVisibleAt: dateTime(), evidenceSnapshotRef: string(), evidenceHash: hash, sourceVersion },
      ["enterpriseId", "publicationPlanId", "channelPublicationId", "executionId", "channel", "externalWorkRef", "douyinExecutionMode", "accountOwnershipType", "accountAssignmentId", "firstVisibleAt", "evidenceSnapshotRef", "evidenceHash", "sourceVersion"],
    ),
    payloadExample: { enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", executionId: "exec_contract_001", channel: "DOUYIN", externalWorkRef: "douyin_work_safe_contract_001", douyinExecutionMode: "OPC_RENTED", accountOwnershipType: "OPC_RENTED", accountAssignmentId: "aasg_contract_001", firstVisibleAt: "2026-08-10T02:00:00Z", evidenceSnapshotRef: "evidence_contract_001", evidenceHash: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", sourceVersion: 3 },
    idempotencyKey: "PUBLICATION_FIRST_VISIBLE:{channelPublicationId}", idempotencyExample: "PUBLICATION_FIRST_VISIBLE:cpub_contract_001",
    businessUniqueness: "first visibility freezes once per channelPublicationId; evidence hash is immutable",
  }),
  defineContract({
    eventType: "ChannelPublicationEffective", topic: "publication.channel.effective.v1", producer: "SYS-05",
    consumers: ["SYS-06", "SYS-07", "SYS-08"],
    aggregate: aggregate("ValidPublication", "validPublicationId", "vpub_contract_001", undefined, 1, 1),
    payloadSchema: record(
      { validPublicationId: id("vpub_"), enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), executionId: id("exec_"), externalWorkRef: string(), chargeReservationId: id("pcr_"), douyinExecutionMode: enumeration(["SELF_ACCOUNT", "PLATFORM_OPERATED", "OPC_RENTED"] as const), accountOwnershipType: enumeration(["ENTERPRISE_OWNED", "PLATFORM_OWNED", "OPC_RENTED"] as const), accountAssignmentId: nullable(id("aasg_")), providerId: nullable(id("prov_")), opcAccountId: nullable(id("opca_")), channelAccountId: id("chacc_"), firstVisibleAt: dateTime(), effectiveAt: dateTime(), evidenceSnapshotRef: string(), evidenceHash: hash, sourceVersion },
      ["validPublicationId", "enterpriseId", "publicationPlanId", "channelPublicationId", "executionId", "externalWorkRef", "chargeReservationId", "douyinExecutionMode", "accountOwnershipType", "accountAssignmentId", "providerId", "opcAccountId", "channelAccountId", "firstVisibleAt", "effectiveAt", "evidenceSnapshotRef", "evidenceHash", "sourceVersion"],
    ),
    payloadExample: { validPublicationId: "vpub_contract_001", enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", executionId: "exec_contract_001", externalWorkRef: "douyin_work_safe_contract_001", chargeReservationId: "pcr_contract_001", douyinExecutionMode: "OPC_RENTED", accountOwnershipType: "OPC_RENTED", accountAssignmentId: "aasg_contract_001", providerId: "prov_contract_001", opcAccountId: "opca_contract_001", channelAccountId: "chacc_contract_001", firstVisibleAt: "2026-08-10T02:00:00Z", effectiveAt: "2026-08-11T02:00:00Z", evidenceSnapshotRef: "evidence_contract_002", evidenceHash: "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", sourceVersion: 3 },
    idempotencyKey: "PUBLICATION_EFFECTIVE:{validPublicationId}", idempotencyExample: "PUBLICATION_EFFECTIVE:vpub_contract_001",
    businessUniqueness: "one validPublicationId per Douyin channelPublicationId",
    notes: "For OPC_RENTED all assignment/provider/OPC/channel-account references are required by business validation.",
  }),
  defineContract({
    eventType: "ChannelPublicationFailed", topic: "publication.channel.failed.v1", producer: "SYS-05",
    consumers: ["SYS-06", "SYS-07", "SYS-08"],
    aggregate: aggregate("ChannelPublication", "channelPublicationId", "cpub_contract_001", "sourceVersion", 4),
    payloadSchema: record(
      { enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), executionId: nullable(id("exec_")), failureStage: string(), failureCode: string(), terminal: boolean, chargeReservationId: nullable(id("pcr_")), accountAssignmentId: nullable(id("aasg_")), sourceVersion, failedAt: dateTime() },
      ["enterpriseId", "publicationPlanId", "channelPublicationId", "executionId", "failureStage", "failureCode", "terminal", "chargeReservationId", "accountAssignmentId", "sourceVersion", "failedAt"],
    ),
    payloadExample: { enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", executionId: "exec_contract_001", failureStage: "VISIBILITY_24H", failureCode: "WORK_NOT_VISIBLE", terminal: true, chargeReservationId: "pcr_contract_001", accountAssignmentId: "aasg_contract_001", sourceVersion: 4, failedAt: "2026-08-11T02:00:00Z" },
    idempotencyKey: "PUBLICATION_FAILED:{channelPublicationId}:{sourceVersion}", idempotencyExample: "PUBLICATION_FAILED:cpub_contract_001:4",
    businessUniqueness: "channelPublicationId + sourceVersion; late failure cannot overwrite an effective publication",
  }),
  defineContract({
    eventType: "ChannelPublicationRefundEligible", topic: "publication.channel.refund-eligible.v1", producer: "SYS-05",
    consumers: ["SYS-06", "SYS-08"],
    aggregate: aggregate("PublicationLiability", "liabilityEventId", "lia_contract_001", "responsibilityVersion"),
    payloadSchema: record(
      { liabilityEventId: id("lia_"), enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), validPublicationId: id("vpub_"), chargeReservationId: id("pcr_"), douyinExecutionMode: enumeration(["PLATFORM_OPERATED"] as const), firstVisibleAt: dateTime(), removedAt: dateTime(), refundReasonCode: string(), responsibilityVersion: version, eligibilityAt: dateTime(), evidenceSnapshotRef: string(), evidenceHash: hash },
      ["liabilityEventId", "enterpriseId", "publicationPlanId", "channelPublicationId", "validPublicationId", "chargeReservationId", "douyinExecutionMode", "firstVisibleAt", "removedAt", "refundReasonCode", "responsibilityVersion", "eligibilityAt", "evidenceSnapshotRef", "evidenceHash"],
    ),
    payloadExample: { liabilityEventId: "lia_contract_001", enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", validPublicationId: "vpub_contract_001", chargeReservationId: "pcr_contract_001", douyinExecutionMode: "PLATFORM_OPERATED", firstVisibleAt: "2026-08-10T02:00:00Z", removedAt: "2026-08-12T02:00:00Z", refundReasonCode: "PLATFORM_RESPONSIBILITY_REMOVAL", responsibilityVersion: 1, eligibilityAt: "2026-08-12T02:05:00Z", evidenceSnapshotRef: "evidence_contract_003", evidenceHash: "1111111111111111111111111111111111111111111111111111111111111111" },
    idempotencyKey: "LIABILITY_REFUND_ELIGIBLE:{validPublicationId}:{refundReasonCode}:{responsibilityVersion}", idempotencyExample: "LIABILITY_REFUND_ELIGIBLE:vpub_contract_001:PLATFORM_RESPONSIBILITY_REMOVAL:1",
    businessUniqueness: "liabilityEventId and validPublicationId + reason + responsibilityVersion",
    notes: "Eligibility never means that quota or money has been returned.",
  }),
  defineContract({
    eventType: "ChannelPublicationChargeReleased", topic: "ledger.publication.charge-released.v1", producer: "SYS-08",
    consumers: ["SYS-05", "SYS-06"],
    aggregate: aggregate("PublicationChargeRelease", "releaseId", "pcrel_contract_001", "sourceVersion"),
    payloadSchema: record(
      { releaseId: id("pcrel_"), liabilityEventId: nullable(id("lia_")), enterpriseId, channelPublicationId: id("cpub_"), validPublicationId: nullable(id("vpub_")), chargeReservationId: id("pcr_"), releaseType: enumeration(["PRE_EFFECTIVE_RELEASE", "RESPONSIBILITY_REFUND"] as const), originalChargeSource: enumeration(["BENEFIT_QUOTA", "PUBLICATION_SERVICE_ORDER", "AUTHORIZED_BALANCE"] as const), releasedQuotaCount: integer(), refundedAmountFen: amountFen, refundReasonCode: nullable(string()), status: enumeration(["COMPLETED"] as const), ledgerRefs: array(string()), sourceVersion, completedAt: dateTime() },
      ["releaseId", "liabilityEventId", "enterpriseId", "channelPublicationId", "validPublicationId", "chargeReservationId", "releaseType", "originalChargeSource", "releasedQuotaCount", "refundedAmountFen", "refundReasonCode", "status", "ledgerRefs", "sourceVersion", "completedAt"],
    ),
    payloadExample: { releaseId: "pcrel_contract_001", liabilityEventId: "lia_contract_001", enterpriseId: "ent_contract_001", channelPublicationId: "cpub_contract_001", validPublicationId: "vpub_contract_001", chargeReservationId: "pcr_contract_001", releaseType: "RESPONSIBILITY_REFUND", originalChargeSource: "PUBLICATION_SERVICE_ORDER", releasedQuotaCount: 0, refundedAmountFen: 500, refundReasonCode: "PLATFORM_RESPONSIBILITY_REMOVAL", status: "COMPLETED", ledgerRefs: ["le_contract_refund_001"], sourceVersion: 1, completedAt: "2026-08-12T02:10:00Z" },
    idempotencyKey: "PUB_CHARGE_REFUND:{validPublicationId}:{refundReasonCode}:{responsibilityVersion}", idempotencyExample: "PUB_CHARGE_REFUND:vpub_contract_001:PLATFORM_RESPONSIBILITY_REMOVAL:1",
    businessUniqueness: "releaseId + sourceVersion; same liability/evidence/reservation must be stable",
  }),
  defineContract({
    messageKind: "COMMAND", eventType: "AccountAssignmentRequested", topic: "publication.account-assignment.requested.v1", producer: "SYS-05",
    consumers: ["SYS-07"],
    aggregate: aggregate("ChannelPublication", "channelPublicationId", "cpub_contract_001", "assignmentRequestVersion"),
    payloadSchema: record(
      { enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), channel: enumeration(["DOUYIN"] as const), requiredAccountOwnershipType: enumeration(["OPC_RENTED"] as const), constraints: openRecord("Non-secret matching constraints"), assignmentRequestVersion: version, sourceVersion, requestedAt: dateTime() },
      ["enterpriseId", "publicationPlanId", "channelPublicationId", "channel", "requiredAccountOwnershipType", "constraints", "assignmentRequestVersion", "sourceVersion", "requestedAt"],
    ),
    payloadExample: { enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", channel: "DOUYIN", requiredAccountOwnershipType: "OPC_RENTED", constraints: { industryCode: "RETAIL" }, assignmentRequestVersion: 1, sourceVersion: 2, requestedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "ACCOUNT_ASSIGNMENT_REQUEST:{channelPublicationId}:{assignmentRequestVersion}", idempotencyExample: "ACCOUNT_ASSIGNMENT_REQUEST:cpub_contract_001:1",
    businessUniqueness: "one result and one active assignment per channelPublicationId + assignmentRequestVersion",
  }),
  defineContract({
    eventType: "AccountAssignmentCompleted", topic: "opc.account-assignment.completed.v1", producer: "SYS-07",
    consumers: ["SYS-05"],
    aggregate: aggregate("AccountAssignment", "accountAssignmentId", "aasg_contract_001", "assignmentVersion"),
    payloadSchema: record(
      { accountAssignmentId: id("aasg_"), enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), assignmentRequestVersion: version, providerId: id("prov_"), opcAccountId: id("opca_"), channelAccountId: id("chacc_"), assignmentSnapshotVersion: version, assignmentVersion: version, sourceVersion, assignedAt: dateTime() },
      ["accountAssignmentId", "enterpriseId", "publicationPlanId", "channelPublicationId", "assignmentRequestVersion", "providerId", "opcAccountId", "channelAccountId", "assignmentSnapshotVersion", "assignmentVersion", "sourceVersion", "assignedAt"],
    ),
    payloadExample: { accountAssignmentId: "aasg_contract_001", enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", assignmentRequestVersion: 1, providerId: "prov_contract_001", opcAccountId: "opca_contract_001", channelAccountId: "chacc_contract_001", assignmentSnapshotVersion: 1, assignmentVersion: 1, sourceVersion: 2, assignedAt: "2026-08-10T02:01:00Z" },
    idempotencyKey: "ACCOUNT_ASSIGNMENT_RESULT:{channelPublicationId}:{assignmentRequestVersion}", idempotencyExample: "ACCOUNT_ASSIGNMENT_RESULT:cpub_contract_001:1",
    businessUniqueness: "Completed and Unavailable are mutually exclusive for a request version",
    piiPolicy: "No sessionRef, platformAccountId, login name, Cookie, token or credential.",
    notes: "Session authorization is a synchronous API, not an event. It must bind accountAssignmentId + channelPublicationId + executionId + assignmentSnapshotVersion.",
  }),
  defineContract({
    eventType: "AccountAssignmentUnavailable", topic: "opc.account-assignment.unavailable.v1", producer: "SYS-07",
    consumers: ["SYS-05"],
    aggregate: aggregate("AccountAssignmentRequest", "channelPublicationId", "cpub_contract_001", "resultVersion"),
    payloadSchema: record(
      { enterpriseId, publicationPlanId: id("pplan_"), channelPublicationId: id("cpub_"), assignmentRequestVersion: version, resultVersion: version, reasonCode: string(), retryAfter: nullable(dateTime()), sourceVersion, decidedAt: dateTime() },
      ["enterpriseId", "publicationPlanId", "channelPublicationId", "assignmentRequestVersion", "resultVersion", "reasonCode", "retryAfter", "sourceVersion", "decidedAt"],
    ),
    payloadExample: { enterpriseId: "ent_contract_001", publicationPlanId: "pplan_contract_001", channelPublicationId: "cpub_contract_001", assignmentRequestVersion: 1, resultVersion: 1, reasonCode: "NO_HEALTHY_ACCOUNT", retryAfter: "2026-08-10T02:30:00Z", sourceVersion: 2, decidedAt: "2026-08-10T02:01:00Z" },
    idempotencyKey: "ACCOUNT_ASSIGNMENT_RESULT:{channelPublicationId}:{assignmentRequestVersion}", idempotencyExample: "ACCOUNT_ASSIGNMENT_RESULT:cpub_contract_001:1",
    businessUniqueness: "Completed and Unavailable are mutually exclusive for a request version",
  }),
  defineContract({
    messageKind: "COMMAND", eventType: "AccountAssignmentReleaseRequested", topic: "publication.account-assignment.release-requested.v1", producer: "SYS-05",
    consumers: ["SYS-07"],
    aggregate: aggregate("AccountAssignment", "accountAssignmentId", "aasg_contract_001", "sourceVersion", 3),
    payloadSchema: record(
      { accountAssignmentId: id("aasg_"), enterpriseId, channelPublicationId: id("cpub_"), executionId: id("exec_"), reason: enumeration(["PUBLICATION_COMPLETED", "CANCELLED", "TERMINATED", "FINAL_FAILED"] as const), sourceVersion, requestedAt: dateTime() },
      ["accountAssignmentId", "enterpriseId", "channelPublicationId", "executionId", "reason", "sourceVersion", "requestedAt"],
    ),
    payloadExample: { accountAssignmentId: "aasg_contract_001", enterpriseId: "ent_contract_001", channelPublicationId: "cpub_contract_001", executionId: "exec_contract_001", reason: "PUBLICATION_COMPLETED", sourceVersion: 3, requestedAt: "2026-08-11T02:01:00Z" },
    idempotencyKey: "ACCOUNT_ASSIGNMENT_RELEASE:{accountAssignmentId}", idempotencyExample: "ACCOUNT_ASSIGNMENT_RELEASE:aasg_contract_001",
    businessUniqueness: "one effective release action per accountAssignmentId; sourceVersion only rejects stale commands",
    notes: "Never send while external execution status is unknown.",
  }),
  defineContract({
    eventType: "AccountAssignmentReleased", topic: "opc.account-assignment.released.v1", producer: "SYS-07",
    consumers: ["SYS-05"],
    aggregate: aggregate("AccountAssignment", "accountAssignmentId", "aasg_contract_001", "assignmentVersion", 2),
    payloadSchema: record(
      { accountAssignmentId: id("aasg_"), enterpriseId, channelPublicationId: id("cpub_"), executionId: id("exec_"), reason: string(), sessionRevocationStatus: enumeration(["REVOKED"] as const), coolingStatus: string(), sourceVersion, assignmentVersion: version, releasedAt: dateTime() },
      ["accountAssignmentId", "enterpriseId", "channelPublicationId", "executionId", "reason", "sessionRevocationStatus", "coolingStatus", "sourceVersion", "assignmentVersion", "releasedAt"],
    ),
    payloadExample: { accountAssignmentId: "aasg_contract_001", enterpriseId: "ent_contract_001", channelPublicationId: "cpub_contract_001", executionId: "exec_contract_001", reason: "PUBLICATION_COMPLETED", sessionRevocationStatus: "REVOKED", coolingStatus: "COOLING", sourceVersion: 3, assignmentVersion: 2, releasedAt: "2026-08-11T02:02:00Z" },
    idempotencyKey: "ACCOUNT_ASSIGNMENT_RELEASE:{accountAssignmentId}", idempotencyExample: "ACCOUNT_ASSIGNMENT_RELEASE:aasg_contract_001",
    businessUniqueness: "one release terminal result per accountAssignmentId",
    piiPolicy: "Confirms secret revocation status only; contains no secret or session-grant identifier.",
  }),
  defineContract({
    eventType: "OpcAccountStatusChanged", topic: "opc.account.status-changed.v1", producer: "SYS-07",
    consumers: ["SYS-05", "SYS-06"],
    aggregate: aggregate("OpcAccount", "opcAccountId", "opca_contract_001", "accountVersion", 3),
    payloadSchema: record(
      { providerId: id("prov_"), opcAccountId: id("opca_"), channelAccountId: id("chacc_"), admissionStatus: string(), operatingStatus: string(), healthStatus: string(), pauseReasonCode: nullable(string()), accountVersion: version, changedAt: dateTime() },
      ["providerId", "opcAccountId", "channelAccountId", "admissionStatus", "operatingStatus", "healthStatus", "pauseReasonCode", "accountVersion", "changedAt"],
    ),
    payloadExample: { providerId: "prov_contract_001", opcAccountId: "opca_contract_001", channelAccountId: "chacc_contract_001", admissionStatus: "APPROVED", operatingStatus: "ACTIVE", healthStatus: "HEALTHY", pauseReasonCode: null, accountVersion: 3, changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "OPC_ACCOUNT_STATUS:{opcAccountId}:{accountVersion}", idempotencyExample: "OPC_ACCOUNT_STATUS:opca_contract_001:3",
    businessUniqueness: "opcAccountId + accountVersion", piiPolicy: "No external login, platformAccountId, sessionRef or credential.",
  }),
  defineContract({
    messageKind: "COMMAND", eventType: "RequestOpcEarningSettlement", topic: "ledger.command.request-opc-earning-settlement.v1", producer: "SYS-07",
    consumers: ["SYS-08"],
    aggregate: aggregate("ValidPublication", "validPublicationId", "vpub_contract_001", undefined, 1, 1),
    payloadSchema: record(
      { validPublicationId: id("vpub_"), enterpriseId, channelPublicationId: id("cpub_"), accountAssignmentId: id("aasg_"), providerId: id("prov_"), opcAccountId: id("opca_"), channelAccountId: id("chacc_"), accountOwnershipType: enumeration(["OPC_RENTED"] as const), amountFen: { type: "integer", const: 200 }, ruleVersion: version, requestedAt: dateTime() },
      ["validPublicationId", "enterpriseId", "channelPublicationId", "accountAssignmentId", "providerId", "opcAccountId", "channelAccountId", "accountOwnershipType", "amountFen", "ruleVersion", "requestedAt"],
    ),
    payloadExample: { validPublicationId: "vpub_contract_001", enterpriseId: "ent_contract_001", channelPublicationId: "cpub_contract_001", accountAssignmentId: "aasg_contract_001", providerId: "prov_contract_001", opcAccountId: "opca_contract_001", channelAccountId: "chacc_contract_001", accountOwnershipType: "OPC_RENTED", amountFen: 200, ruleVersion: 1, requestedAt: "2026-08-11T02:00:00Z" },
    idempotencyKey: "OPC_EARNING:{validPublicationId}", idempotencyExample: "OPC_EARNING:vpub_contract_001",
    businessUniqueness: "validPublicationId; provider/assignment changes under this key are conflicts", notes: "This is a command, never a cash fact.",
  }),
  defineContract({
    eventType: "OpcEarningSettled", topic: "ledger.opc-earning.settled.v1", producer: "SYS-08",
    consumers: ["SYS-07"],
    aggregate: aggregate("OpcEarning", "earningId", "oearn_contract_001", "sourceVersion"),
    payloadSchema: record(
      { earningId: id("oearn_"), ledgerEntryId: id("le_"), validPublicationId: id("vpub_"), enterpriseId, channelPublicationId: id("cpub_"), accountAssignmentId: id("aasg_"), providerId: id("prov_"), opcAccountId: id("opca_"), channelAccountId: id("chacc_"), amountFen: { type: "integer", const: 200 }, accountCode: string(), ruleVersion: version, sourceVersion, settledAt: dateTime() },
      ["earningId", "ledgerEntryId", "validPublicationId", "enterpriseId", "channelPublicationId", "accountAssignmentId", "providerId", "opcAccountId", "channelAccountId", "amountFen", "accountCode", "ruleVersion", "sourceVersion", "settledAt"],
    ),
    payloadExample: { earningId: "oearn_contract_001", ledgerEntryId: "le_contract_opc_001", validPublicationId: "vpub_contract_001", enterpriseId: "ent_contract_001", channelPublicationId: "cpub_contract_001", accountAssignmentId: "aasg_contract_001", providerId: "prov_contract_001", opcAccountId: "opca_contract_001", channelAccountId: "chacc_contract_001", amountFen: 200, accountCode: "OPC_EARNING_PAYABLE", ruleVersion: 1, sourceVersion: 1, settledAt: "2026-08-11T02:01:00Z" },
    idempotencyKey: "OPC_EARNING:{validPublicationId}", idempotencyExample: "OPC_EARNING:vpub_contract_001",
    businessUniqueness: "one settled earning per validPublicationId", notes: "SYS-06 must not consume this for amounts; it consumes CashLedgerEntryPosted only.",
  }),
  defineContract({
    eventType: "OpcEarningReversed", topic: "ledger.opc-earning.reversed.v1", producer: "SYS-08",
    consumers: ["SYS-07"],
    aggregate: aggregate("OpcEarning", "earningId", "oearn_contract_001", "sourceVersion", 2),
    payloadSchema: record(
      { earningId: id("oearn_"), originalLedgerEntryId: id("le_"), reversalLedgerEntryId: id("le_"), validPublicationId: id("vpub_"), enterpriseId, channelPublicationId: id("cpub_"), accountAssignmentId: id("aasg_"), providerId: id("prov_"), opcAccountId: id("opca_"), channelAccountId: id("chacc_"), amountFen: { type: "integer", const: 200 }, reasonCode: string(), approvalRef: string(), sourceVersion, reversedAt: dateTime() },
      ["earningId", "originalLedgerEntryId", "reversalLedgerEntryId", "validPublicationId", "enterpriseId", "channelPublicationId", "accountAssignmentId", "providerId", "opcAccountId", "channelAccountId", "amountFen", "reasonCode", "approvalRef", "sourceVersion", "reversedAt"],
    ),
    payloadExample: { earningId: "oearn_contract_001", originalLedgerEntryId: "le_contract_opc_001", reversalLedgerEntryId: "le_contract_opc_reversal_001", validPublicationId: "vpub_contract_001", enterpriseId: "ent_contract_001", channelPublicationId: "cpub_contract_001", accountAssignmentId: "aasg_contract_001", providerId: "prov_contract_001", opcAccountId: "opca_contract_001", channelAccountId: "chacc_contract_001", amountFen: 200, reasonCode: "APPROVED_ADJUSTMENT", approvalRef: "approval_contract_005", sourceVersion: 2, reversedAt: "2026-08-12T02:00:00Z" },
    idempotencyKey: "OPC_EARNING_REVERSE:{originalLedgerEntryId}", idempotencyExample: "OPC_EARNING_REVERSE:le_contract_opc_001",
    businessUniqueness: "one approved reversal per original earning ledger entry; reversal appends",
  }),
] as const;

const LEDGER_EVENT_CONTRACTS = [
  defineContract({
    eventType: "MembershipChanged", topic: "ledger.membership.changed.v1", producer: "SYS-08",
    consumers: ["SYS-01", "SYS-05", "SYS-06"],
    aggregate: aggregate("Membership", "membershipId", "mem_contract_001", "membershipVersion", 2),
    payloadSchema: record(
      { membershipId: id("mem_"), enterpriseId, planCode: string(), planVersionId: string(), ruleVersion: version, status: enumeration(["FREE", "ACTIVE", "EXPIRED", "CANCELLED"] as const), startsAt: dateTime(), endsAt: nullable(dateTime()), membershipVersion: version, changedAt: dateTime() },
      ["membershipId", "enterpriseId", "planCode", "planVersionId", "ruleVersion", "status", "startsAt", "endsAt", "membershipVersion", "changedAt"],
    ),
    payloadExample: { membershipId: "mem_contract_001", enterpriseId: "ent_contract_001", planCode: "PRO", planVersionId: "mpv_contract_001", ruleVersion: 1, status: "ACTIVE", startsAt: "2026-08-10T02:00:00Z", endsAt: "2027-08-10T02:00:00Z", membershipVersion: 2, changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "MEMBERSHIP:{membershipId}:{membershipVersion}", idempotencyExample: "MEMBERSHIP:mem_contract_001:2",
    businessUniqueness: "membershipId + membershipVersion; historical rules remain immutable", notes: "This is an entitlement state, not a cash receipt.",
  }),
  defineContract({
    eventType: "BenefitQuotaChanged", topic: "ledger.benefit-quota.changed.v1", producer: "SYS-08",
    consumers: ["SYS-01", "SYS-05", "SYS-06"],
    aggregate: aggregate("BenefitQuota", "quotaAccountId", "bqa_contract_001", "quotaVersion", 3),
    payloadSchema: record(
      { quotaAccountId: id("bqa_"), enterpriseId, benefitCode: string(), availableCount: integer(), reservedCount: integer(), usedCount: integer(), expiredCount: integer(), changeReason: string(), businessNo: string(), quotaVersion: version, changedAt: dateTime() },
      ["quotaAccountId", "enterpriseId", "benefitCode", "availableCount", "reservedCount", "usedCount", "expiredCount", "changeReason", "businessNo", "quotaVersion", "changedAt"],
    ),
    payloadExample: { quotaAccountId: "bqa_contract_001", enterpriseId: "ent_contract_001", benefitCode: "DOUYIN_VIDEO_PUBLICATION", availableCount: 4, reservedCount: 1, usedCount: 0, expiredCount: 0, changeReason: "PUBLICATION_RESERVED", businessNo: "cpub_contract_001", quotaVersion: 3, changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "BENEFIT_QUOTA:{quotaAccountId}:{quotaVersion}", idempotencyExample: "BENEFIT_QUOTA:bqa_contract_001:3",
    businessUniqueness: "quotaAccountId + quotaVersion", notes: "Quota counts must never be converted into points or money.",
  }),
  defineContract({
    eventType: "ProfitBaseFrozen", topic: "ledger.profit-base.frozen.v1", producer: "SYS-08",
    consumers: ["SYS-06"],
    aggregate: aggregate("ProfitBase", "profitBaseId", "pb_contract_001", "sourceVersion"),
    payloadSchema: record(
      { profitBaseId: id("pb_"), orderId: id("ord_"), subOrderId: id("subord_"), enterpriseId, frozenAmountFen: amountFen, currency, status: enumeration(["FROZEN"] as const), membershipPlanVersionId: string(), distributionRuleVersionId: nullable(string()), sourceVersion, frozenAt: dateTime() },
      ["profitBaseId", "orderId", "subOrderId", "enterpriseId", "frozenAmountFen", "currency", "status", "membershipPlanVersionId", "distributionRuleVersionId", "sourceVersion", "frozenAt"],
    ),
    payloadExample: { profitBaseId: "pb_contract_001", orderId: "ord_contract_001", subOrderId: "subord_contract_001", enterpriseId: "ent_contract_001", frozenAmountFen: 3000, currency: "CNY", status: "FROZEN", membershipPlanVersionId: "mpv_contract_001", distributionRuleVersionId: "dru_contract_001", sourceVersion: 1, frozenAt: "2026-08-17T02:00:00Z" },
    idempotencyKey: "PROFIT_FREEZE:{subOrderId}:{settlementVersion}", idempotencyExample: "PROFIT_FREEZE:subord_contract_001:1",
    businessUniqueness: "subOrderId + settlementVersion", notes: "Non-cash operational projection only.",
  }),
  defineContract({
    eventType: "ProfitBaseAllocated", topic: "ledger.profit-base.allocated.v1", producer: "SYS-08",
    consumers: ["SYS-06"],
    aggregate: aggregate("ProfitBase", "profitBaseId", "pb_contract_001", "sourceVersion", 2),
    payloadSchema: record(
      { profitBaseId: id("pb_"), orderId: id("ord_"), subOrderId: id("subord_"), attributionVersion: version, beneficiaries: array(record({ enterpriseId, role: enumeration(["SELLER", "PROMOTER", "MEMBERSHIP_OWNER"] as const), amountFen }, ["enterpriseId", "role", "amountFen"]), 1), platformAmountFen: amountFen, membershipPlanVersionId: string(), distributionRuleVersionId: string(), roundingFen: integer(), status: enumeration(["ALLOCATED"] as const), sourceVersion, allocatedAt: dateTime() },
      ["profitBaseId", "orderId", "subOrderId", "attributionVersion", "beneficiaries", "platformAmountFen", "membershipPlanVersionId", "distributionRuleVersionId", "roundingFen", "status", "sourceVersion", "allocatedAt"],
    ),
    payloadExample: { profitBaseId: "pb_contract_001", orderId: "ord_contract_001", subOrderId: "subord_contract_001", attributionVersion: 1, beneficiaries: [{ enterpriseId: "ent_contract_001", role: "SELLER", amountFen: 1800 }, { enterpriseId: "ent_contract_002", role: "PROMOTER", amountFen: 600 }], platformAmountFen: 600, membershipPlanVersionId: "mpv_contract_001", distributionRuleVersionId: "dru_contract_001", roundingFen: 0, status: "ALLOCATED", sourceVersion: 2, allocatedAt: "2026-08-17T02:01:00Z" },
    idempotencyKey: "PROFIT_ALLOCATE:{profitBaseId}:{targetPlanVersionId}", idempotencyExample: "PROFIT_ALLOCATE:pb_contract_001:mpv_contract_001",
    businessUniqueness: "profitBaseId + target membership plan version", notes: "Non-cash operational projection only; SYS-06 cash metrics use ledger entries.",
  }),
  defineContract({
    eventType: "ProfitBaseReversed", topic: "ledger.profit-base.reversed.v1", producer: "SYS-08",
    consumers: ["SYS-06"],
    aggregate: aggregate("ProfitBase", "profitBaseId", "pb_contract_001", "sourceVersion", 3),
    payloadSchema: record(
      { profitBaseId: id("pb_"), originalAllocationVersion: version, reversalBatchId: string(), reversalLedgerRefs: array(id("le_"), 1), reasonCode: string(), approvalRef: string(), sourceVersion, reversedAt: dateTime() },
      ["profitBaseId", "originalAllocationVersion", "reversalBatchId", "reversalLedgerRefs", "reasonCode", "approvalRef", "sourceVersion", "reversedAt"],
    ),
    payloadExample: { profitBaseId: "pb_contract_001", originalAllocationVersion: 2, reversalBatchId: "revbatch_contract_001", reversalLedgerRefs: ["le_contract_reversal_001"], reasonCode: "ATTRIBUTION_ADJUSTED", approvalRef: "approval_contract_006", sourceVersion: 3, reversedAt: "2026-08-18T02:00:00Z" },
    idempotencyKey: "PROFIT_REVERSE:{profitBaseId}:{originalAllocationVersion}", idempotencyExample: "PROFIT_REVERSE:pb_contract_001:2",
    businessUniqueness: "profitBaseId + original allocation version; reversal appends",
  }),
  defineContract({
    eventType: "MerchantSettlementChanged", topic: "ledger.merchant-settlement.changed.v1", producer: "SYS-08",
    consumers: ["SYS-03", "SYS-06"],
    aggregate: aggregate("MerchantSettlement", "settlementId", "mst_contract_001", "sourceVersion", 2),
    payloadSchema: record(
      { settlementId: id("mst_"), orderId: id("ord_"), subOrderId: id("subord_"), sellerEnterpriseId: enterpriseId, storeId: id("store_"), supplierId: nullable(string()), merchantPayableFen: amountFen, supplierPayableFen: amountFen, status: string(), ledgerRefs: array(id("le_")), sourceVersion, changedAt: dateTime() },
      ["settlementId", "orderId", "subOrderId", "sellerEnterpriseId", "storeId", "supplierId", "merchantPayableFen", "supplierPayableFen", "status", "ledgerRefs", "sourceVersion", "changedAt"],
    ),
    payloadExample: { settlementId: "mst_contract_001", orderId: "ord_contract_001", subOrderId: "subord_contract_001", sellerEnterpriseId: "ent_contract_001", storeId: "store_contract_001", supplierId: null, merchantPayableFen: 9000, supplierPayableFen: 0, status: "POSTED", ledgerRefs: ["le_contract_merchant_001"], sourceVersion: 2, changedAt: "2026-08-17T02:00:00Z" },
    idempotencyKey: "ORDER_SETTLE:{subOrderId}:{settlementVersion}", idempotencyExample: "ORDER_SETTLE:subord_contract_001:2",
    businessUniqueness: "settlementId + sourceVersion; merchant and supplier payables obey the frozen sales model",
    notes: "Read projection only. Cash metrics consume CashLedgerEntryPosted.",
  }),
  defineContract({
    eventType: "PointsLedgerEntryPosted", topic: "ledger.points-entry.posted.v1", producer: "SYS-08",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("PointsEntry", "pointsEntryId", "pe_contract_001", undefined, 1, 1),
    payloadSchema: record(
      { pointsEntryId: id("pe_"), pointsAccountId: id("pa_"), enterpriseId, sourceOrChargeCode: string(), direction: enumeration(["EARN", "SPEND", "REFUND", "ADJUST"] as const), points, signedPoints: { type: "integer" }, businessType: string(), businessNo: string(), agentRunId: nullable(id("arun_")), toolCallId: nullable(id("tcall_")), reservationId: nullable(string()), originalPointsEntryId: nullable(id("pe_")), ruleVersion: version, postedAt: dateTime() },
      ["pointsEntryId", "pointsAccountId", "enterpriseId", "sourceOrChargeCode", "direction", "points", "signedPoints", "businessType", "businessNo", "agentRunId", "toolCallId", "reservationId", "originalPointsEntryId", "ruleVersion", "postedAt"],
    ),
    payloadExample: { pointsEntryId: "pe_contract_001", pointsAccountId: "pa_contract_001", enterpriseId: "ent_contract_001", sourceOrChargeCode: "AGENT_CONTENT_GENERATION", direction: "SPEND", points: 20, signedPoints: -20, businessType: "AGENT_TOOL", businessNo: "arun_contract_001", agentRunId: "arun_contract_001", toolCallId: "tcall_contract_001", reservationId: "points_res_contract_001", originalPointsEntryId: null, ruleVersion: 1, postedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "POINTS_ENTRY:{pointsEntryId}", idempotencyExample: "POINTS_ENTRY:pe_contract_001",
    businessUniqueness: "pointsEntryId exactly once; same ID must remain byte-stable", notes: "REFUND/ADJUST append and reference the original entry; balances never replace this fact.",
  }),
  defineContract({
    eventType: "PointsBalanceChanged", topic: "ledger.points-balance.changed.v1", producer: "SYS-08",
    consumers: ["SYS-01"],
    aggregate: aggregate("PointsAccount", "pointsAccountId", "pa_contract_001", "balanceVersion", 2),
    payloadSchema: record(
      { pointsAccountId: id("pa_"), enterpriseId, availablePoints: integer(), reservedPoints: integer(), balanceVersion: version, lastPointsEntryId: id("pe_"), changedAt: dateTime() },
      ["pointsAccountId", "enterpriseId", "availablePoints", "reservedPoints", "balanceVersion", "lastPointsEntryId", "changedAt"],
    ),
    payloadExample: { pointsAccountId: "pa_contract_001", enterpriseId: "ent_contract_001", availablePoints: 980, reservedPoints: 0, balanceVersion: 2, lastPointsEntryId: "pe_contract_001", changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "POINTS_BALANCE:{pointsAccountId}:{balanceVersion}", idempotencyExample: "POINTS_BALANCE:pa_contract_001:2",
    businessUniqueness: "pointsAccountId + balanceVersion", notes: "Cache invalidation only; PointsLedgerEntryPosted is the points fact source.",
  }),
  defineContract({
    eventType: "WithdrawalStatusChanged", topic: "ledger.withdrawal.status-changed.v1", producer: "SYS-08",
    consumers: ["SYS-01", "SYS-06", "SYS-07"],
    aggregate: aggregate("Withdrawal", "withdrawalId", "wd_contract_001", "version", 3),
    payloadSchema: record(
      { withdrawalId: id("wd_"), ownerType: enumeration(["ENTERPRISE", "OPC_PROVIDER"] as const), ownerId: string("enterpriseId when ENTERPRISE; providerId when OPC_PROVIDER"), amountFen, status: enumeration(["SUBMITTED", "INITIAL_REVIEW", "FINAL_REVIEW", "PROCESSING", "PAID", "REJECTED", "FAILED", "CANCELLED"] as const), reason: nullable(string()), channelNoMasked: nullable(string()), version, changedAt: dateTime() },
      ["withdrawalId", "ownerType", "ownerId", "amountFen", "status", "reason", "channelNoMasked", "version", "changedAt"],
    ),
    payloadExample: { withdrawalId: "wd_contract_001", ownerType: "OPC_PROVIDER", ownerId: "prov_contract_001", amountFen: 20000, status: "PAID", reason: null, channelNoMasked: "WX****9988", version: 3, changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "WITHDRAWAL_STATUS:{withdrawalId}:{version}", idempotencyExample: "WITHDRAWAL_STATUS:wd_contract_001:3",
    businessUniqueness: "withdrawalId + version; channel result key is independently unique",
    piiPolicy: "No payout profile or complete channel number. OPC uses ownerType=OPC_PROVIDER and ownerId=providerId.",
    notes: "ownerType/ownerId is the only frozen subject model; provider is not represented as an enterprise.",
  }),
  defineContract({
    eventType: "CashLedgerEntryPosted", topic: "ledger.cash-entry.posted.v1", producer: "SYS-08",
    consumers: ["SYS-06"],
    aggregate: aggregate("LedgerEntry", "ledgerEntryId", "le_contract_001", undefined, 1, 1),
    payloadSchema: record(
      { ledgerEntryId: id("le_"), journalId: id("jrnl_"), enterpriseId: nullable(enterpriseId), subjectType: enumeration(["ENTERPRISE", "OPC_PROVIDER", "PLATFORM", "MERCHANT", "SUPPLIER"] as const), subjectId: string(), accountCode: string(), direction: enumeration(["DEBIT", "CREDIT"] as const), amountFen, currency, metricBucket: string(), metricBucketVersion: version, metricEffect: enumeration(["INCREASE", "DECREASE"] as const), signedMetricAmountFen: { type: "integer" }, businessType: string(), businessNo: string(), sourceEventId: nullable(id("evt_")), originalLedgerEntryId: nullable(id("le_")), ruleVersion: version, postedAt: dateTime() },
      ["ledgerEntryId", "journalId", "enterpriseId", "subjectType", "subjectId", "accountCode", "direction", "amountFen", "currency", "metricBucket", "metricBucketVersion", "metricEffect", "signedMetricAmountFen", "businessType", "businessNo", "sourceEventId", "originalLedgerEntryId", "ruleVersion", "postedAt"],
    ),
    payloadExample: { ledgerEntryId: "le_contract_001", journalId: "jrnl_contract_001", enterpriseId: "ent_contract_001", subjectType: "ENTERPRISE", subjectId: "ent_contract_001", accountCode: "ENTERPRISE_AVAILABLE", direction: "CREDIT", amountFen: 1200, currency: "CNY", metricBucket: "ENTERPRISE_REVENUE", metricBucketVersion: 1, metricEffect: "INCREASE", signedMetricAmountFen: 1200, businessType: "ORDER_SETTLEMENT", businessNo: "subord_contract_001", sourceEventId: "evt_contract_source_001", originalLedgerEntryId: null, ruleVersion: 1, postedAt: "2026-08-17T02:00:00Z" },
    idempotencyKey: "CASH_LEDGER_ENTRY:{ledgerEntryId}", idempotencyExample: "CASH_LEDGER_ENTRY:le_contract_001",
    businessUniqueness: "ledgerEntryId exactly once; same ID must keep amount, sign, bucket, subject and business refs byte-stable",
    notes: "The only cash metric input for SYS-06. Reversals append a new entry referencing originalLedgerEntryId.",
  }),
  defineContract({
    eventType: "EnterpriseBalanceChanged", topic: "ledger.enterprise-balance.changed.v1", producer: "SYS-08",
    consumers: ["SYS-01"],
    aggregate: aggregate("EnterpriseBalance", "enterpriseId", "ent_contract_001", "balanceVersion", 4),
    payloadSchema: record(
      { enterpriseId, availableFen: amountFen, frozenFen: amountFen, withdrawingFen: amountFen, balanceVersion: version, lastLedgerEntryId: id("le_"), changedAt: dateTime() },
      ["enterpriseId", "availableFen", "frozenFen", "withdrawingFen", "balanceVersion", "lastLedgerEntryId", "changedAt"],
    ),
    payloadExample: { enterpriseId: "ent_contract_001", availableFen: 120000, frozenFen: 3000, withdrawingFen: 20000, balanceVersion: 4, lastLedgerEntryId: "le_contract_001", changedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "ENTERPRISE_BALANCE:{enterpriseId}:{balanceVersion}", idempotencyExample: "ENTERPRISE_BALANCE:ent_contract_001:4",
    businessUniqueness: "enterpriseId + balanceVersion", notes: "Cache invalidation only; never a cash metric input.",
  }),
  defineContract({
    eventType: "LedgerAnomalyDetected", topic: "ledger.anomaly.detected.v1", producer: "SYS-08",
    consumers: ["SYS-01", "SYS-06"],
    aggregate: aggregate("LedgerAnomaly", "anomalyId", "lan_contract_001", "anomalyVersion"),
    payloadSchema: record(
      { anomalyId: id("lan_"), enterpriseId: nullable(enterpriseId), anomalyType: string(), severity: enumeration(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const), objectType: string(), objectId: string(), assigneeRole: string(), traceId: string(), status: enumeration(["OPEN"] as const), anomalyVersion: version, detectedAt: dateTime() },
      ["anomalyId", "enterpriseId", "anomalyType", "severity", "objectType", "objectId", "assigneeRole", "traceId", "status", "anomalyVersion", "detectedAt"],
    ),
    payloadExample: { anomalyId: "lan_contract_001", enterpriseId: "ent_contract_001", anomalyType: "LEDGER_PROJECTION_MISMATCH", severity: "HIGH", objectType: "Journal", objectId: "jrnl_contract_001", assigneeRole: "PLATFORM_FINANCE", traceId: "trace_contract_fixture_001", status: "OPEN", anomalyVersion: 1, detectedAt: "2026-08-10T02:00:00Z" },
    idempotencyKey: "LEDGER_ANOMALY:{anomalyId}:{anomalyVersion}", idempotencyExample: "LEDGER_ANOMALY:lan_contract_001:1",
    businessUniqueness: "anomalyId + anomalyVersion", piiPolicy: "No raw payment callback, payout details or reconciliation evidence body.",
  }),
] as const;

/** Frozen descriptor list consumed by AsyncAPI/fixture/SDK generators. */
export const PLATFORM_EVENT_CONTRACTS: readonly PlatformEventContract[] = [
  ...IDENTITY_EVENT_CONTRACTS,
  ...COMMERCE_EVENT_CONTRACTS,
  ...CRM_EVENT_CONTRACTS,
  ...PUBLICATION_OPC_EVENT_CONTRACTS,
  ...LEDGER_EVENT_CONTRACTS,
];

/** Broker registration source. Kept as the exact same descriptor objects. */
export const PLATFORM_TOPIC_REGISTRY = PLATFORM_EVENT_CONTRACTS;

export type PlatformEventType = (typeof PLATFORM_EVENT_CONTRACTS)[number]["eventType"];

function createEnvelopeSchema(contract: PlatformEventContract): JsonSchema {
  return {
    $schema: PLATFORM_EVENT_SCHEMA_DIALECT,
    $id: `https://contracts.wotaotao.com/events/${contract.topic}/envelope.schema.json`,
    title: `${contract.eventType} envelope v${contract.schemaVersion}`,
    type: "object",
    properties: {
      eventId: id("evt_"),
      eventType: { type: "string", const: contract.eventType },
      schemaVersion: { type: "integer", const: contract.schemaVersion },
      occurredAt: dateTime("Business occurrence time"),
      publishedAt: dateTime("Outbox publication time"),
      producer: { type: "string", const: contract.producer },
      environment: enumeration(PLATFORM_ENVIRONMENTS),
      audience: {
        type: "array",
        items: enumeration(contract.consumers),
        minItems: 1,
        uniqueItems: true,
      },
      enterpriseId: nullable(enterpriseId),
      aggregateType: { type: "string", const: contract.aggregate.type },
      aggregateId: string("Stable aggregate identifier"),
      aggregateVersion:
        contract.aggregate.fixedVersion === undefined
          ? integer(1, "Monotonic aggregate version")
          : { type: "integer", const: contract.aggregate.fixedVersion },
      traceId: string(),
      causationId: nullable(id("evt_")),
      correlationId: string(),
      idempotencyKey: string("Stable business idempotency key; unchanged on retry"),
      payload: contract.payloadSchema,
    },
    required: [
      "eventId",
      "eventType",
      "schemaVersion",
      "occurredAt",
      "publishedAt",
      "producer",
      "environment",
      "audience",
      "enterpriseId",
      "aggregateType",
      "aggregateId",
      "aggregateVersion",
      "traceId",
      "causationId",
      "correlationId",
      "idempotencyKey",
      "payload",
    ],
    additionalProperties: false,
  };
}

/** Full envelope schemas keyed by eventType; payload schemas remain embedded in each descriptor. */
export const PLATFORM_EVENT_SCHEMAS: Readonly<Record<string, JsonSchema>> = Object.freeze(
  Object.fromEntries(
    PLATFORM_EVENT_CONTRACTS.map((contract) => [
      contract.eventType,
      createEnvelopeSchema(contract),
    ]),
  ),
);

export const PLATFORM_EVENT_CONTRACTS_BY_TYPE: Readonly<Record<string, PlatformEventContract>> =
  Object.freeze(
    Object.fromEntries(
      PLATFORM_EVENT_CONTRACTS.map((contract) => [contract.eventType, contract]),
    ),
  );

export function getPlatformEventContract(
  eventType: string,
): PlatformEventContract | undefined {
  return PLATFORM_EVENT_CONTRACTS_BY_TYPE[eventType];
}

const REQUIRED_DESCRIPTOR_FIELDS = [
  "eventType",
  "topic",
  "producer",
  "consumers",
  "schemaVersion",
  "payloadSchema",
  "example",
  "idempotencyKey",
] as const;

const FROZEN_TOPIC_BY_EVENT_TYPE: Readonly<Record<string, string>> = {
  EnterpriseInitialized: "platform.enterprise.initialized.v1",
  EnterpriseProfileUpdated: "platform.enterprise.profile_updated.v1",
  EnterpriseMemberChanged: "platform.enterprise.member_changed.v1",
  LeadCreated: "crm.lead.created.v1",
  LeadStatusChanged: "crm.lead.status_changed.v1",
  CustomerUpdated: "crm.customer.updated.v1",
  AccountAssignmentRequested: "publication.account-assignment.requested.v1",
  AccountAssignmentCompleted: "opc.account-assignment.completed.v1",
  AccountAssignmentUnavailable: "opc.account-assignment.unavailable.v1",
  AccountAssignmentReleaseRequested:
    "publication.account-assignment.release-requested.v1",
  AccountAssignmentReleased: "opc.account-assignment.released.v1",
  ChannelPublicationFirstVisible: "publication.channel.first_visible.v1",
  ChannelPublicationFailed: "publication.channel.failed.v1",
  ChannelPublicationEffective: "publication.channel.effective.v1",
  RequestOpcEarningSettlement:
    "ledger.command.request-opc-earning-settlement.v1",
  OpcEarningSettled: "ledger.opc-earning.settled.v1",
  OpcEarningReversed: "ledger.opc-earning.reversed.v1",
  WithdrawalStatusChanged: "ledger.withdrawal.status-changed.v1",
  OpcAccountStatusChanged: "opc.account.status-changed.v1",
};

function hasProperty(schema: JsonSchema, name: string): boolean {
  return schema.properties !== undefined && schema.properties[name] !== undefined;
}

function containsSchemaProperty(schema: JsonSchema, forbiddenName: string): boolean {
  if (schema.properties?.[forbiddenName] !== undefined) return true;
  if (schema.properties !== undefined) {
    for (const child of Object.values(schema.properties)) {
      if (containsSchemaProperty(child, forbiddenName)) return true;
    }
  }
  if (schema.items !== undefined && containsSchemaProperty(schema.items, forbiddenName)) return true;
  for (const branch of schema.anyOf ?? []) {
    if (containsSchemaProperty(branch, forbiddenName)) return true;
  }
  for (const branch of schema.oneOf ?? []) {
    if (containsSchemaProperty(branch, forbiddenName)) return true;
  }
  return false;
}

/**
 * Performs dependency-free structural validation.  Return an empty array before
 * generation, tests or Broker registration.  JSON Schema validators still
 * validate individual examples/traffic against PLATFORM_EVENT_SCHEMAS.
 */
export function validatePlatformEventContracts(): string[] {
  const errors: string[] = [];
  const eventTypes = new Set<string>();
  const topics = new Set<string>();

  for (const [index, contract] of PLATFORM_EVENT_CONTRACTS.entries()) {
    const label = contract.eventType || `contract[${index}]`;
    for (const field of REQUIRED_DESCRIPTOR_FIELDS) {
      if (!(field in contract)) errors.push(`${label}: missing descriptor field ${field}`);
    }
    if (eventTypes.has(contract.eventType)) errors.push(`${label}: duplicate eventType`);
    eventTypes.add(contract.eventType);
    if (topics.has(contract.topic)) errors.push(`${label}: duplicate topic ${contract.topic}`);
    topics.add(contract.topic);
    if (!contract.topic.endsWith(`.v${contract.schemaVersion}`)) {
      errors.push(`${label}: topic suffix does not match schemaVersion`);
    }
    if (!PLATFORM_PRODUCERS.includes(contract.producer)) {
      errors.push(`${label}: unknown producer ${contract.producer}`);
    }
    if (contract.consumers.length === 0) errors.push(`${label}: consumers cannot be empty`);
    if (new Set(contract.consumers).size !== contract.consumers.length) {
      errors.push(`${label}: duplicate consumer/audience`);
    }
    for (const consumer of contract.consumers) {
      if (!PLATFORM_SYSTEMS.includes(consumer)) errors.push(`${label}: unknown consumer ${consumer}`);
    }
    if (contract.audience.join("|") !== contract.consumers.join("|")) {
      errors.push(`${label}: descriptor audience must exactly equal consumers`);
    }
    if (contract.schemaVersion !== 1) errors.push(`${label}: this registry currently freezes v1 only`);
    if (contract.payloadSchema.type !== "object") errors.push(`${label}: payloadSchema must be an object`);
    if (contract.payloadSchema.additionalProperties !== false) {
      errors.push(`${label}: payloadSchema must reject undeclared fields`);
    }
    if (containsSchemaProperty(contract.payloadSchema, "eventVersion")) {
      errors.push(`${label}: eventVersion is forbidden; use schemaVersion/aggregateVersion`);
    }
    if (contract.example.eventType !== contract.eventType) errors.push(`${label}: example eventType mismatch`);
    if (contract.example.schemaVersion !== contract.schemaVersion) errors.push(`${label}: example schemaVersion mismatch`);
    if (contract.example.producer !== contract.producer) errors.push(`${label}: example producer mismatch`);
    if (contract.example.aggregateType !== contract.aggregate.type) errors.push(`${label}: example aggregateType mismatch`);
    if (contract.example.idempotencyKey !== contract.idempotencyExample) errors.push(`${label}: example idempotency key mismatch`);
    if (contract.idempotencyKey.includes("PUB_CHARGE_RESERVE")) {
      errors.push(`${label}: legacy PUB_CHARGE_RESERVE key is forbidden; use PUBLICATION_CHARGE`);
    }
    const frozenTopic = FROZEN_TOPIC_BY_EVENT_TYPE[contract.eventType];
    if (frozenTopic !== undefined && contract.topic !== frozenTopic) {
      errors.push(`${label}: expected frozen topic ${frozenTopic}`);
    }
  }

  if (Object.keys(PLATFORM_EVENT_SCHEMAS).length !== PLATFORM_EVENT_CONTRACTS.length) {
    errors.push("PLATFORM_EVENT_SCHEMAS count does not match descriptor count");
  }

  const withdrawal = PLATFORM_EVENT_CONTRACTS_BY_TYPE.WithdrawalStatusChanged;
  if (
    withdrawal === undefined ||
    !hasProperty(withdrawal.payloadSchema, "ownerType") ||
    !hasProperty(withdrawal.payloadSchema, "ownerId") ||
    "providerId" in withdrawal.example.payload ||
    "enterpriseId" in withdrawal.example.payload
  ) {
    errors.push(
      "WithdrawalStatusChanged must use ownerType/ownerId only; OPC is OPC_PROVIDER/providerId",
    );
  }
  if (
    withdrawal?.example.payload.ownerType === "OPC_PROVIDER" &&
    withdrawal.example.payload.ownerId !== "prov_contract_001"
  ) {
    errors.push("WithdrawalStatusChanged OPC fixture ownerId must be providerId");
  }

  const assignment = PLATFORM_EVENT_CONTRACTS_BY_TYPE.AccountAssignmentCompleted;
  if (
    assignment === undefined ||
    !hasProperty(assignment.payloadSchema, "assignmentSnapshotVersion") ||
    assignment.example.payload.assignmentSnapshotVersion === undefined
  ) {
    errors.push("AccountAssignmentCompleted must carry assignmentSnapshotVersion");
  }

  const reservation = PLATFORM_EVENT_CONTRACTS_BY_TYPE.ChannelPublicationReserved;
  if (reservation?.idempotencyKey !== "PUBLICATION_CHARGE:{channelPublicationId}") {
    errors.push("ChannelPublicationReserved must use PUBLICATION_CHARGE:{channelPublicationId}");
  }

  return errors;
}
