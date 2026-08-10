/**
 * Full-platform HTTP contract source of truth.
 *
 * This file intentionally does not import the legacy MVP contracts. The legacy
 * package models a small content-review slice, while this registry freezes the
 * SYS-01 ... SYS-08 integration boundary described by PRD V1.0.
 *
 * Public/user APIs use /api/v1, service-to-service APIs use /internal/v1 and
 * provider callbacks use /callbacks/v1. Paths from older drafts such as
 * /api/v1/internal are normalized here and must not be reintroduced.
 */

export type PlatformSystem =
  | "SYS-01"
  | "SYS-02"
  | "SYS-03"
  | "SYS-04"
  | "SYS-05"
  | "SYS-06"
  | "SYS-07"
  | "SYS-08";

export type PlatformHttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type PlatformApiVisibility = "PUBLIC" | "INTERNAL" | "CALLBACK";
export type PlatformAuthMode =
  | "PUBLIC"
  | "USER_SESSION"
  | "USER_SESSION_STRONG"
  | "SERVICE_MTLS"
  | "SERVICE_MTLS_USER_DELEGATION"
  | "SIGNED_PROVIDER_CALLBACK";

export type PlatformJsonSchemaType =
  | "null"
  | "boolean"
  | "object"
  | "array"
  | "number"
  | "integer"
  | "string";

export type PlatformJsonPrimitive = string | number | boolean | null;

export interface PlatformJsonSchema {
  readonly $schema?: string;
  readonly $id?: string;
  readonly $ref?: string;
  readonly title?: string;
  readonly description?: string;
  readonly type?: PlatformJsonSchemaType | readonly PlatformJsonSchemaType[];
  readonly format?: string;
  readonly pattern?: string;
  readonly minLength?: number;
  readonly maxLength?: number;
  readonly minimum?: number;
  readonly maximum?: number;
  readonly minItems?: number;
  readonly maxItems?: number;
  readonly uniqueItems?: boolean;
  readonly properties?: Readonly<Record<string, PlatformJsonSchema>>;
  readonly required?: readonly string[];
  readonly additionalProperties?: boolean | PlatformJsonSchema;
  readonly items?: PlatformJsonSchema;
  readonly enum?: readonly PlatformJsonPrimitive[];
  readonly const?: PlatformJsonPrimitive;
  readonly oneOf?: readonly PlatformJsonSchema[];
  readonly anyOf?: readonly PlatformJsonSchema[];
  readonly allOf?: readonly PlatformJsonSchema[];
  readonly examples?: readonly unknown[];
  readonly default?: unknown;
}

export interface PlatformErrorDefinition {
  readonly httpStatus: number;
  readonly retryable: boolean;
  readonly description: string;
}

const schema = {
  string(options: Omit<PlatformJsonSchema, "type"> = {}): PlatformJsonSchema {
    return { type: "string", ...options };
  },
  nullableString(
    options: Omit<PlatformJsonSchema, "type"> = {},
  ): PlatformJsonSchema {
    return { type: ["string", "null"], ...options };
  },
  integer(options: Omit<PlatformJsonSchema, "type"> = {}): PlatformJsonSchema {
    return { type: "integer", ...options };
  },
  nullableInteger(
    options: Omit<PlatformJsonSchema, "type"> = {},
  ): PlatformJsonSchema {
    return { type: ["integer", "null"], ...options };
  },
  boolean(options: Omit<PlatformJsonSchema, "type"> = {}): PlatformJsonSchema {
    return { type: "boolean", ...options };
  },
  nullableBoolean(
    options: Omit<PlatformJsonSchema, "type"> = {},
  ): PlatformJsonSchema {
    return { type: ["boolean", "null"], ...options };
  },
  enum(values: readonly string[]): PlatformJsonSchema {
    return { type: "string", enum: values };
  },
  nullableEnum(values: readonly string[]): PlatformJsonSchema {
    return { type: ["string", "null"], enum: [...values, null] };
  },
  array(
    items: PlatformJsonSchema,
    options: Omit<PlatformJsonSchema, "type" | "items"> = {},
  ): PlatformJsonSchema {
    return { type: "array", items, ...options };
  },
  object(
    properties: Readonly<Record<string, PlatformJsonSchema>>,
    required: readonly string[] = Object.keys(properties),
    additionalProperties: boolean | PlatformJsonSchema = false,
  ): PlatformJsonSchema {
    return {
      type: "object",
      properties,
      required,
      additionalProperties,
    };
  },
  record(value: PlatformJsonSchema = {}): PlatformJsonSchema {
    return { type: "object", additionalProperties: value };
  },
  id(prefix?: string): PlatformJsonSchema {
    return {
      type: "string",
      pattern: prefix
        ? "^" + prefix + "[A-Za-z0-9][A-Za-z0-9_-]{1,126}$"
        : "^[A-Za-z][A-Za-z0-9_-]{2,127}$",
    };
  },
  dateTime(): PlatformJsonSchema {
    return { type: "string", format: "date-time" };
  },
} as const;

const FIELD_ERROR_SCHEMA = schema.object(
  {
    field: schema.string({ minLength: 1 }),
    code: schema.string({ minLength: 1 }),
    message: schema.string({ minLength: 1 }),
  },
  ["field", "code", "message"],
);

export const PLATFORM_HTTP_SCHEMAS = {
  JsonSchemaDialect: "https://json-schema.org/draft/2020-12/schema",
  Id: schema.id(),
  TraceId: schema.string({
    pattern: "^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$",
  }),
  IsoDateTime: schema.dateTime(),
  Currency: schema.enum(["CNY"]),
  MoneyFen: schema.integer({ minimum: 0 }),
  PositiveVersion: schema.integer({ minimum: 1 }),
  NullableId: schema.nullableString({
    pattern: "^[A-Za-z][A-Za-z0-9_-]{2,127}$",
  }),
  Cursor: schema.nullableString({ maxLength: 512 }),
  FieldError: FIELD_ERROR_SCHEMA,
  ErrorResponse: schema.object(
    {
      code: schema.string({ minLength: 1 }),
      message: schema.string({ minLength: 1 }),
      retryable: schema.boolean(),
      requestId: schema.string({ minLength: 8 }),
      traceId: schema.string({ minLength: 8 }),
      fieldErrors: schema.array(FIELD_ERROR_SCHEMA),
      currentVersion: schema.nullableInteger({ minimum: 1 }),
      availableActions: schema.array(schema.string({ minLength: 1 })),
      commandId: schema.nullableString({ minLength: 1 }),
    },
    ["code", "message", "retryable", "requestId", "traceId", "fieldErrors"],
  ),
} as const satisfies Readonly<Record<string, PlatformJsonSchema | string>>;

export const PLATFORM_ERROR_REGISTRY = {
  VALIDATION_ERROR: {
    httpStatus: 400,
    retryable: false,
    description: "Request shape or field validation failed.",
  },
  AUTH_REQUIRED: {
    httpStatus: 401,
    retryable: false,
    description: "A valid user session is required.",
  },
  FORBIDDEN: {
    httpStatus: 403,
    retryable: false,
    description: "The authenticated actor is not allowed to perform the action.",
  },
  TENANT_SCOPE_VIOLATION: {
    httpStatus: 403,
    retryable: false,
    description: "The object is outside the trusted enterprise/provider scope.",
  },
  OBJECT_NOT_FOUND: {
    httpStatus: 404,
    retryable: false,
    description: "The object is absent or intentionally hidden from this caller.",
  },
  VERSION_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "The aggregate version changed and must be re-read.",
  },
  IDEMPOTENCY_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "The same idempotency key was reused with a different payload hash.",
  },
  RATE_LIMITED: {
    httpStatus: 429,
    retryable: true,
    description: "The caller must wait for the supplied retry interval.",
  },
  DEPENDENCY_UNAVAILABLE: {
    httpStatus: 503,
    retryable: true,
    description: "A required dependency is temporarily unavailable.",
  },
  CALLBACK_SIGNATURE_INVALID: {
    httpStatus: 401,
    retryable: false,
    description: "Provider signature, timestamp, nonce or credential binding failed.",
  },
  CALLBACK_PAYLOAD_MISMATCH: {
    httpStatus: 409,
    retryable: false,
    description: "A provider business key was replayed with different facts.",
  },
  ENTERPRISE_INIT_REQUIRED: {
    httpStatus: 409,
    retryable: false,
    description: "The user does not yet have an initialized enterprise.",
  },
  ENTERPRISE_REVIEW_REQUIRED: {
    httpStatus: 403,
    retryable: false,
    description: "Enterprise review is required for this capability.",
  },
  WHITELIST_REQUIRED: {
    httpStatus: 403,
    retryable: false,
    description: "The enterprise or user is not in the controlled rollout.",
  },
  FEATURE_DISABLED: {
    httpStatus: 403,
    retryable: false,
    description: "The feature flag is disabled for the current scope.",
  },
  REVIEW_SUBMISSION_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "An active review already exists for this profile version.",
  },
  APPROVAL_AUTHORIZATION_DENIED: {
    httpStatus: 403,
    retryable: false,
    description: "Permission, data scope or separation-of-duty validation failed.",
  },
  TOOL_AUTHORIZATION_INVALID: {
    httpStatus: 403,
    retryable: false,
    description: "The short-lived tool authorization is invalid or mismatched.",
  },
  TOOL_RESULT_VERSION_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "A tool result version is stale or conflicts with saved payload.",
  },
  CONSUMER_TRIAL_WHITELIST_REQUIRED: {
    httpStatus: 403,
    retryable: false,
    description: "The consumer cannot start a new controlled-rollout transaction.",
  },
  TRIAL_INVITATION_INVALID: {
    httpStatus: 422,
    retryable: false,
    description: "The trial invitation is invalid, expired or exhausted.",
  },
  PRODUCT_UNAVAILABLE: {
    httpStatus: 422,
    retryable: false,
    description: "The product/version is not currently sellable.",
  },
  PRODUCT_SALES_MODEL_INVALID: {
    httpStatus: 422,
    retryable: false,
    description: "Required sales-model or payee facts are missing or invalid.",
  },
  PRICE_CHANGED: {
    httpStatus: 409,
    retryable: false,
    description: "The checkout price differs from the preview.",
  },
  OUT_OF_STOCK: {
    httpStatus: 409,
    retryable: false,
    description: "One or more requested SKU quantities are unavailable.",
  },
  CART_STORE_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "The cart would contain incompatible stores.",
  },
  ORDER_STATE_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "The order is not in a legal state for the command.",
  },
  PAYMENT_PENDING: {
    httpStatus: 409,
    retryable: true,
    description: "The existing payment result is still unknown.",
  },
  PAYMENT_CHANNEL_UNAVAILABLE: {
    httpStatus: 503,
    retryable: true,
    description: "The selected payment channel is unavailable.",
  },
  INVENTORY_RESERVATION_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "The inventory reservation conflicts with current order facts.",
  },
  ORDER_INVENTORY_NOT_COMMITTED: {
    httpStatus: 409,
    retryable: true,
    description: "Shipment is blocked until committed inventory is confirmed.",
  },
  AFTERSALE_NOT_ELIGIBLE: {
    httpStatus: 422,
    retryable: false,
    description: "The order item, amount, deadline or state is not eligible.",
  },
  REVIEW_NOT_ELIGIBLE: {
    httpStatus: 422,
    retryable: false,
    description: "The completed order item is not eligible for this review action.",
  },
  PUBLISHED_SNAPSHOT_VERSION_MISMATCH: {
    httpStatus: 409,
    retryable: false,
    description: "The immutable product snapshot version does not match.",
  },
  PUBLISHED_SNAPSHOT_HASH_MISMATCH: {
    httpStatus: 409,
    retryable: false,
    description: "The immutable product snapshot hash does not match.",
  },
  DISTRIBUTION_CONTEXT_PENDING: {
    httpStatus: 202,
    retryable: true,
    description: "Transaction may proceed, but profit distribution remains blocked.",
  },
  COMMERCE_NOT_ENABLED: {
    httpStatus: 403,
    retryable: false,
    description: "Commerce is disabled for the current enterprise.",
  },
  STORE_NOT_ACTIVE: {
    httpStatus: 422,
    retryable: false,
    description: "The store is not active.",
  },
  SOURCE_NOT_AUTHORIZED: {
    httpStatus: 403,
    retryable: false,
    description: "Source acquisition or commercial-use evidence is not authorized.",
  },
  COMMERCIAL_USE_NOT_CLEARED: {
    httpStatus: 422,
    retryable: false,
    description: "Commercial-use clearance is incomplete.",
  },
  PRODUCT_REVIEW_REQUIRED: {
    httpStatus: 422,
    retryable: false,
    description: "The current product version requires review.",
  },
  INVENTORY_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "Inventory version, quantity or terminal state conflicts.",
  },
  INVENTORY_RESERVATION_NOT_FOUND: {
    httpStatus: 404,
    retryable: false,
    description: "The inventory reservation does not exist in this scope.",
  },
  COMMAND_IDEMPOTENCY_PAYLOAD_MISMATCH: {
    httpStatus: 409,
    retryable: false,
    description: "The command key was replayed with a different canonical payload.",
  },
  APPROVAL_REF_REQUIRED: {
    httpStatus: 422,
    retryable: false,
    description: "A non-null approval reference is required for this action.",
  },
  COST_INCOMPLETE: {
    httpStatus: 422,
    retryable: true,
    description: "Required settlement evidence is incomplete.",
  },
  MARKETING_CONTEXT_UNAVAILABLE: {
    httpStatus: 503,
    retryable: true,
    description: "Trusted enterprise marketing context is unavailable.",
  },
  SOURCE_LICENSE_MISSING: {
    httpStatus: 422,
    retryable: false,
    description: "The source record has no valid license/consent evidence.",
  },
  CONTACT_DETERMINISTIC_DUPLICATE: {
    httpStatus: 409,
    retryable: false,
    description: "The contact deterministically matches an existing record.",
  },
  CRM_STAGE_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "The requested CRM stage transition is illegal.",
  },
  TOUCH_NOT_AUTHORIZED: {
    httpStatus: 403,
    retryable: false,
    description: "Consent, purpose, suppression or time policy denies contact.",
  },
  CALL_CAMPAIGN_NOT_APPROVED: {
    httpStatus: 422,
    retryable: false,
    description: "The call campaign is not approved for execution.",
  },
  CALL_ADAPTER_UNHEALTHY: {
    httpStatus: 503,
    retryable: true,
    description: "The real AI-calling adapter is unhealthy.",
  },
  CALL_RESULT_INCOMPLETE: {
    httpStatus: 422,
    retryable: true,
    description: "The provider callback does not contain a complete terminal result.",
  },
  WECHAT_ADAPTER_UNHEALTHY: {
    httpStatus: 503,
    retryable: true,
    description: "The WeChat adapter is unhealthy.",
  },
  HUMAN_HANDOFF_REQUIRED: {
    httpStatus: 422,
    retryable: false,
    description: "Automation must stop and create a human handoff.",
  },
  ATTRIBUTION_FREEZE_PENDING: {
    httpStatus: 202,
    retryable: true,
    description: "Attribution resolution is pending and must not be guessed.",
  },
  CONTENT_VERSION_LOCKED: {
    httpStatus: 409,
    retryable: false,
    description: "The submitted/locked content version is immutable.",
  },
  CONTENT_NOT_APPROVED: {
    httpStatus: 422,
    retryable: false,
    description: "The content/channel version has no valid approval.",
  },
  PUBLICATION_STATE_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "The publication state does not allow the requested action.",
  },
  PUBLICATION_CHARGE_NOT_RESERVED: {
    httpStatus: 409,
    retryable: true,
    description: "No matching ChannelPublicationReserved fact exists.",
  },
  ASSIGNMENT_UNAVAILABLE: {
    httpStatus: 422,
    retryable: true,
    description: "No compliant account assignment is currently available.",
  },
  ASSIGNMENT_RESULT_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "Account-assignment result facts conflict.",
  },
  EXECUTION_STATUS_UNKNOWN: {
    httpStatus: 409,
    retryable: true,
    description: "External execution status is unknown; blind retry/release is forbidden.",
  },
  ASSIGNMENT_RELEASE_NOT_ALLOWED: {
    httpStatus: 409,
    retryable: false,
    description: "The assignment cannot be released from the current execution state.",
  },
  METRIC_NOT_FOUND: {
    httpStatus: 404,
    retryable: false,
    description: "The approved metric definition does not exist.",
  },
  ANALYTICS_DIMENSION_DENIED: {
    httpStatus: 400,
    retryable: false,
    description: "The requested dimension or expression is not allowlisted.",
  },
  ANALYTICS_DATA_STALE: {
    httpStatus: 503,
    retryable: true,
    description: "Required source cutoffs are too stale for this operation.",
  },
  EXPORT_LIMIT_EXCEEDED: {
    httpStatus: 422,
    retryable: false,
    description: "The export exceeds row, frequency or field limits.",
  },
  PROFILE_VALIDATION_FAILED: {
    httpStatus: 422,
    retryable: false,
    description: "The OPC identity profile failed validation.",
  },
  OPC_FORBIDDEN: {
    httpStatus: 403,
    retryable: false,
    description: "The provider does not own or cannot access the OPC object.",
  },
  DUPLICATE_ACCOUNT: {
    httpStatus: 409,
    retryable: false,
    description: "The submitted channel account already exists.",
  },
  INVALID_EVIDENCE: {
    httpStatus: 422,
    retryable: false,
    description: "Required account evidence is invalid.",
  },
  ACCOUNT_NOT_USABLE: {
    httpStatus: 409,
    retryable: true,
    description: "The assigned account is paused, risky, unhealthy or released.",
  },
  SESSION_GRANT_EXPIRED: {
    httpStatus: 401,
    retryable: false,
    description: "The one-time session grant expired.",
  },
  SCOPE_DENIED: {
    httpStatus: 403,
    retryable: false,
    description: "The requested account-session scope is not allowed.",
  },
  REPLAY_DETECTED: {
    httpStatus: 409,
    retryable: false,
    description: "A nonce, one-time grant or provider event was replayed.",
  },
  ASSIGNMENT_RELEASED: {
    httpStatus: 409,
    retryable: false,
    description: "The account assignment has already been released.",
  },
  LEDGER_RULE_NOT_EFFECTIVE: {
    httpStatus: 422,
    retryable: true,
    description: "No approved effective ledger rule exists for the business time.",
  },
  LEDGER_COST_INCOMPLETE: {
    httpStatus: 422,
    retryable: true,
    description: "Accounting cost evidence is incomplete.",
  },
  LEDGER_IDEMPOTENCY_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "A ledger business key was reused with different immutable facts.",
  },
  LEDGER_BALANCE_RECONCILING: {
    httpStatus: 409,
    retryable: true,
    description: "Balance reconciliation blocks withdrawals and adjustments.",
  },
  QUOTA_INSUFFICIENT: {
    httpStatus: 422,
    retryable: false,
    description: "No quota or valid 500-fen service-payment source is available.",
  },
  PUBLICATION_SOURCE_INVALID: {
    httpStatus: 422,
    retryable: false,
    description: "Publication charge sources are missing, conflicting or invalid.",
  },
  OPC_FACTS_INCOMPLETE: {
    httpStatus: 422,
    retryable: true,
    description: "Required effective-publication and assignment facts are incomplete.",
  },
  POINTS_INSUFFICIENT: {
    httpStatus: 422,
    retryable: false,
    description: "The enterprise points balance is insufficient.",
  },
  WITHDRAWAL_PAYOUT_PROFILE_INVALID: {
    httpStatus: 422,
    retryable: false,
    description: "The payout profile is unverified or belongs to another subject.",
  },
  WITHDRAWAL_DUTY_CONFLICT: {
    httpStatus: 409,
    retryable: false,
    description: "Initial and final withdrawal reviewers must be different people.",
  },
} as const satisfies Readonly<Record<string, PlatformErrorDefinition>>;

export type PlatformErrorCode = keyof typeof PLATFORM_ERROR_REGISTRY;

export interface PlatformHttpAuth {
  readonly mode: PlatformAuthMode;
  readonly roles: readonly string[];
  readonly scopes: readonly string[];
  readonly servicePrincipals: readonly string[];
  readonly notes: string;
}

export interface PlatformHttpIdempotency {
  readonly required: boolean;
  readonly source: "NONE" | "HEADER" | "PROVIDER_EVENT";
  readonly headerName: "Idempotency-Key" | null;
  readonly keyFormat: string | null;
  readonly replayBehavior: string;
  readonly payloadConflictHttpStatus: 409;
}

export interface PlatformHttpRequestContract {
  readonly contentType: "application/json";
  readonly schema: PlatformJsonSchema;
}

export interface PlatformHttpResponseContract {
  readonly successStatus: number;
  readonly successSchema: PlatformJsonSchema;
  readonly errorSchema: PlatformJsonSchema;
}

export interface PlatformHttpErrorContract extends PlatformErrorDefinition {
  readonly code: PlatformErrorCode;
}

export interface PlatformHttpExample {
  readonly request: Readonly<Record<string, unknown>>;
  readonly response: unknown;
}

export interface PlatformHttpContract {
  readonly operationId: string;
  readonly system: PlatformSystem;
  readonly visibility: PlatformApiVisibility;
  readonly method: PlatformHttpMethod;
  readonly path: string;
  readonly owner: PlatformSystem;
  readonly producer: string;
  readonly consumer: readonly string[];
  readonly audience: readonly string[];
  readonly auth: PlatformHttpAuth;
  readonly idempotency: PlatformHttpIdempotency;
  readonly request: PlatformHttpRequestContract;
  readonly response: PlatformHttpResponseContract;
  readonly errors: readonly PlatformHttpErrorContract[];
  readonly examples: {
    readonly success: PlatformHttpExample;
    readonly failure: PlatformHttpExample;
  };
  readonly sourceRefs: readonly string[];
}

interface ContractDefinition {
  readonly operationId: string;
  readonly system: PlatformSystem;
  readonly visibility: PlatformApiVisibility;
  readonly method: PlatformHttpMethod;
  readonly path: string;
  readonly producer?: string;
  readonly consumer: readonly string[];
  readonly audience: readonly string[];
  readonly auth: PlatformHttpAuth;
  readonly idempotency?: {
    readonly source?: "HEADER" | "PROVIDER_EVENT";
    readonly keyFormat: string;
  };
  readonly params?: PlatformJsonSchema;
  readonly query?: PlatformJsonSchema;
  readonly body?: PlatformJsonSchema;
  readonly requestExample?: Readonly<Record<string, unknown>>;
  readonly responseData: PlatformJsonSchema;
  readonly responseExample: unknown;
  readonly successStatus: number;
  readonly errors: readonly PlatformErrorCode[];
  readonly sourceRefs: readonly string[];
}

function actorAuth(
  roles: readonly string[],
  scopes: readonly string[],
  strong = false,
): PlatformHttpAuth {
  return {
    mode: strong ? "USER_SESSION_STRONG" : "USER_SESSION",
    roles,
    scopes,
    servicePrincipals: [],
    notes: strong
      ? "Signed user session, recent strong authentication and CSRF protection."
      : "Signed user session; enterprise/provider scope is derived server-side.",
  };
}

function serviceAuth(
  principals: readonly string[],
  scopes: readonly string[],
  withDelegation = false,
): PlatformHttpAuth {
  return {
    mode: withDelegation
      ? "SERVICE_MTLS_USER_DELEGATION"
      : "SERVICE_MTLS",
    roles: [],
    scopes,
    servicePrincipals: principals,
    notes: withDelegation
      ? "mTLS service identity plus a short-lived SYS-01 user delegation assertion."
      : "mTLS service identity, audience and object-scope authorization.",
  };
}

const PUBLIC_AUTH: PlatformHttpAuth = {
  mode: "PUBLIC",
  roles: [],
  scopes: [],
  servicePrincipals: [],
  notes: "Public route; no caller-supplied role or enterprise is trusted.",
};

const CALLBACK_AUTH: PlatformHttpAuth = {
  mode: "SIGNED_PROVIDER_CALLBACK",
  roles: [],
  scopes: [],
  servicePrincipals: [],
  notes:
    "Verify credential-bound signature, timestamp and nonce before resolving tenant/business ownership.",
};

function successSchema(data: PlatformJsonSchema): PlatformJsonSchema {
  return schema.object(
    {
      data,
      requestId: schema.string({ minLength: 8 }),
      traceId: PLATFORM_HTTP_SCHEMAS.TraceId,
    },
    ["data", "requestId", "traceId"],
  );
}

function errorSchema(codes: readonly PlatformErrorCode[]): PlatformJsonSchema {
  return schema.object(
    {
      code: {
        type: "string",
        enum: codes,
      },
      message: schema.string({ minLength: 1 }),
      retryable: schema.boolean(),
      requestId: schema.string({ minLength: 8 }),
      traceId: PLATFORM_HTTP_SCHEMAS.TraceId,
      fieldErrors: schema.array(FIELD_ERROR_SCHEMA),
      currentVersion: schema.nullableInteger({ minimum: 1 }),
      availableActions: schema.array(schema.string({ minLength: 1 })),
      commandId: schema.nullableString({ minLength: 1 }),
    },
    ["code", "message", "retryable", "requestId", "traceId", "fieldErrors"],
  );
}

function requestHeadersSchema(
  auth: PlatformHttpAuth,
  idempotency: PlatformHttpIdempotency,
): PlatformJsonSchema {
  const properties: Record<string, PlatformJsonSchema> = {
    "x-trace-id": PLATFORM_HTTP_SCHEMAS.TraceId,
  };
  // Callers may continue an existing trace; gateways/providers create one when absent.
  const required: string[] = [];

  if (
    auth.mode === "USER_SESSION" ||
    auth.mode === "USER_SESSION_STRONG"
  ) {
    properties.authorization = schema.string({
      pattern: "^Bearer\\s+[^\\s]+$",
    });
    required.push("authorization");
  }
  if (auth.mode === "USER_SESSION_STRONG") {
    properties["x-csrf-token"] = schema.string({ minLength: 16 });
    required.push("x-csrf-token");
  }
  if (auth.mode === "SERVICE_MTLS_USER_DELEGATION") {
    properties["x-user-delegation"] = schema.string({ minLength: 32 });
    required.push("x-user-delegation");
  }
  if (auth.mode === "SIGNED_PROVIDER_CALLBACK") {
    properties["x-provider-signature"] = schema.string({ minLength: 16 });
    properties["x-provider-timestamp"] = schema.dateTime();
    properties["x-provider-nonce"] = schema.string({ minLength: 16 });
    required.push(
      "x-provider-signature",
      "x-provider-timestamp",
      "x-provider-nonce",
    );
  }
  if (idempotency.source === "HEADER") {
    properties["idempotency-key"] = schema.string({
      minLength: 8,
      maxLength: 200,
    });
    required.push("idempotency-key");
  }

  return schema.object(properties, required);
}

function requestHeaderExample(
  auth: PlatformHttpAuth,
  idempotency: PlatformHttpIdempotency,
): Readonly<Record<string, unknown>> {
  const headers: Record<string, unknown> = {
    "x-trace-id": "trace_contract_example_001",
  };
  if (
    auth.mode === "USER_SESSION" ||
    auth.mode === "USER_SESSION_STRONG"
  ) {
    headers.authorization = "Bearer <access-token>";
  }
  if (auth.mode === "USER_SESSION_STRONG") {
    headers["x-csrf-token"] = "csrf_example_token_001";
  }
  if (auth.mode === "SERVICE_MTLS_USER_DELEGATION") {
    headers["x-user-delegation"] = "<signed-user-delegation-assertion>";
  }
  if (auth.mode === "SIGNED_PROVIDER_CALLBACK") {
    headers["x-provider-signature"] = "<provider-signature>";
    headers["x-provider-timestamp"] = "2026-08-10T02:00:00Z";
    headers["x-provider-nonce"] = "provider_nonce_001";
  }
  if (idempotency.source === "HEADER") {
    headers["idempotency-key"] = idempotency.keyFormat;
  }
  return headers;
}

function makeContract(definition: ContractDefinition): PlatformHttpContract {
  const idempotency: PlatformHttpIdempotency = definition.idempotency
    ? {
        required: true,
        source: definition.idempotency.source ?? "HEADER",
        headerName:
          (definition.idempotency.source ?? "HEADER") === "HEADER"
            ? "Idempotency-Key"
            : null,
        keyFormat: definition.idempotency.keyFormat,
        replayBehavior:
          "Same key and canonical payload hash returns the original result; a different payload returns HTTP 409.",
        payloadConflictHttpStatus: 409,
      }
    : {
        required: false,
        source: "NONE",
        headerName: null,
        keyFormat: null,
        replayBehavior: "Read-only request; no business-side deduplication key.",
        payloadConflictHttpStatus: 409,
      };

  const requestProperties: Record<string, PlatformJsonSchema> = {
    headers: requestHeadersSchema(definition.auth, idempotency),
  };
  const requestRequired = ["headers"];
  if (definition.params) {
    requestProperties.params = definition.params;
    requestRequired.push("params");
  }
  if (definition.query) {
    requestProperties.query = definition.query;
    requestRequired.push("query");
  }
  if (definition.body) {
    requestProperties.body = definition.body;
    requestRequired.push("body");
  }

  const requestExample: Record<string, unknown> = {
    headers: requestHeaderExample(definition.auth, idempotency),
    ...(definition.requestExample ?? {}),
  };
  const firstErrorCode = definition.errors[0] ?? "VALIDATION_ERROR";
  const firstError = PLATFORM_ERROR_REGISTRY[firstErrorCode];

  return {
    operationId: definition.operationId,
    system: definition.system,
    visibility: definition.visibility,
    method: definition.method,
    path: definition.path,
    owner: definition.system,
    producer:
      definition.producer ?? definition.system + ".http-api",
    consumer: definition.consumer,
    audience: definition.audience,
    auth: definition.auth,
    idempotency,
    request: {
      contentType: "application/json",
      schema: {
        $schema: PLATFORM_HTTP_SCHEMAS.JsonSchemaDialect,
        ...schema.object(requestProperties, requestRequired),
      },
    },
    response: {
      successStatus: definition.successStatus,
      successSchema: {
        $schema: PLATFORM_HTTP_SCHEMAS.JsonSchemaDialect,
        ...successSchema(definition.responseData),
      },
      errorSchema: {
        $schema: PLATFORM_HTTP_SCHEMAS.JsonSchemaDialect,
        ...errorSchema(definition.errors),
      },
    },
    errors: definition.errors.map((code) => ({
      code,
      ...PLATFORM_ERROR_REGISTRY[code],
    })),
    examples: {
      success: {
        request: requestExample,
        response: {
          data: definition.responseExample,
          requestId: "request_contract_example_001",
          traceId: "trace_contract_example_001",
        },
      },
      failure: {
        request: requestExample,
        response: {
          code: firstErrorCode,
          message: firstError.description,
          retryable: firstError.retryable,
          requestId: "request_contract_example_001",
          traceId: "trace_contract_example_001",
          fieldErrors: [],
        },
      },
    },
    sourceRefs: definition.sourceRefs,
  };
}

const nullableId = PLATFORM_HTTP_SCHEMAS.NullableId;
const version = PLATFORM_HTTP_SCHEMAS.PositiveVersion;
const time = PLATFORM_HTTP_SCHEMAS.IsoDateTime;
const money = PLATFORM_HTTP_SCHEMAS.MoneyFen;
const cursorQuery = schema.object(
  {
    cursor: PLATFORM_HTTP_SCHEMAS.Cursor,
    limit: schema.integer({ minimum: 1, maximum: 200, default: 20 }),
  },
  [],
);

const pageInfo = schema.object(
  {
    nextCursor: PLATFORM_HTTP_SCHEMAS.Cursor,
    hasMore: schema.boolean(),
  },
  ["nextCursor", "hasMore"],
);

function pageOf(item: PlatformJsonSchema): PlatformJsonSchema {
  return schema.object(
    {
      items: schema.array(item),
      pageInfo,
    },
    ["items", "pageInfo"],
  );
}

const COMMON_USER_ERRORS = [
  "AUTH_REQUIRED",
  "FORBIDDEN",
  "TENANT_SCOPE_VIOLATION",
  "VALIDATION_ERROR",
] as const satisfies readonly PlatformErrorCode[];

const COMMON_SERVICE_ERRORS = [
  "FORBIDDEN",
  "TENANT_SCOPE_VIOLATION",
  "VALIDATION_ERROR",
  "DEPENDENCY_UNAVAILABLE",
] as const satisfies readonly PlatformErrorCode[];

const CONTRACTS: PlatformHttpContract[] = [];

function register(
  definitions: readonly ContractDefinition[],
): void {
  CONTRACTS.push(...definitions.map(makeContract));
}

// SYS-01 — identity, enterprise context, authorization and agent control plane.
register([
  {
    operationId: "sys01.auth.sendPhoneCode",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/auth/phone/code",
    consumer: ["workbench-web", "mall-web", "opc-mobile", "admin-web"],
    audience: ["public-auth"],
    auth: PUBLIC_AUTH,
    idempotency: {
      keyFormat: "PHONE_CODE:{phoneHash}:{purpose}:{timeWindow}",
    },
    body: schema.object({
      phone: schema.string({ pattern: "^\\+?[1-9][0-9]{7,14}$" }),
      purpose: schema.enum(["LOGIN", "BIND_PHONE", "STRONG_AUTH"]),
    }),
    requestExample: {
      body: { phone: "+8613800000000", purpose: "LOGIN" },
    },
    responseData: schema.object({
      retryAfterSeconds: schema.integer({ minimum: 0 }),
      expiresAt: time,
    }),
    responseExample: {
      retryAfterSeconds: 60,
      expiresAt: "2026-08-10T02:05:00Z",
    },
    successStatus: 202,
    errors: ["VALIDATION_ERROR", "RATE_LIMITED", "DEPENDENCY_UNAVAILABLE"],
    sourceRefs: ["SYS-01 PRD 9.1 auth/phone/code"],
  },
  {
    operationId: "sys01.auth.createPhoneSession",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/auth/phone/session",
    consumer: ["workbench-web", "mall-web", "opc-mobile", "admin-web"],
    audience: ["public-auth"],
    auth: PUBLIC_AUTH,
    idempotency: {
      keyFormat: "PHONE_SESSION:{phoneHash}:{clientType}:{clientRequestId}",
    },
    body: schema.object(
      {
        phone: schema.string({ pattern: "^\\+?[1-9][0-9]{7,14}$" }),
        code: schema.string({ pattern: "^[0-9]{4,8}$" }),
        clientType: schema.enum(["WORKBENCH", "MALL", "OPC", "ADMIN"]),
        returnUrl: schema.nullableString({ pattern: "^/(?!/).*$" }),
        clientRequestId: schema.id("req_"),
      },
      ["phone", "code", "clientType", "returnUrl", "clientRequestId"],
    ),
    requestExample: {
      body: {
        phone: "+8613800000000",
        code: "123456",
        clientType: "MALL",
        returnUrl: "/mall/orders",
        clientRequestId: "req_login_001",
      },
    },
    responseData: schema.object({
      user: schema.object({
        userId: schema.id("usr_"),
        phoneMasked: schema.string(),
      }),
      session: schema.object({
        accessToken: schema.string(),
        refreshToken: schema.string(),
        expiresAt: time,
      }),
      nextRoute: schema.string({ pattern: "^/(?!/).*$" }),
    }),
    responseExample: {
      user: { userId: "usr_001", phoneMasked: "138****0000" },
      session: {
        accessToken: "<access-token>",
        refreshToken: "<refresh-token>",
        expiresAt: "2026-08-10T04:00:00Z",
      },
      nextRoute: "/mall/orders",
    },
    successStatus: 201,
    errors: ["VALIDATION_ERROR", "IDEMPOTENCY_CONFLICT", "RATE_LIMITED"],
    sourceRefs: ["SYS-01 PRD 9.1 auth/phone/session", "SYS-02 PRD 9.1 unified consumer login"],
  },
  {
    operationId: "sys01.identity.getMyContext",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/me/context",
    consumer: ["workbench-web", "mall-web", "opc-mobile", "admin-web"],
    audience: ["authenticated-user"],
    auth: actorAuth(["AUTHENTICATED_USER"], ["identity.context.read"]),
    responseData: schema.object({
      userId: schema.id("usr_"),
      enterpriseId: nullableId,
      profileVersion: schema.nullableInteger({ minimum: 1 }),
      roles: schema.array(schema.string()),
      permissions: schema.array(schema.string()),
      nextRoute: schema.string({ pattern: "^/(?!/).*$" }),
    }),
    responseExample: {
      userId: "usr_001",
      enterpriseId: "ent_001",
      profileVersion: 3,
      roles: ["ENTERPRISE_ADMIN"],
      permissions: ["enterprise.profile.read"],
      nextRoute: "/workbench",
    },
    successStatus: 200,
    errors: ["AUTH_REQUIRED", "ENTERPRISE_INIT_REQUIRED"],
    sourceRefs: ["SYS-01 PRD 9.1 me/context"],
  },
  {
    operationId: "sys01.enterprise.create",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/enterprises",
    consumer: ["workbench-web"],
    audience: ["authenticated-user"],
    auth: actorAuth(["AUTHENTICATED_USER"], ["enterprise.create"]),
    idempotency: {
      keyFormat: "ENTERPRISE_CREATE:{userId}:{requestId}",
    },
    body: schema.object({
      requestId: schema.id("req_"),
      name: schema.string({ minLength: 2, maxLength: 120 }),
      industryCode: schema.string({ minLength: 1, maxLength: 64 }),
      mainProducts: schema.array(schema.string({ minLength: 1 }), {
        minItems: 1,
        maxItems: 20,
      }),
      operationModel: schema.enum(["SELF_OPERATED", "MERCHANT", "HYBRID"]),
      contactName: schema.string({ minLength: 1, maxLength: 80 }),
    }),
    requestExample: {
      body: {
        requestId: "req_enterprise_001",
        name: "示例企业",
        industryCode: "RETAIL",
        mainProducts: ["茶叶"],
        operationModel: "MERCHANT",
        contactName: "张三",
      },
    },
    responseData: schema.object({
      enterpriseId: schema.id("ent_"),
      profileId: schema.id("epr_"),
      profileVersion: version,
      reviewStatus: schema.enum(["NOT_SUBMITTED"]),
    }),
    responseExample: {
      enterpriseId: "ent_001",
      profileId: "epr_001",
      profileVersion: 1,
      reviewStatus: "NOT_SUBMITTED",
    },
    successStatus: 201,
    errors: [...COMMON_USER_ERRORS, "IDEMPOTENCY_CONFLICT", "ENTERPRISE_INIT_REQUIRED"],
    sourceRefs: ["SYS-01 PRD 9.1 enterprises"],
  },
  {
    operationId: "sys01.enterprise.getProfile",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/enterprises/{enterpriseId}/profile",
    consumer: ["workbench-web", "admin-web"],
    audience: ["enterprise-member", "platform-operator"],
    auth: actorAuth(
      ["ENTERPRISE_MEMBER", "PLATFORM_OPERATOR"],
      ["enterprise.profile.read"],
    ),
    params: schema.object({
      enterpriseId: schema.id("ent_"),
    }),
    requestExample: {
      params: { enterpriseId: "ent_001" },
    },
    responseData: schema.object({
      enterpriseId: schema.id("ent_"),
      profileId: schema.id("epr_"),
      version,
      industryCode: schema.string(),
      mainProducts: schema.array(schema.string()),
      status: schema.enum(["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED"]),
      syncStatus: schema.enum(["CURRENT", "PENDING", "FAILED"]),
    }),
    responseExample: {
      enterpriseId: "ent_001",
      profileId: "epr_001",
      version: 3,
      industryCode: "RETAIL",
      mainProducts: ["茶叶"],
      status: "APPROVED",
      syncStatus: "CURRENT",
    },
    successStatus: 200,
    errors: [...COMMON_USER_ERRORS, "OBJECT_NOT_FOUND"],
    sourceRefs: ["SYS-01 PRD 9.1 enterprise profile"],
  },
  {
    operationId: "sys01.enterprise.updateProfile",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "PUT",
    path: "/api/v1/enterprises/{enterpriseId}/profile",
    consumer: ["workbench-web"],
    audience: ["enterprise-admin"],
    auth: actorAuth(["ENTERPRISE_ADMIN"], ["enterprise.profile.write"]),
    idempotency: {
      keyFormat: "ENTERPRISE_PROFILE:{enterpriseId}:{expectedVersion}:{requestId}",
    },
    params: schema.object({
      enterpriseId: schema.id("ent_"),
    }),
    body: schema.object(
      {
        expectedVersion: version,
        industryCode: schema.string({ minLength: 1, maxLength: 64 }),
        mainProducts: schema.array(schema.string({ minLength: 1 }), {
          minItems: 1,
          maxItems: 20,
        }),
        reason: schema.string({ minLength: 2, maxLength: 500 }),
      },
      ["expectedVersion", "industryCode", "mainProducts", "reason"],
    ),
    requestExample: {
      params: { enterpriseId: "ent_001" },
      body: {
        expectedVersion: 3,
        industryCode: "RETAIL",
        mainProducts: ["茶叶", "茶具"],
        reason: "新增主营产品",
      },
    },
    responseData: schema.object({
      enterpriseId: schema.id("ent_"),
      profileId: schema.id("epr_"),
      version,
      snapshotHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      syncStatus: schema.enum(["PENDING"]),
    }),
    responseExample: {
      enterpriseId: "ent_001",
      profileId: "epr_001",
      version: 4,
      snapshotHash: "a".repeat(64),
      syncStatus: "PENDING",
    },
    successStatus: 200,
    errors: [...COMMON_USER_ERRORS, "VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-01 PRD 9.1 enterprise profile update"],
  },
  {
    operationId: "sys01.enterprise.submitReview",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/enterprises/{enterpriseId}/review-submissions",
    consumer: ["workbench-web"],
    audience: ["enterprise-admin"],
    auth: actorAuth(["ENTERPRISE_ADMIN"], ["enterprise.review.submit"]),
    idempotency: {
      keyFormat: "ENTERPRISE_REVIEW:{enterpriseId}:{profileVersion}",
    },
    params: schema.object({
      enterpriseId: schema.id("ent_"),
    }),
    body: schema.object(
      {
        profileVersion: version,
        previousSubmissionId: nullableId,
        statement: schema.string({ minLength: 1, maxLength: 2000 }),
        evidenceRefs: schema.array(schema.id("evd_"), { maxItems: 50 }),
      },
      ["profileVersion", "previousSubmissionId", "statement", "evidenceRefs"],
    ),
    requestExample: {
      params: { enterpriseId: "ent_001" },
      body: {
        profileVersion: 4,
        previousSubmissionId: null,
        statement: "提交企业资料审核",
        evidenceRefs: ["evd_001"],
      },
    },
    responseData: schema.object({
      reviewSubmissionId: schema.id("ers_"),
      reviewStatus: schema.enum(["SUBMITTED"]),
      submissionVersion: version,
    }),
    responseExample: {
      reviewSubmissionId: "ers_001",
      reviewStatus: "SUBMITTED",
      submissionVersion: 1,
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "REVIEW_SUBMISSION_CONFLICT",
      "VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-01 PRD 9.1 review-submissions"],
  },
  {
    operationId: "sys01.enterprise.decideReview",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/admin/enterprise-review-submissions/{reviewSubmissionId}/decision",
    consumer: ["admin-web"],
    audience: ["platform-reviewer"],
    auth: actorAuth(
      ["PLATFORM_REVIEWER"],
      ["enterprise.review.decide"],
      true,
    ),
    idempotency: {
      keyFormat: "ENTERPRISE_REVIEW_DECISION:{reviewSubmissionId}:{expectedVersion}:{decision}",
    },
    params: schema.object({
      reviewSubmissionId: schema.id("ers_"),
    }),
    body: schema.object({
      decision: schema.enum(["APPROVE", "REJECT"]),
      reason: schema.string({ minLength: 2, maxLength: 1000 }),
      evidenceRefs: schema.array(schema.id("evd_"), { maxItems: 50 }),
      expectedVersion: version,
    }),
    requestExample: {
      params: { reviewSubmissionId: "ers_001" },
      body: {
        decision: "APPROVE",
        reason: "资料完整",
        evidenceRefs: ["evd_002"],
        expectedVersion: 1,
      },
    },
    responseData: schema.object({
      reviewSubmissionId: schema.id("ers_"),
      reviewStatus: schema.enum(["APPROVED", "REJECTED"]),
      decisionVersion: version,
    }),
    responseExample: {
      reviewSubmissionId: "ers_001",
      reviewStatus: "APPROVED",
      decisionVersion: 2,
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "VERSION_CONFLICT",
      "APPROVAL_AUTHORIZATION_DENIED",
    ],
    sourceRefs: ["SYS-01 PRD 9.1 enterprise review decision"],
  },
  {
    operationId: "sys01.authorization.decide",
    system: "SYS-01",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/authorization/decisions",
    consumer: ["SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-07", "SYS-08"],
    audience: ["registered-domain-services"],
    auth: serviceAuth(
      ["SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-07", "SYS-08"],
      ["authorization.decision.request"],
    ),
    idempotency: {
      keyFormat: "AUTHZ_DECISION:{approvalRef}:{actorUserId}:{stepCode}",
    },
    body: schema.object({
      approvalRef: schema.id("apr_"),
      enterpriseId: schema.id("ent_"),
      actorUserId: schema.id("usr_"),
      permissionCodes: schema.array(schema.string(), { minItems: 1 }),
      domainObjectRef: schema.string({ minLength: 3 }),
      requesterUserId: schema.id("usr_"),
      previousApproverUserIds: schema.array(schema.id("usr_")),
      occurredAt: time,
    }),
    requestExample: {
      body: {
        approvalRef: "apr_001",
        enterpriseId: "ent_001",
        actorUserId: "usr_reviewer_002",
        permissionCodes: ["withdrawal.final_review"],
        domainObjectRef: "withdrawal:wdr_001",
        requesterUserId: "usr_requester_001",
        previousApproverUserIds: ["usr_reviewer_001"],
        occurredAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      allowed: schema.boolean(),
      denyReasons: schema.array(schema.string()),
      effectiveRoles: schema.array(schema.string()),
      dataScope: schema.record(),
      authorizationVersion: version,
      expiresAt: time,
    }),
    responseExample: {
      allowed: true,
      denyReasons: [],
      effectiveRoles: ["FINANCE_REVIEWER"],
      dataScope: { enterpriseIds: ["ent_001"] },
      authorizationVersion: 12,
      expiresAt: "2026-08-10T02:05:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "APPROVAL_AUTHORIZATION_DENIED",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-01 PRD 9.1 internal authorization decisions"],
  },
  {
    operationId: "sys01.authorization.createDelegation",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/authorization/delegations",
    consumer: ["domain-bff"],
    audience: ["authenticated-user"],
    auth: actorAuth(
      ["ENTERPRISE_MEMBER", "PLATFORM_OPERATOR"],
      ["authorization.delegation.create"],
      true,
    ),
    idempotency: {
      keyFormat: "USER_DELEGATION:{sessionId}:{commandId}:{payloadHash}",
    },
    body: schema.object(
      {
        aud: schema.enum(["SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-07", "SYS-08"]),
        action: schema.string({ minLength: 3, maxLength: 120 }),
        objectType: schema.string({ minLength: 2, maxLength: 80 }),
        objectId: schema.id(),
        approvalRef: nullableId,
        commandId: schema.id("cmd_"),
        payloadHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      },
      [
        "aud",
        "action",
        "objectType",
        "objectId",
        "approvalRef",
        "commandId",
        "payloadHash",
      ],
    ),
    requestExample: {
      body: {
        aud: "SYS-02",
        action: "shipment.register",
        objectType: "Order",
        objectId: "ord_001",
        approvalRef: null,
        commandId: "cmd_ship_001",
        payloadHash: "b".repeat(64),
      },
    },
    responseData: schema.object({
      assertion: schema.string({ minLength: 32 }),
      jti: schema.id("jti_"),
      expiresAt: time,
      authorizationVersion: version,
    }),
    responseExample: {
      assertion: "<signed-user-delegation-assertion>",
      jti: "jti_001",
      expiresAt: "2026-08-10T02:05:00Z",
      authorizationVersion: 12,
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "APPROVAL_AUTHORIZATION_DENIED",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-01 PRD 9.1 authorization delegations"],
  },
  {
    operationId: "sys01.approvals.putProjection",
    system: "SYS-01",
    visibility: "INTERNAL",
    method: "PUT",
    path: "/internal/v1/approval-task-projections/{approvalRef}",
    consumer: ["SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-07", "SYS-08"],
    audience: ["approval-projection-writers"],
    auth: serviceAuth(
      ["SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-07", "SYS-08"],
      ["approval.projection.write"],
    ),
    idempotency: {
      keyFormat: "APPROVAL_PROJECTION:{approvalRef}:{sourceVersion}",
    },
    params: schema.object({
      approvalRef: schema.id("apr_"),
    }),
    body: schema.object({
      domainSystem: schema.enum(["SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-07", "SYS-08"]),
      domainObjectRef: schema.string(),
      status: schema.enum(["PENDING", "APPROVED", "REJECTED", "CANCELLED"]),
      sourceVersion: version,
      requiredPermissionCodes: schema.array(schema.string()),
      dueAt: schema.nullableString({ format: "date-time" }),
      returnRouteRef: schema.string({ pattern: "^/(?!/).*$" }),
      summary: schema.string({ maxLength: 500 }),
    }),
    requestExample: {
      params: { approvalRef: "apr_001" },
      body: {
        domainSystem: "SYS-08",
        domainObjectRef: "withdrawal:wdr_001",
        status: "PENDING",
        sourceVersion: 1,
        requiredPermissionCodes: ["withdrawal.final_review"],
        dueAt: "2026-08-11T02:00:00Z",
        returnRouteRef: "/ledger/withdrawals/wdr_001",
        summary: "提现复核",
      },
    },
    responseData: schema.object({
      approvalRef: schema.id("apr_"),
      sourceVersion: version,
      lastSyncedAt: time,
    }),
    responseExample: {
      approvalRef: "apr_001",
      sourceVersion: 1,
      lastSyncedAt: "2026-08-10T02:00:01Z",
    },
    successStatus: 200,
    errors: [...COMMON_SERVICE_ERRORS, "VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-01 PRD 9.1 approval task projections"],
  },
  {
    operationId: "sys01.agents.createRun",
    system: "SYS-01",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/agent-runs",
    consumer: ["workbench-web"],
    audience: ["enterprise-member"],
    auth: actorAuth(["ENTERPRISE_MEMBER"], ["agent.run.create"]),
    idempotency: {
      keyFormat: "AGENT_RUN:{enterpriseId}:{clientRequestId}",
    },
    body: schema.object({
      clientRequestId: schema.id("req_"),
      agentCode: schema.string({ minLength: 2, maxLength: 64 }),
      goal: schema.string({ minLength: 2, maxLength: 2000 }),
      businessRefs: schema.array(schema.string({ minLength: 3 }), {
        maxItems: 50,
      }),
    }),
    requestExample: {
      body: {
        clientRequestId: "req_agent_001",
        agentCode: "CONTENT_PUBLISHING",
        goal: "发布商品宣传内容",
        businessRefs: ["product:prd_001"],
      },
    },
    responseData: schema.object({
      agentRunId: schema.id("agr_"),
      status: schema.enum(["PREVIEW_READY", "QUOTING", "FAILED"]),
      previewVersion: schema.nullableInteger({ minimum: 1 }),
      quoteRef: nullableId,
    }),
    responseExample: {
      agentRunId: "agr_001",
      status: "PREVIEW_READY",
      previewVersion: 1,
      quoteRef: "pqt_001",
    },
    successStatus: 201,
    errors: [...COMMON_USER_ERRORS, "FEATURE_DISABLED", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-01 PRD 9.1 agent-runs"],
  },
  {
    operationId: "sys01.agents.reportToolResult",
    system: "SYS-01",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/agent-runs/{agentRunId}/tool-results",
    consumer: ["SYS-04", "SYS-05"],
    audience: ["agent-control-plane"],
    auth: serviceAuth(
      ["SYS-04", "SYS-05"],
      ["agent.tool_result.report"],
    ),
    idempotency: {
      keyFormat: "AGENT_TOOL_RESULT:{agentRunId}:{toolRunId}:{resultVersion}",
    },
    params: schema.object({
      agentRunId: schema.id("agr_"),
    }),
    body: schema.object(
      {
        toolRunId: schema.id("atr_"),
        toolCallId: nullableId,
        toolCode: schema.string(),
        domainSystem: schema.enum(["SYS-04", "SYS-05"]),
        enterpriseId: schema.id("ent_"),
        businessRefs: schema.array(schema.string()),
        inputVersion: version,
        status: schema.enum(["SUCCEEDED", "FAILED", "PARTIAL", "CANCELLED"]),
        billingPoint: schema.nullableString(),
        retryable: schema.boolean(),
        resultVersion: version,
        toolAuthorizationRef: schema.id("tau_"),
        resultSummary: schema.nullableString({ maxLength: 1000 }),
        failureCode: schema.nullableString({ maxLength: 100 }),
        reportedAt: time,
      },
      [
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
      ],
    ),
    requestExample: {
      params: { agentRunId: "agr_001" },
      body: {
        toolRunId: "atr_001",
        toolCallId: "atc_001",
        toolCode: "content.publish",
        domainSystem: "SYS-05",
        enterpriseId: "ent_001",
        businessRefs: ["publication:chp_001"],
        inputVersion: 1,
        status: "SUCCEEDED",
        billingPoint: "PUBLICATION_CONFIRMED",
        retryable: false,
        resultVersion: 1,
        toolAuthorizationRef: "tau_001",
        resultSummary: "发布确认已建立",
        failureCode: null,
        reportedAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      toolRunId: schema.id("atr_"),
      resultVersion: version,
      agentRunStatus: schema.enum(["RUNNING", "PARTIAL", "SUCCEEDED", "FAILED"]),
      agentRunVersion: version,
    }),
    responseExample: {
      toolRunId: "atr_001",
      resultVersion: 1,
      agentRunStatus: "SUCCEEDED",
      agentRunVersion: 4,
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "TOOL_AUTHORIZATION_INVALID",
      "TOOL_RESULT_VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-01 PRD 9.1 internal agent tool results"],
  },
]);

// SYS-08 — membership, points, publication charge, settlement and unified ledger.
register([
  {
    operationId: "sys08.membership.getCurrent",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/membership/current",
    consumer: ["workbench-web", "content-web"],
    audience: ["enterprise-member"],
    auth: actorAuth(["ENTERPRISE_MEMBER"], ["membership.current.read"]),
    responseData: schema.object({
      enterpriseId: schema.id("ent_"),
      planCode: schema.enum(["FREE", "BASIC", "PRO", "ENTERPRISE"]),
      planVersion: version,
      status: schema.enum(["ACTIVE", "EXPIRING", "EXPIRED", "PROCESSING"]),
      startsAt: time,
      endsAt: schema.nullableString({ format: "date-time" }),
      frozenProfitFen: money,
      benefitSummary: schema.record(),
    }),
    responseExample: {
      enterpriseId: "ent_001",
      planCode: "FREE",
      planVersion: 1,
      status: "ACTIVE",
      startsAt: "2026-07-31T16:00:00Z",
      endsAt: null,
      frozenProfitFen: 5000,
      benefitSummary: { douyinQuotaAvailable: 5 },
    },
    successStatus: 200,
    errors: ["AUTH_REQUIRED", "TENANT_SCOPE_VIOLATION", "DEPENDENCY_UNAVAILABLE"],
    sourceRefs: ["SYS-08 PRD LG-API-002"],
  },
  {
    operationId: "sys08.membership.createOrder",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/membership/orders",
    consumer: ["workbench-web"],
    audience: ["enterprise-admin"],
    auth: actorAuth(["ENTERPRISE_ADMIN"], ["membership.order.create"], true),
    idempotency: { keyFormat: "MEMBERSHIP_ORDER:{enterpriseId}:{planVersionId}:{clientRequestId}" },
    body: schema.object({
      planVersionId: schema.id("mpv_"),
      channel: schema.enum(["WECHAT", "ALIPAY"]),
      clientRequestId: schema.id("req_"),
    }),
    requestExample: {
      body: {
        planVersionId: "mpv_pro_003",
        channel: "WECHAT",
        clientRequestId: "req_membership_001",
      },
    },
    responseData: schema.object({
      membershipOrderId: schema.id("mso_"),
      paymentId: schema.id("pay_"),
      amountFen: money,
      currency: schema.enum(["CNY"]),
      status: schema.enum(["PENDING_PAYMENT"]),
      paymentParameters: schema.record(),
    }),
    responseExample: {
      membershipOrderId: "mso_001",
      paymentId: "pay_100",
      amountFen: 29900,
      currency: "CNY",
      status: "PENDING_PAYMENT",
      paymentParameters: { prepayId: "<provider-prepay-reference>" },
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "LEDGER_RULE_NOT_EFFECTIVE",
      "IDEMPOTENCY_CONFLICT",
      "PAYMENT_CHANNEL_UNAVAILABLE",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-003"],
  },
  {
    operationId: "sys08.wallet.getSummary",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/wallet/summary",
    consumer: ["workbench-web", "opc-mobile"],
    audience: ["wallet-owner"],
    auth: actorAuth(["ENTERPRISE_MEMBER", "OPC_PROVIDER"], ["wallet.summary.read"]),
    responseData: schema.object({
      ownerType: schema.enum(["ENTERPRISE", "OPC_PROVIDER"]),
      ownerId: schema.id(),
      availableFen: money,
      frozenFen: money,
      withdrawingFen: money,
      withdrawnFen: money,
      currency: schema.enum(["CNY"]),
      balanceVersion: version,
      updatedAt: time,
    }),
    responseExample: {
      ownerType: "ENTERPRISE",
      ownerId: "ent_001",
      availableFen: 100000,
      frozenFen: 5000,
      withdrawingFen: 0,
      withdrawnFen: 20000,
      currency: "CNY",
      balanceVersion: 12,
      updatedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: ["AUTH_REQUIRED", "TENANT_SCOPE_VIOLATION", "LEDGER_BALANCE_RECONCILING"],
    sourceRefs: ["SYS-08 PRD LG-API-005"],
  },
  {
    operationId: "sys08.points.createQuote",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/points/quotes",
    consumer: ["workbench-web", "agent-control-plane"],
    audience: ["enterprise-member", "authorized-agent-tool"],
    auth: actorAuth(["ENTERPRISE_MEMBER", "AUTHORIZED_AGENT_TOOL"], ["points.quote.create"]),
    idempotency: { keyFormat: "POINTS_QUOTE:{enterpriseId}:{agentRunId}:{chargeCode}:{inputVersion}" },
    body: schema.object({
      agentRunId: schema.id("agr_"),
      toolCallId: nullableId,
      chargeCode: schema.string({ minLength: 2, maxLength: 80 }),
      billingPoint: schema.string({ minLength: 2, maxLength: 80 }),
      inputVersion: version,
    }),
    requestExample: {
      body: {
        agentRunId: "agr_001",
        toolCallId: "atc_001",
        chargeCode: "CONTENT_GENERATION",
        billingPoint: "GENERATION_ACCEPTED",
        inputVersion: 1,
      },
    },
    responseData: schema.object({
      quoteId: schema.id("pqt_"),
      quoteVersion: version,
      chargeCode: schema.string(),
      estimatedPoints: schema.integer({ minimum: 0 }),
      ruleVersion: version,
      expiresAt: time,
    }),
    responseExample: {
      quoteId: "pqt_001",
      quoteVersion: 1,
      chargeCode: "CONTENT_GENERATION",
      estimatedPoints: 20,
      ruleVersion: 4,
      expiresAt: "2026-08-10T02:05:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "LEDGER_RULE_NOT_EFFECTIVE",
      "FEATURE_DISABLED",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-014"],
  },
  {
    operationId: "sys08.points.reserve",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/points/reservations",
    consumer: ["workbench-web", "agent-control-plane"],
    audience: ["enterprise-member", "authorized-agent-tool"],
    auth: actorAuth(["ENTERPRISE_MEMBER", "AUTHORIZED_AGENT_TOOL"], ["points.reserve"]),
    idempotency: { keyFormat: "POINTS_RESERVE:{agentRunId}:{chargeCode}" },
    body: schema.object({
      agentRunId: schema.id("agr_"),
      toolCallId: nullableId,
      quoteId: schema.id("pqt_"),
      quoteVersion: version,
      chargeCode: schema.string({ minLength: 2, maxLength: 80 }),
      points: schema.integer({ minimum: 0 }),
    }),
    requestExample: {
      body: {
        agentRunId: "agr_001",
        toolCallId: "atc_001",
        quoteId: "pqt_001",
        quoteVersion: 1,
        chargeCode: "CONTENT_GENERATION",
        points: 20,
      },
    },
    responseData: schema.object({
      reservationId: schema.id("ptr_"),
      status: schema.enum(["RESERVED"]),
      reservedPoints: schema.integer({ minimum: 0 }),
      expiresAt: time,
      reservationVersion: version,
    }),
    responseExample: {
      reservationId: "ptr_001",
      status: "RESERVED",
      reservedPoints: 20,
      expiresAt: "2026-08-10T02:30:00Z",
      reservationVersion: 1,
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "POINTS_INSUFFICIENT",
      "LEDGER_RULE_NOT_EFFECTIVE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-010"],
  },
  {
    operationId: "sys08.points.commitReservation",
    system: "SYS-08",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/points/reservations/{reservationId}/commit",
    consumer: ["SYS-01", "SYS-04", "SYS-05"],
    audience: ["authorized-domain-services"],
    auth: serviceAuth(["SYS-01", "SYS-04", "SYS-05"], ["points.commit"]),
    idempotency: { keyFormat: "POINTS_COMMIT:{agentRunId}:{chargeCode}" },
    params: schema.object({ reservationId: schema.id("ptr_") }),
    body: schema.object({
      agentRunId: schema.id("agr_"),
      toolCallId: nullableId,
      chargeCode: schema.string(),
      billingPoint: schema.string(),
      resultVersion: version,
      occurredAt: time,
    }),
    requestExample: {
      params: { reservationId: "ptr_001" },
      body: {
        agentRunId: "agr_001",
        toolCallId: "atc_001",
        chargeCode: "CONTENT_GENERATION",
        billingPoint: "GENERATION_ACCEPTED",
        resultVersion: 1,
        occurredAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      reservationId: schema.id("ptr_"),
      pointsEntryId: schema.id("pte_"),
      status: schema.enum(["COMMITTED"]),
      committedPoints: schema.integer({ minimum: 0 }),
    }),
    responseExample: {
      reservationId: "ptr_001",
      pointsEntryId: "pte_001",
      status: "COMMITTED",
      committedPoints: 20,
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "OBJECT_NOT_FOUND",
      "LEDGER_IDEMPOTENCY_CONFLICT",
      "VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-015 normalized internal path"],
  },
  {
    operationId: "sys08.points.releaseReservation",
    system: "SYS-08",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/points/reservations/{reservationId}/release",
    consumer: ["SYS-01", "SYS-04", "SYS-05"],
    audience: ["authorized-domain-services"],
    auth: serviceAuth(["SYS-01", "SYS-04", "SYS-05"], ["points.release"]),
    idempotency: { keyFormat: "POINTS_RELEASE:{reservationId}" },
    params: schema.object({ reservationId: schema.id("ptr_") }),
    body: schema.object({
      reasonCode: schema.string({ minLength: 2, maxLength: 80 }),
      resultVersion: version,
      occurredAt: time,
    }),
    requestExample: {
      params: { reservationId: "ptr_001" },
      body: {
        reasonCode: "TOOL_FAILED_BEFORE_BILLING_POINT",
        resultVersion: 1,
        occurredAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      reservationId: schema.id("ptr_"),
      status: schema.enum(["RELEASED"]),
      releasedPoints: schema.integer({ minimum: 0 }),
      reservationVersion: version,
    }),
    responseExample: {
      reservationId: "ptr_001",
      status: "RELEASED",
      releasedPoints: 20,
      reservationVersion: 2,
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "OBJECT_NOT_FOUND",
      "LEDGER_IDEMPOTENCY_CONFLICT",
      "VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-016 normalized internal path"],
  },
  {
    operationId: "sys08.publicationService.createOrder",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/publication-service-orders",
    consumer: ["content-web"],
    audience: ["enterprise-member"],
    auth: actorAuth(["ENTERPRISE_MEMBER"], ["publication_service.order.create"], true),
    idempotency: { keyFormat: "PUBLICATION_SERVICE_ORDER:{channelPublicationId}" },
    body: schema.object({
      publicationPlanId: schema.id("ppl_"),
      channelPublicationId: schema.id("chp_"),
      channel: schema.enum(["DOUYIN"]),
      amountFen: { const: 500, type: "integer" },
      paymentChannel: schema.enum(["WECHAT", "ALIPAY"]),
    }),
    requestExample: {
      body: {
        publicationPlanId: "ppl_001",
        channelPublicationId: "chp_dy_001",
        channel: "DOUYIN",
        amountFen: 500,
        paymentChannel: "WECHAT",
      },
    },
    responseData: schema.object({
      serviceOrderId: schema.id("pso_"),
      paymentId: schema.id("pay_"),
      amountFen: { const: 500, type: "integer" },
      status: schema.enum(["PENDING_PAYMENT"]),
      paymentParameters: schema.record(),
    }),
    responseExample: {
      serviceOrderId: "pso_001",
      paymentId: "pay_200",
      amountFen: 500,
      status: "PENDING_PAYMENT",
      paymentParameters: { prepayId: "<provider-prepay-reference>" },
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "PUBLICATION_SOURCE_INVALID",
      "IDEMPOTENCY_CONFLICT",
      "PAYMENT_CHANNEL_UNAVAILABLE",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-018", "SYS-05 PRD IF-CNT-007"],
  },
  {
    operationId: "sys08.publicationService.getOrder",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/publication-service-orders/{serviceOrderId}",
    consumer: ["content-web", "SYS-05"],
    audience: ["enterprise-member", "content-publication-service"],
    auth: actorAuth(["ENTERPRISE_MEMBER", "CONTENT_SERVICE"], ["publication_service.order.read"]),
    params: schema.object({ serviceOrderId: schema.id("pso_") }),
    requestExample: {
      params: { serviceOrderId: "pso_001" },
    },
    responseData: schema.object({
      serviceOrderId: schema.id("pso_"),
      publicationPlanId: schema.id("ppl_"),
      channelPublicationId: schema.id("chp_"),
      paymentId: schema.id("pay_"),
      amountFen: { const: 500, type: "integer" },
      status: schema.enum([
        "PENDING_PAYMENT",
        "PAID",
        "RESERVED",
        "COMMITTED",
        "REFUNDING",
        "REFUNDED",
        "CLOSED",
      ]),
      version,
    }),
    responseExample: {
      serviceOrderId: "pso_001",
      publicationPlanId: "ppl_001",
      channelPublicationId: "chp_dy_001",
      paymentId: "pay_200",
      amountFen: 500,
      status: "PAID",
      version: 2,
    },
    successStatus: 200,
    errors: [...COMMON_USER_ERRORS, "OBJECT_NOT_FOUND"],
    sourceRefs: ["SYS-08 PRD LG-API-019"],
  },
  {
    operationId: "sys08.publicationCharge.reserve",
    system: "SYS-08",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/ledger/publication-charge-reservations",
    consumer: ["SYS-05"],
    audience: ["content-publication-service"],
    auth: serviceAuth(["SYS-05"], ["ledger.publication_charge.reserve"]),
    idempotency: { keyFormat: "PUBLICATION_CHARGE:{channelPublicationId}" },
    body: schema.object(
      {
        publicationPlanId: schema.id("ppl_"),
        channelPublicationId: schema.id("chp_"),
        enterpriseId: schema.id("ent_"),
        channel: schema.enum(["DOUYIN"]),
        douyinExecutionMode: schema.enum(["ENTERPRISE_SELF", "PLATFORM_MANAGED", "OPC_RENTED"]),
        sourceType: schema.enum(["QUOTA", "SERVICE_ORDER", "AUTHORIZED_BALANCE"]),
        sourceVersion: version,
        quotaBatchId: nullableId,
        serviceOrderId: nullableId,
        paymentId: nullableId,
        authorizedBalanceRef: nullableId,
      },
      [
        "publicationPlanId",
        "channelPublicationId",
        "enterpriseId",
        "channel",
        "douyinExecutionMode",
        "sourceType",
        "sourceVersion",
        "quotaBatchId",
        "serviceOrderId",
        "paymentId",
        "authorizedBalanceRef",
      ],
    ),
    requestExample: {
      body: {
        publicationPlanId: "ppl_001",
        channelPublicationId: "chp_dy_001",
        enterpriseId: "ent_001",
        channel: "DOUYIN",
        douyinExecutionMode: "OPC_RENTED",
        sourceType: "QUOTA",
        sourceVersion: 1,
        quotaBatchId: "qtb_001",
        serviceOrderId: null,
        paymentId: null,
        authorizedBalanceRef: null,
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      chargeReservationId: schema.id("pcr_"),
      status: schema.enum(["RESERVED"]),
      sourceType: schema.enum(["QUOTA", "SERVICE_ORDER", "AUTHORIZED_BALANCE"]),
      expiresAt: time,
    }),
    responseExample: {
      accepted: true,
      chargeReservationId: "pcr_001",
      status: "RESERVED",
      sourceType: "QUOTA",
      expiresAt: "2026-08-10T03:00:00Z",
    },
    successStatus: 202,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "QUOTA_INSUFFICIENT",
      "PUBLICATION_SOURCE_INVALID",
      "LEDGER_IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: [
      "SYS-08 PRD LG-API-023",
      "SYS-05 PRD IF-CNT-007",
      "Contract freeze: replaces conflicting legacy PUB_CHARGE_RESERVE key",
    ],
  },
  {
    operationId: "sys08.distribution.resolveContext",
    system: "SYS-08",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/ledger/distribution-context:resolve",
    consumer: ["SYS-02"],
    audience: ["mall-order-service"],
    auth: serviceAuth(["SYS-02"], ["ledger.distribution_context.resolve"]),
    idempotency: {
      keyFormat: "DISTRIBUTION_CONTEXT_RESOLVE:{orderId}:{attributionId}:{requestHash}",
    },
    body: schema.object(
      {
        orderId: schema.id("ord_"),
        attributionId: schema.id("att_"),
        sellerEnterpriseId: schema.id("ent_"),
        promoterEnterpriseId: nullableId,
        orderCreatedAt: time,
        attributionRuleVersion: version,
        requestHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      },
      [
        "orderId",
        "attributionId",
        "sellerEnterpriseId",
        "promoterEnterpriseId",
        "orderCreatedAt",
        "attributionRuleVersion",
        "requestHash",
      ],
    ),
    requestExample: {
      body: {
        orderId: "ord_001",
        attributionId: "att_001",
        sellerEnterpriseId: "ent_001",
        promoterEnterpriseId: "ent_002",
        orderCreatedAt: "2026-08-10T02:00:00Z",
        attributionRuleVersion: 2,
        requestHash: "7".repeat(64),
      },
    },
    responseData: schema.object(
      {
        distributionContextVersion: version,
        distributionContextStatus: schema.enum(["RESOLVED", "PENDING_DISTRIBUTION_RULE"]),
        sellerEnterpriseId: schema.id("ent_"),
        promoterEnterpriseId: nullableId,
        membershipOwnerEnterpriseId: nullableId,
        distributionRuleVersionId: nullableId,
        distributionContextHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
        resolvedAt: time,
      },
      [
        "distributionContextVersion",
        "distributionContextStatus",
        "sellerEnterpriseId",
        "promoterEnterpriseId",
        "membershipOwnerEnterpriseId",
        "distributionRuleVersionId",
        "distributionContextHash",
        "resolvedAt",
      ],
    ),
    responseExample: {
      distributionContextVersion: 1,
      distributionContextStatus: "RESOLVED",
      sellerEnterpriseId: "ent_001",
      promoterEnterpriseId: "ent_002",
      membershipOwnerEnterpriseId: "ent_002",
      distributionRuleVersionId: "drv_003",
      distributionContextHash: "8".repeat(64),
      resolvedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "LEDGER_RULE_NOT_EFFECTIVE",
      "DISTRIBUTION_CONTEXT_PENDING",
      "LEDGER_IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-122", "SYS-02 PRD 9.1 distribution context"],
  },
  {
    operationId: "sys08.opc.createWithdrawal",
    system: "SYS-08",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/opc/withdrawals",
    consumer: ["SYS-07"],
    audience: ["opc-bff"],
    auth: serviceAuth(["SYS-07"], ["ledger.opc_withdrawal.create"], true),
    idempotency: { keyFormat: "OPC_WITHDRAWAL:{providerId}:{clientRequestId}" },
    body: schema.object({
      amountFen: schema.integer({ minimum: 1 }),
      payoutProfileRef: schema.id("ppr_"),
      clientRequestId: schema.id("req_"),
    }),
    requestExample: {
      body: {
        amountFen: 10000,
        payoutProfileRef: "ppr_001",
        clientRequestId: "req_withdraw_001",
      },
    },
    responseData: schema.object({
      withdrawalId: schema.id("wdr_"),
      providerId: schema.id("prv_"),
      amountFen: money,
      status: schema.enum(["SUBMITTED", "PENDING_INITIAL_REVIEW"]),
      version,
    }),
    responseExample: {
      withdrawalId: "wdr_001",
      providerId: "prv_001",
      amountFen: 10000,
      status: "SUBMITTED",
      version: 1,
    },
    successStatus: 201,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "WITHDRAWAL_PAYOUT_PROFILE_INVALID",
      "LEDGER_BALANCE_RECONCILING",
      "LEDGER_IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-021", "SYS-07 PRD 8.5"],
  },
  {
    operationId: "sys08.enterprise.createWithdrawal",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/withdrawals",
    consumer: ["workbench-web"],
    audience: ["enterprise-finance"],
    auth: actorAuth(["ENTERPRISE_FINANCE"], ["withdrawal.create"], true),
    idempotency: { keyFormat: "ENTERPRISE_WITHDRAWAL:{enterpriseId}:{clientRequestId}" },
    body: schema.object({
      clientRequestId: schema.id("req_"),
      amountFen: schema.integer({ minimum: 1 }),
      payoutProfileRef: schema.id("ppr_"),
      reason: schema.string({ minLength: 2, maxLength: 500 }),
    }),
    requestExample: {
      body: {
        clientRequestId: "req_enterprise_withdraw_001",
        amountFen: 100000,
        payoutProfileRef: "ppr_ent_001",
        reason: "企业经营款提现",
      },
    },
    responseData: schema.object({
      withdrawalId: schema.id("wdr_"),
      ownerType: schema.enum(["ENTERPRISE"]),
      amountFen: money,
      status: schema.enum(["SUBMITTED", "PENDING_INITIAL_REVIEW"]),
      version,
    }),
    responseExample: {
      withdrawalId: "wdr_ent_001",
      ownerType: "ENTERPRISE",
      amountFen: 100000,
      status: "PENDING_INITIAL_REVIEW",
      version: 1,
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "WITHDRAWAL_PAYOUT_PROFILE_INVALID",
      "LEDGER_BALANCE_RECONCILING",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-011"],
  },
  {
    operationId: "sys08.payment.receiveResult",
    system: "SYS-08",
    visibility: "CALLBACK",
    method: "POST",
    path: "/callbacks/v1/payments/{channel}",
    producer: "PAYMENT_PROVIDER",
    consumer: ["SYS-08.payment-adapter"],
    audience: ["ledger-payment-callback"],
    auth: CALLBACK_AUTH,
    idempotency: {
      source: "PROVIDER_EVENT",
      keyFormat: "PAYMENT_SUCCESS:{paymentId}:{channelTransactionId}",
    },
    params: schema.object({ channel: schema.enum(["WECHAT", "ALIPAY"]) }),
    body: schema.object({
      paymentBusinessType: schema.enum(["MEMBERSHIP", "PUBLICATION_SERVICE"]),
      paymentId: schema.id("pay_"),
      merchantAccountRef: schema.id("mar_"),
      channelTransactionId: schema.string({ minLength: 8, maxLength: 128 }),
      amountFen: money,
      currency: schema.enum(["CNY"]),
      status: schema.enum(["SUCCEEDED", "FAILED", "PROCESSING"]),
      occurredAt: time,
    }),
    requestExample: {
      params: { channel: "WECHAT" },
      body: {
        paymentBusinessType: "PUBLICATION_SERVICE",
        paymentId: "pay_200",
        merchantAccountRef: "mar_001",
        channelTransactionId: "wx_tx_001",
        amountFen: 500,
        currency: "CNY",
        status: "SUCCEEDED",
        occurredAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      paymentId: schema.id("pay_"),
      status: schema.enum(["SUCCEEDED", "FAILED", "PROCESSING"]),
    }),
    responseExample: {
      accepted: true,
      paymentId: "pay_200",
      status: "SUCCEEDED",
    },
    successStatus: 200,
    errors: [
      "CALLBACK_SIGNATURE_INVALID",
      "CALLBACK_PAYLOAD_MISMATCH",
      "PUBLICATION_SOURCE_INVALID",
      "TENANT_SCOPE_VIOLATION",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-201"],
  },
  {
    operationId: "sys08.refund.receiveResult",
    system: "SYS-08",
    visibility: "CALLBACK",
    method: "POST",
    path: "/callbacks/v1/refunds/{channel}",
    producer: "PAYMENT_PROVIDER",
    consumer: ["SYS-08.payment-adapter"],
    audience: ["ledger-refund-callback"],
    auth: CALLBACK_AUTH,
    idempotency: {
      source: "PROVIDER_EVENT",
      keyFormat: "REFUND_RESULT:{refundId}:{channelRefundTransactionId}",
    },
    params: schema.object({ channel: schema.enum(["WECHAT", "ALIPAY"]) }),
    body: schema.object({
      paymentBusinessType: schema.enum(["MEMBERSHIP", "PUBLICATION_SERVICE"]),
      paymentId: schema.id("pay_"),
      refundId: schema.id("rfd_"),
      channelRefundTransactionId: schema.string({ minLength: 8, maxLength: 128 }),
      amountFen: money,
      currency: schema.enum(["CNY"]),
      status: schema.enum(["SUCCEEDED", "FAILED", "PROCESSING"]),
      occurredAt: time,
    }),
    requestExample: {
      params: { channel: "WECHAT" },
      body: {
        paymentBusinessType: "PUBLICATION_SERVICE",
        paymentId: "pay_200",
        refundId: "rfd_001",
        channelRefundTransactionId: "wx_refund_001",
        amountFen: 500,
        currency: "CNY",
        status: "SUCCEEDED",
        occurredAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      refundId: schema.id("rfd_"),
      status: schema.enum(["SUCCEEDED", "FAILED", "PROCESSING"]),
    }),
    responseExample: {
      accepted: true,
      refundId: "rfd_001",
      status: "SUCCEEDED",
    },
    successStatus: 200,
    errors: [
      "CALLBACK_SIGNATURE_INVALID",
      "CALLBACK_PAYLOAD_MISMATCH",
      "PUBLICATION_SOURCE_INVALID",
      "TENANT_SCOPE_VIOLATION",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-202"],
  },
  {
    operationId: "sys08.payout.receiveResult",
    system: "SYS-08",
    visibility: "CALLBACK",
    method: "POST",
    path: "/callbacks/v1/payouts/{channel}",
    producer: "PAYOUT_PROVIDER",
    consumer: ["SYS-08.payout-adapter"],
    audience: ["ledger-payout-callback"],
    auth: CALLBACK_AUTH,
    idempotency: {
      source: "PROVIDER_EVENT",
      keyFormat: "WITHDRAW_RESULT:{withdrawalId}:{channelResultId}",
    },
    params: schema.object({ channel: schema.enum(["WECHAT", "ALIPAY"]) }),
    body: schema.object({
      withdrawalId: schema.id("wdr_"),
      channelResultId: schema.string({ minLength: 8, maxLength: 128 }),
      amountFen: money,
      currency: schema.enum(["CNY"]),
      status: schema.enum(["SUCCEEDED", "FAILED", "PROCESSING"]),
      reasonCode: schema.nullableString(),
      occurredAt: time,
    }),
    requestExample: {
      params: { channel: "WECHAT" },
      body: {
        withdrawalId: "wdr_001",
        channelResultId: "wx_payout_001",
        amountFen: 10000,
        currency: "CNY",
        status: "SUCCEEDED",
        reasonCode: null,
        occurredAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      withdrawalId: schema.id("wdr_"),
      status: schema.enum(["SUCCEEDED", "FAILED", "PROCESSING"]),
    }),
    responseExample: {
      accepted: true,
      withdrawalId: "wdr_001",
      status: "SUCCEEDED",
    },
    successStatus: 200,
    errors: [
      "CALLBACK_SIGNATURE_INVALID",
      "CALLBACK_PAYLOAD_MISMATCH",
      "WITHDRAWAL_PAYOUT_PROFILE_INVALID",
      "TENANT_SCOPE_VIOLATION",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-204"],
  },
  {
    operationId: "sys08.admin.finalReviewWithdrawal",
    system: "SYS-08",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/admin/withdrawals/{withdrawalId}/final-review",
    consumer: ["admin-web"],
    audience: ["finance-reviewer", "boss"],
    auth: actorAuth(
      ["FINANCE_REVIEWER", "BOSS"],
      ["withdrawal.final_review"],
      true,
    ),
    idempotency: { keyFormat: "WITHDRAWAL_FINAL_REVIEW:{withdrawalId}:{expectedVersion}:{decision}" },
    params: schema.object({ withdrawalId: schema.id("wdr_") }),
    body: schema.object({
      decision: schema.enum(["APPROVE", "REJECT"]),
      expectedVersion: version,
      reason: schema.string({ minLength: 2, maxLength: 1000 }),
      evidenceRefs: schema.array(schema.id("evd_"), { maxItems: 50 }),
      approvalRef: schema.id("apr_"),
    }),
    requestExample: {
      params: { withdrawalId: "wdr_001" },
      body: {
        decision: "APPROVE",
        expectedVersion: 2,
        reason: "复核通过",
        evidenceRefs: ["evd_201"],
        approvalRef: "apr_201",
      },
    },
    responseData: schema.object({
      withdrawalId: schema.id("wdr_"),
      status: schema.enum(["APPROVED_FOR_PAYOUT", "REJECTED"]),
      version,
    }),
    responseExample: {
      withdrawalId: "wdr_001",
      status: "APPROVED_FOR_PAYOUT",
      version: 3,
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "WITHDRAWAL_DUTY_CONFLICT",
      "APPROVAL_AUTHORIZATION_DENIED",
      "VERSION_CONFLICT",
      "LEDGER_BALANCE_RECONCILING",
    ],
    sourceRefs: ["SYS-08 PRD LG-API-106"],
  },
]);

// SYS-06 — read-only analytics, drill-down, export and sync operations.
register([
  {
    operationId: "sys06.analytics.getOverview",
    system: "SYS-06",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/analytics/overview",
    consumer: ["analytics-web", "workbench-web"],
    audience: ["analytics-user"],
    auth: actorAuth(
      ["ENTERPRISE_ANALYST", "PLATFORM_ANALYST", "BOSS"],
      ["analytics.overview.read"],
    ),
    query: schema.object(
      {
        period: schema.enum(["TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_30_DAYS", "CUSTOM"]),
        startAt: schema.nullableString({ format: "date-time" }),
        endAt: schema.nullableString({ format: "date-time" }),
      },
      ["period"],
    ),
    requestExample: {
      query: { period: "LAST_7_DAYS" },
    },
    responseData: schema.object({
      cards: schema.array(
        schema.object({
          metricId: schema.id("met_"),
          metricVersion: version,
          label: schema.string(),
          value: schema.integer(),
          unit: schema.enum(["FEN", "COUNT", "PERCENT", "SECONDS"]),
          healthStatus: schema.enum(["HEALTHY", "STALE", "PARTIAL", "UNAVAILABLE"]),
        }),
      ),
      dataCutoffAt: time,
      generatedAt: time,
    }),
    responseExample: {
      cards: [
        {
          metricId: "met_sales_paid",
          metricVersion: 1,
          label: "支付销售额",
          value: 9900,
          unit: "FEN",
          healthStatus: "HEALTHY",
        },
      ],
      dataCutoffAt: "2026-08-10T01:59:00Z",
      generatedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: [...COMMON_USER_ERRORS, "ANALYTICS_DATA_STALE"],
    sourceRefs: ["SYS-06 PRD 8.1 analytics overview"],
  },
  {
    operationId: "sys06.analytics.getMetric",
    system: "SYS-06",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/analytics/metrics/{metricId}",
    consumer: ["analytics-web"],
    audience: ["analytics-user"],
    auth: actorAuth(
      ["ENTERPRISE_ANALYST", "PLATFORM_ANALYST", "BOSS"],
      ["analytics.metric.read"],
    ),
    params: schema.object({ metricId: schema.id("met_") }),
    query: schema.object({
      period: schema.enum(["DAY", "WEEK", "MONTH"]),
      dimensions: schema.array(schema.enum(["STORE", "PRODUCT", "CHANNEL", "SOURCE"]), {
        maxItems: 4,
        uniqueItems: true,
      }),
    }),
    requestExample: {
      params: { metricId: "met_sales_paid" },
      query: { period: "DAY", dimensions: ["STORE"] },
    },
    responseData: schema.object({
      metricId: schema.id("met_"),
      metricVersion: version,
      numerator: schema.integer(),
      denominator: schema.nullableInteger({ minimum: 0 }),
      points: schema.array(
        schema.object({
          bucketStartAt: time,
          value: schema.integer(),
          dimensionValues: schema.record(schema.string()),
        }),
      ),
      dataCutoffAt: time,
      healthStatus: schema.enum(["HEALTHY", "STALE", "PARTIAL", "UNAVAILABLE"]),
    }),
    responseExample: {
      metricId: "met_sales_paid",
      metricVersion: 1,
      numerator: 9900,
      denominator: null,
      points: [
        {
          bucketStartAt: "2026-08-09T16:00:00Z",
          value: 9900,
          dimensionValues: { STORE: "sto_001" },
        },
      ],
      dataCutoffAt: "2026-08-10T01:59:00Z",
      healthStatus: "HEALTHY",
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "METRIC_NOT_FOUND",
      "ANALYTICS_DIMENSION_DENIED",
      "ANALYTICS_DATA_STALE",
    ],
    sourceRefs: ["SYS-06 PRD 8.1 analytics metrics"],
  },
  {
    operationId: "sys06.analytics.getMetricDetails",
    system: "SYS-06",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/analytics/metrics/{metricId}/details",
    consumer: ["analytics-web"],
    audience: ["analytics-user"],
    auth: actorAuth(
      ["ENTERPRISE_ANALYST", "PLATFORM_ANALYST", "BOSS"],
      ["analytics.metric.details.read"],
    ),
    params: schema.object({ metricId: schema.id("met_") }),
    query: schema.object(
      {
        cursor: PLATFORM_HTTP_SCHEMAS.Cursor,
        limit: schema.integer({ minimum: 1, maximum: 200 }),
        querySnapshotRef: schema.id("qsn_"),
      },
      ["limit", "querySnapshotRef"],
    ),
    requestExample: {
      params: { metricId: "met_sales_paid" },
      query: { limit: 50, querySnapshotRef: "qsn_001" },
    },
    responseData: schema.object({
      items: schema.array(
        schema.object({
          sourceSystem: schema.enum(["SYS-01", "SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-07", "SYS-08"]),
          sourceEntityId: schema.id(),
          sourceVersion: version,
          occurredAt: time,
          fields: schema.record(),
          sourceRouteRef: schema.string({ pattern: "^/(?!/).*$" }),
        }),
      ),
      nextCursor: PLATFORM_HTTP_SCHEMAS.Cursor,
      querySnapshotRef: schema.id("qsn_"),
      dataCutoffAt: time,
    }),
    responseExample: {
      items: [
        {
          sourceSystem: "SYS-02",
          sourceEntityId: "ord_001",
          sourceVersion: 2,
          occurredAt: "2026-08-10T02:00:00Z",
          fields: { paidFen: 9900 },
          sourceRouteRef: "/mall/orders/ord_001",
        },
      ],
      nextCursor: null,
      querySnapshotRef: "qsn_001",
      dataCutoffAt: "2026-08-10T01:59:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "METRIC_NOT_FOUND",
      "ANALYTICS_DIMENSION_DENIED",
    ],
    sourceRefs: ["SYS-06 PRD 8.1 metric details"],
  },
  {
    operationId: "sys06.analytics.createExport",
    system: "SYS-06",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/analytics/exports",
    consumer: ["analytics-web"],
    audience: ["analytics-user"],
    auth: actorAuth(
      ["ENTERPRISE_ANALYST", "PLATFORM_ANALYST"],
      ["analytics.export.create"],
      true,
    ),
    idempotency: { keyFormat: "ANALYTICS_EXPORT:{actorId}:{querySnapshotRef}:{fieldSetHash}" },
    body: schema.object({
      querySnapshotRef: schema.id("qsn_"),
      metricIds: schema.array(schema.id("met_"), { minItems: 1, maxItems: 50 }),
      fields: schema.array(schema.string(), { minItems: 1, maxItems: 100 }),
      format: schema.enum(["CSV", "XLSX"]),
      reason: schema.string({ minLength: 2, maxLength: 500 }),
    }),
    requestExample: {
      body: {
        querySnapshotRef: "qsn_001",
        metricIds: ["met_sales_paid"],
        fields: ["sourceEntityId", "paidFen", "occurredAt"],
        format: "XLSX",
        reason: "月度经营复盘",
      },
    },
    responseData: schema.object({
      exportId: schema.id("exp_"),
      status: schema.enum(["QUEUED"]),
      querySnapshotRef: schema.id("qsn_"),
      expiresAt: time,
    }),
    responseExample: {
      exportId: "exp_001",
      status: "QUEUED",
      querySnapshotRef: "qsn_001",
      expiresAt: "2026-08-11T02:00:00Z",
    },
    successStatus: 202,
    errors: [
      ...COMMON_USER_ERRORS,
      "EXPORT_LIMIT_EXCEEDED",
      "ANALYTICS_DATA_STALE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-06 PRD 8.1 analytics exports"],
  },
  {
    operationId: "sys06.analytics.getSyncHealth",
    system: "SYS-06",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/analytics/sync-health",
    consumer: ["analytics-web", "admin-web"],
    audience: ["analytics-user", "platform-operator"],
    auth: actorAuth(
      ["ENTERPRISE_ANALYST", "PLATFORM_OPERATOR"],
      ["analytics.sync_health.read"],
    ),
    responseData: schema.object({
      sources: schema.array(
        schema.object({
          sourceSystem: schema.enum(["SYS-01", "SYS-02", "SYS-03", "SYS-04", "SYS-05", "SYS-07", "SYS-08"]),
          status: schema.enum(["HEALTHY", "LAGGING", "FAILED", "QUARANTINED"]),
          lastCursor: schema.nullableString(),
          backlogCount: schema.integer({ minimum: 0 }),
          dataCutoffAt: schema.nullableString({ format: "date-time" }),
          lastErrorCode: schema.nullableString(),
        }),
      ),
      checkedAt: time,
    }),
    responseExample: {
      sources: [
        {
          sourceSystem: "SYS-02",
          status: "HEALTHY",
          lastCursor: "cursor_100",
          backlogCount: 0,
          dataCutoffAt: "2026-08-10T01:59:00Z",
          lastErrorCode: null,
        },
      ],
      checkedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: [...COMMON_USER_ERRORS, "DEPENDENCY_UNAVAILABLE"],
    sourceRefs: ["SYS-06 PRD 8.1 sync health"],
  },
  {
    operationId: "sys06.analytics.retrySyncJob",
    system: "SYS-06",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/analytics/sync-jobs/{syncJobId}/retry",
    consumer: ["admin-web"],
    audience: ["platform-operator"],
    auth: actorAuth(["PLATFORM_OPERATOR"], ["analytics.sync_job.retry"], true),
    idempotency: { keyFormat: "SYNC_JOB_RETRY:{syncJobId}:{checkpointVersion}" },
    params: schema.object({ syncJobId: schema.id("syj_") }),
    body: schema.object({
      checkpointVersion: version,
      reason: schema.string({ minLength: 2, maxLength: 500 }),
    }),
    requestExample: {
      params: { syncJobId: "syj_001" },
      body: { checkpointVersion: 3, reason: "依赖恢复后从检查点重试" },
    },
    responseData: schema.object({
      syncJobId: schema.id("syj_"),
      retryRunId: schema.id("syr_"),
      status: schema.enum(["QUEUED"]),
      startingCursor: schema.nullableString(),
    }),
    responseExample: {
      syncJobId: "syj_001",
      retryRunId: "syr_001",
      status: "QUEUED",
      startingCursor: "cursor_099",
    },
    successStatus: 202,
    errors: [
      ...COMMON_USER_ERRORS,
      "OBJECT_NOT_FOUND",
      "VERSION_CONFLICT",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-06 PRD 8.1 sync job retry"],
  },
]);

// SYS-07 — OPC provider identity, account pool and controlled session grants.
register([
  {
    operationId: "sys07.opc.getMe",
    system: "SYS-07",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/opc/me",
    consumer: ["opc-mobile"],
    audience: ["opc-provider"],
    auth: actorAuth(["OPC_PROVIDER"], ["opc.profile.read"]),
    responseData: schema.object({
      providerId: schema.id("prv_"),
      status: schema.enum(["DRAFT", "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "REVOKED"]),
      agreement: schema.object({
        acceptedVersion: schema.nullableInteger({ minimum: 1 }),
        currentVersion: version,
        acceptanceRequired: schema.boolean(),
      }),
      payoutProfileMasked: schema.nullableString(),
      profileVersion: version,
    }),
    responseExample: {
      providerId: "prv_001",
      status: "ACTIVE",
      agreement: {
        acceptedVersion: 2,
        currentVersion: 2,
        acceptanceRequired: false,
      },
      payoutProfileMasked: "微信商户号 ****1234",
      profileVersion: 3,
    },
    successStatus: 200,
    errors: ["AUTH_REQUIRED", "OPC_FORBIDDEN"],
    sourceRefs: ["SYS-07 PRD 8.2 opc/me"],
  },
  {
    operationId: "sys07.opc.updateProfile",
    system: "SYS-07",
    visibility: "PUBLIC",
    method: "PUT",
    path: "/api/v1/opc/me/profile",
    consumer: ["opc-mobile"],
    audience: ["opc-provider"],
    auth: actorAuth(["OPC_PROVIDER"], ["opc.profile.write"], true),
    idempotency: { keyFormat: "OPC_PROFILE:{providerId}:{expectedVersion}:{clientRequestId}" },
    body: schema.object({
      expectedVersion: version,
      clientRequestId: schema.id("req_"),
      identityEvidenceRefs: schema.array(schema.id("evd_"), { minItems: 1, maxItems: 20 }),
      contactRef: schema.id("ctc_"),
    }),
    requestExample: {
      body: {
        expectedVersion: 3,
        clientRequestId: "req_opc_profile_001",
        identityEvidenceRefs: ["evd_001"],
        contactRef: "ctc_001",
      },
    },
    responseData: schema.object({
      providerId: schema.id("prv_"),
      profileVersion: version,
      status: schema.enum(["DRAFT", "PENDING_REVIEW", "ACTIVE"]),
      identitySummaryMasked: schema.string(),
    }),
    responseExample: {
      providerId: "prv_001",
      profileVersion: 4,
      status: "PENDING_REVIEW",
      identitySummaryMasked: "张* / 110***********001",
    },
    successStatus: 200,
    errors: [
      "AUTH_REQUIRED",
      "OPC_FORBIDDEN",
      "PROFILE_VALIDATION_FAILED",
      "VERSION_CONFLICT",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-07 PRD 8.2 opc profile"],
  },
  {
    operationId: "sys07.account.create",
    system: "SYS-07",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/opc/accounts",
    consumer: ["opc-mobile"],
    audience: ["opc-provider"],
    auth: actorAuth(["OPC_PROVIDER"], ["opc.account.create"], true),
    idempotency: { keyFormat: "OPC_ACCOUNT:{providerId}:{channel}:{externalAccountHash}" },
    body: schema.object({
      channel: schema.enum(["DOUYIN"]),
      externalAccountHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      displayNameMasked: schema.string({ minLength: 1, maxLength: 100 }),
      evidenceRefs: schema.array(schema.id("evd_"), { minItems: 1, maxItems: 20 }),
    }),
    requestExample: {
      body: {
        channel: "DOUYIN",
        externalAccountHash: "6".repeat(64),
        displayNameMasked: "抖音号 ****001",
        evidenceRefs: ["evd_001"],
      },
    },
    responseData: schema.object({
      opcAccountId: schema.id("oca_"),
      channelAccountId: schema.id("cha_"),
      reviewStatus: schema.enum(["PENDING"]),
      accountVersion: version,
    }),
    responseExample: {
      opcAccountId: "oca_001",
      channelAccountId: "cha_001",
      reviewStatus: "PENDING",
      accountVersion: 1,
    },
    successStatus: 201,
    errors: [
      "AUTH_REQUIRED",
      "OPC_FORBIDDEN",
      "DUPLICATE_ACCOUNT",
      "INVALID_EVIDENCE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-07 PRD 8.2 opc accounts"],
  },
  {
    operationId: "sys07.account.pause",
    system: "SYS-07",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/opc/accounts/{opcAccountId}/pause",
    consumer: ["opc-mobile"],
    audience: ["opc-provider"],
    auth: actorAuth(["OPC_PROVIDER"], ["opc.account.pause"], true),
    idempotency: { keyFormat: "OPC_ACCOUNT_PAUSE:{opcAccountId}:{expectedVersion}" },
    params: schema.object({ opcAccountId: schema.id("oca_") }),
    body: schema.object({
      expectedVersion: version,
      reason: schema.string({ minLength: 2, maxLength: 500 }),
    }),
    requestExample: {
      params: { opcAccountId: "oca_001" },
      body: { expectedVersion: 3, reason: "暂时停止接单" },
    },
    responseData: schema.object({
      opcAccountId: schema.id("oca_"),
      status: schema.enum(["PAUSING", "PAUSED"]),
      activeAssignmentReleaseStatus: schema.enum(["NOT_REQUIRED", "RELEASING"]),
      accountVersion: version,
    }),
    responseExample: {
      opcAccountId: "oca_001",
      status: "PAUSING",
      activeAssignmentReleaseStatus: "RELEASING",
      accountVersion: 4,
    },
    successStatus: 202,
    errors: [
      "AUTH_REQUIRED",
      "OPC_FORBIDDEN",
      "ACCOUNT_NOT_USABLE",
      "VERSION_CONFLICT",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-07 PRD 8.2 account pause"],
  },
  {
    operationId: "sys07.withdrawal.createIntent",
    system: "SYS-07",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/opc/withdrawal-intents",
    consumer: ["opc-mobile"],
    audience: ["opc-provider"],
    auth: actorAuth(["OPC_PROVIDER"], ["opc.withdrawal.create"], true),
    idempotency: { keyFormat: "OPC_WITHDRAWAL:{providerId}:{clientRequestId}" },
    body: schema.object({
      clientRequestId: schema.id("req_"),
      amountFen: schema.integer({ minimum: 1 }),
      payoutProfileRef: schema.id("ppr_"),
    }),
    requestExample: {
      body: {
        clientRequestId: "req_withdraw_001",
        amountFen: 10000,
        payoutProfileRef: "ppr_001",
      },
    },
    responseData: schema.object({
      withdrawalId: schema.id("wdr_"),
      status: schema.enum(["SUBMITTED", "PENDING_INITIAL_REVIEW"]),
      amountFen: money,
    }),
    responseExample: {
      withdrawalId: "wdr_001",
      status: "SUBMITTED",
      amountFen: 10000,
    },
    successStatus: 201,
    errors: [
      "AUTH_REQUIRED",
      "OPC_FORBIDDEN",
      "WITHDRAWAL_PAYOUT_PROFILE_INVALID",
      "LEDGER_BALANCE_RECONCILING",
      "IDEMPOTENCY_CONFLICT",
      "DEPENDENCY_UNAVAILABLE",
    ],
    sourceRefs: ["SYS-07 PRD 8.2 withdrawal intents", "SYS-08 PRD LG-API-021"],
  },
  {
    operationId: "sys07.admin.decideAccountReview",
    system: "SYS-07",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/admin/opc/reviews/{reviewId}/decision",
    consumer: ["admin-web"],
    audience: ["opc-reviewer"],
    auth: actorAuth(["OPC_REVIEWER"], ["opc.review.decide"], true),
    idempotency: { keyFormat: "OPC_REVIEW_DECISION:{reviewId}:{expectedVersion}:{decision}" },
    params: schema.object({ reviewId: schema.id("opr_") }),
    body: schema.object({
      decision: schema.enum(["APPROVE", "REQUEST_MORE", "REJECT"]),
      reason: schema.string({ minLength: 2, maxLength: 1000 }),
      evidenceRefs: schema.array(schema.id("evd_"), { maxItems: 50 }),
      expectedVersion: version,
    }),
    requestExample: {
      params: { reviewId: "opr_001" },
      body: {
        decision: "APPROVE",
        reason: "账号与授权材料有效",
        evidenceRefs: ["evd_010"],
        expectedVersion: 1,
      },
    },
    responseData: schema.object({
      reviewId: schema.id("opr_"),
      status: schema.enum(["APPROVED", "MORE_INFO_REQUIRED", "REJECTED"]),
      reviewVersion: version,
    }),
    responseExample: {
      reviewId: "opr_001",
      status: "APPROVED",
      reviewVersion: 2,
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "INVALID_EVIDENCE",
      "APPROVAL_AUTHORIZATION_DENIED",
      "VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-07 PRD 8.3 admin OPC review"],
  },
  {
    operationId: "sys07.assignment.createSessionGrant",
    system: "SYS-07",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/opc/assignments/{accountAssignmentId}/session-grants",
    consumer: ["SYS-05"],
    audience: ["douyin-publication-adapter"],
    auth: serviceAuth(["SYS-05"], ["opc.session_grant.create"]),
    idempotency: { keyFormat: "SESSION_GRANT:{accountAssignmentId}:{executionId}:{nonce}" },
    params: schema.object({ accountAssignmentId: schema.id("aas_") }),
    body: schema.object({
      channelPublicationId: schema.id("chp_"),
      executionId: schema.id("exe_"),
      assignmentSnapshotVersion: version,
      requestedScopes: schema.array(schema.enum(["PUBLISH", "READ_STATUS", "DELETE_WORK"]), {
        minItems: 1,
        uniqueItems: true,
      }),
      nonce: schema.string({ minLength: 16, maxLength: 128 }),
    }),
    requestExample: {
      params: { accountAssignmentId: "aas_001" },
      body: {
        channelPublicationId: "chp_dy_001",
        executionId: "exe_001",
        assignmentSnapshotVersion: 2,
        requestedScopes: ["PUBLISH", "READ_STATUS"],
        nonce: "nonce_session_001",
      },
    },
    responseData: schema.object({
      sessionGrantId: schema.id("sgr_"),
      opaqueGrant: schema.string({ minLength: 32 }),
      expiresAt: time,
      scope: schema.array(schema.enum(["PUBLISH", "READ_STATUS", "DELETE_WORK"])),
    }),
    responseExample: {
      sessionGrantId: "sgr_001",
      opaqueGrant: "<one-time-opaque-session-grant-value>",
      expiresAt: "2026-08-10T02:05:00Z",
      scope: ["PUBLISH", "READ_STATUS"],
    },
    successStatus: 201,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "ACCOUNT_NOT_USABLE",
      "SCOPE_DENIED",
      "REPLAY_DETECTED",
      "ASSIGNMENT_RELEASED",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-07 PRD 8.4 session grants", "SYS-05 PRD IF-CNT-006"],
  },
  {
    operationId: "sys07.assignment.getStatus",
    system: "SYS-07",
    visibility: "INTERNAL",
    method: "GET",
    path: "/internal/v1/opc/assignments/{accountAssignmentId}/status",
    consumer: ["SYS-05"],
    audience: ["content-publication-service"],
    auth: serviceAuth(["SYS-05"], ["opc.assignment.status.read"]),
    params: schema.object({ accountAssignmentId: schema.id("aas_") }),
    requestExample: {
      params: { accountAssignmentId: "aas_001" },
    },
    responseData: schema.object({
      accountAssignmentId: schema.id("aas_"),
      assignmentStatus: schema.enum(["ACTIVE", "RELEASING", "RELEASED", "RISK_HOLD"]),
      authorizationStatus: schema.enum(["VALID", "REVOKED", "EXPIRED"]),
      healthStatus: schema.enum(["HEALTHY", "DEGRADED", "UNAVAILABLE"]),
      activeSessionGrantCount: schema.integer({ minimum: 0 }),
      assignmentVersion: version,
      checkedAt: time,
    }),
    responseExample: {
      accountAssignmentId: "aas_001",
      assignmentStatus: "ACTIVE",
      authorizationStatus: "VALID",
      healthStatus: "HEALTHY",
      activeSessionGrantCount: 0,
      assignmentVersion: 2,
      checkedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: [...COMMON_SERVICE_ERRORS, "OBJECT_NOT_FOUND", "ACCOUNT_NOT_USABLE"],
    sourceRefs: ["SYS-07 PRD 8.4 assignment status"],
  },
]);

// SYS-04 — marketing acquisition, CRM, real AI calling and WeChat adapters.
register([
  {
    operationId: "sys04.marketing.getContext",
    system: "SYS-04",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/marketing/context",
    consumer: ["marketing-web"],
    audience: ["marketing-user"],
    auth: actorAuth(["MARKETING_USER"], ["marketing.context.read"]),
    responseData: schema.object({
      enterpriseId: schema.id("ent_"),
      enterpriseProfileVersion: version,
      featureFlags: schema.record(schema.boolean()),
      stale: schema.boolean(),
      lastSyncedAt: time,
    }),
    responseExample: {
      enterpriseId: "ent_001",
      enterpriseProfileVersion: 4,
      featureFlags: { aiCalling: true, wechatAutoReply: false },
      stale: false,
      lastSyncedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "MARKETING_CONTEXT_UNAVAILABLE",
      "FEATURE_DISABLED",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 marketing/context"],
  },
  {
    operationId: "sys04.lead.create",
    system: "SYS-04",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/marketing/leads",
    consumer: ["marketing-web", "approved-import-worker"],
    audience: ["marketing-user"],
    auth: actorAuth(["MARKETING_USER"], ["marketing.lead.create"]),
    idempotency: { keyFormat: "LEAD_CREATE:{enterpriseId}:{sourceRecordId}:{clientRequestId}" },
    body: schema.object(
      {
        clientRequestId: schema.id("req_"),
        sourceRecordId: schema.id("src_"),
        sourceType: schema.enum(["MANUAL", "IMPORT", "CONTENT_CLICK", "ORDER_OUTCOME"]),
        contactRef: schema.id("ctc_"),
        consentStatus: schema.enum(["GRANTED", "PENDING", "DENIED"]),
        consentEvidenceRef: nullableId,
        ownerUserId: nullableId,
      },
      [
        "clientRequestId",
        "sourceRecordId",
        "sourceType",
        "contactRef",
        "consentStatus",
        "consentEvidenceRef",
        "ownerUserId",
      ],
    ),
    requestExample: {
      body: {
        clientRequestId: "req_lead_001",
        sourceRecordId: "src_001",
        sourceType: "MANUAL",
        contactRef: "ctc_001",
        consentStatus: "GRANTED",
        consentEvidenceRef: "evd_001",
        ownerUserId: "usr_sales_001",
      },
    },
    responseData: schema.object({
      leadId: schema.id("led_"),
      customerId: nullableId,
      status: schema.enum(["NEW", "PENDING_AUTHORIZATION"]),
      leadVersion: version,
    }),
    responseExample: {
      leadId: "led_001",
      customerId: "cus_001",
      status: "NEW",
      leadVersion: 1,
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "SOURCE_LICENSE_MISSING",
      "CONTACT_DETERMINISTIC_DUPLICATE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 marketing leads"],
  },
  {
    operationId: "sys04.customer.update",
    system: "SYS-04",
    visibility: "PUBLIC",
    method: "PATCH",
    path: "/api/v1/marketing/customers/{customerId}",
    consumer: ["marketing-web"],
    audience: ["marketing-user"],
    auth: actorAuth(["MARKETING_USER"], ["marketing.customer.write"]),
    idempotency: { keyFormat: "CUSTOMER_UPDATE:{customerId}:{expectedVersion}:{clientRequestId}" },
    params: schema.object({ customerId: schema.id("cus_") }),
    body: schema.object(
      {
        expectedVersion: version,
        mainStage: schema.enum(["LEAD", "CONTACTED", "QUALIFIED", "OPPORTUNITY", "WON", "LOST"]),
        ownerUserId: nullableId,
        tags: schema.array(schema.string({ maxLength: 80 }), { maxItems: 50 }),
        reason: schema.string({ minLength: 2, maxLength: 500 }),
        clientRequestId: schema.id("req_"),
      },
      [
        "expectedVersion",
        "mainStage",
        "ownerUserId",
        "tags",
        "reason",
        "clientRequestId",
      ],
    ),
    requestExample: {
      params: { customerId: "cus_001" },
      body: {
        expectedVersion: 3,
        mainStage: "QUALIFIED",
        ownerUserId: "usr_sales_001",
        tags: ["高意向"],
        reason: "完成需求确认",
        clientRequestId: "req_customer_update_001",
      },
    },
    responseData: schema.object({
      customerId: schema.id("cus_"),
      mainStage: schema.enum(["LEAD", "CONTACTED", "QUALIFIED", "OPPORTUNITY", "WON", "LOST"]),
      ownerUserId: nullableId,
      customerVersion: version,
    }),
    responseExample: {
      customerId: "cus_001",
      mainStage: "QUALIFIED",
      ownerUserId: "usr_sales_001",
      customerVersion: 4,
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "CRM_STAGE_CONFLICT",
      "VERSION_CONFLICT",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 marketing customers"],
  },
  {
    operationId: "sys04.customer.createFollowup",
    system: "SYS-04",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/marketing/customers/{customerId}/followups",
    consumer: ["marketing-web"],
    audience: ["marketing-user"],
    auth: actorAuth(["MARKETING_USER"], ["marketing.followup.create"]),
    idempotency: { keyFormat: "FOLLOWUP:{customerId}:{clientRequestId}" },
    params: schema.object({ customerId: schema.id("cus_") }),
    body: schema.object(
      {
        clientRequestId: schema.id("req_"),
        type: schema.enum(["PHONE", "WECHAT", "VISIT", "NOTE"]),
        contentSafeRef: schema.id("csr_"),
        attachmentRefs: schema.array(schema.id("att_"), { maxItems: 20 }),
        nextActionAt: schema.nullableString({ format: "date-time" }),
      },
      ["clientRequestId", "type", "contentSafeRef", "attachmentRefs", "nextActionAt"],
    ),
    requestExample: {
      params: { customerId: "cus_001" },
      body: {
        clientRequestId: "req_followup_001",
        type: "PHONE",
        contentSafeRef: "csr_001",
        attachmentRefs: [],
        nextActionAt: "2026-08-11T02:00:00Z",
      },
    },
    responseData: schema.object({
      followupId: schema.id("fup_"),
      customerId: schema.id("cus_"),
      createdAt: time,
    }),
    responseExample: {
      followupId: "fup_001",
      customerId: "cus_001",
      createdAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 201,
    errors: [...COMMON_USER_ERRORS, "TOUCH_NOT_AUTHORIZED", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-04 PRD 9.1 customer followups"],
  },
  {
    operationId: "sys04.touchPolicy.evaluate",
    system: "SYS-04",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/marketing/touch-policy/evaluate",
    consumer: ["marketing-web", "calling-worker", "wechat-worker"],
    audience: ["marketing-automation"],
    auth: actorAuth(["MARKETING_USER", "MARKETING_AUTOMATION"], ["marketing.touch.evaluate"]),
    idempotency: { keyFormat: "TOUCH_POLICY:{customerId}:{channel}:{purpose}:{evaluationBucket}" },
    body: schema.object({
      customerId: schema.id("cus_"),
      channel: schema.enum(["PHONE", "WECHAT", "SMS", "EMAIL"]),
      purpose: schema.string({ minLength: 2, maxLength: 80 }),
      campaignId: nullableId,
      proposedAt: time,
    }),
    requestExample: {
      body: {
        customerId: "cus_001",
        channel: "PHONE",
        purpose: "SALES_FOLLOWUP",
        campaignId: "cmp_001",
        proposedAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      allowed: schema.boolean(),
      reasonCodes: schema.array(schema.string()),
      policyVersion: version,
      evaluatedAt: time,
    }),
    responseExample: {
      allowed: true,
      reasonCodes: [],
      policyVersion: 7,
      evaluatedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "TOUCH_NOT_AUTHORIZED",
      "MARKETING_CONTEXT_UNAVAILABLE",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 touch-policy/evaluate"],
  },
  {
    operationId: "sys04.attribution.resolve",
    system: "SYS-04",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/marketing/attribution/resolve",
    consumer: ["SYS-02"],
    audience: ["mall-order-attribution"],
    auth: serviceAuth(["SYS-02"], ["marketing.attribution.resolve"]),
    idempotency: { keyFormat: "ATTRIBUTION_RESOLVE:{orderId}:{inputHash}:{ruleVersion}" },
    body: schema.object(
      {
        orderId: schema.id("ord_"),
        subOrderId: schema.id("sor_"),
        customerId: nullableId,
        anonymousId: nullableId,
        productId: schema.id("prd_"),
        sellerEnterpriseId: schema.id("ent_"),
        orderCreatedAt: time,
        ruleVersion: version,
        candidateCutoffSequence: schema.integer({ minimum: 0 }),
        inputHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      },
      [
        "orderId",
        "subOrderId",
        "customerId",
        "anonymousId",
        "productId",
        "sellerEnterpriseId",
        "orderCreatedAt",
        "ruleVersion",
        "candidateCutoffSequence",
        "inputHash",
      ],
    ),
    requestExample: {
      body: {
        orderId: "ord_001",
        subOrderId: "sor_001",
        customerId: "cus_001",
        anonymousId: null,
        productId: "prd_001",
        sellerEnterpriseId: "ent_001",
        orderCreatedAt: "2026-08-10T02:00:00Z",
        ruleVersion: 2,
        candidateCutoffSequence: 100,
        inputHash: "1".repeat(64),
      },
    },
    responseData: schema.object(
      {
        resolutionId: schema.id("atr_"),
        sourceType: schema.enum(["CONTENT_CLICK", "DIRECT", "CAMPAIGN", "UNKNOWN"]),
        candidateId: nullableId,
        promoterEnterpriseId: nullableId,
        contentId: nullableId,
        channelPublicationId: nullableId,
        sellerEnterpriseId: schema.id("ent_"),
        ruleVersion: version,
        windowStartedAt: time,
        windowEndedAt: time,
        inputHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
        resultHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
        resolvedAt: time,
      },
      [
        "resolutionId",
        "sourceType",
        "candidateId",
        "promoterEnterpriseId",
        "contentId",
        "channelPublicationId",
        "sellerEnterpriseId",
        "ruleVersion",
        "windowStartedAt",
        "windowEndedAt",
        "inputHash",
        "resultHash",
        "resolvedAt",
      ],
    ),
    responseExample: {
      resolutionId: "atr_001",
      sourceType: "CONTENT_CLICK",
      candidateId: "atc_001",
      promoterEnterpriseId: "ent_002",
      contentId: "cnt_001",
      channelPublicationId: "chp_001",
      sellerEnterpriseId: "ent_001",
      ruleVersion: 2,
      windowStartedAt: "2026-08-03T02:00:00Z",
      windowEndedAt: "2026-08-10T02:00:00Z",
      inputHash: "1".repeat(64),
      resultHash: "2".repeat(64),
      resolvedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "ATTRIBUTION_FREEZE_PENDING",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 internal attribution resolve", "SYS-02 PRD 9.1 attribution consumer"],
  },
  {
    operationId: "sys04.analytics.listOutcomes",
    system: "SYS-04",
    visibility: "INTERNAL",
    method: "GET",
    path: "/internal/v1/marketing/analytics-outcomes",
    consumer: ["SYS-06"],
    audience: ["business-analytics"],
    auth: serviceAuth(["SYS-06"], ["marketing.analytics_outcome.read"]),
    query: schema.object(
      {
        afterCursor: PLATFORM_HTTP_SCHEMAS.Cursor,
        limit: schema.integer({ minimum: 1, maximum: 200 }),
        enterpriseId: schema.nullableString({ pattern: "^ent_" }),
      },
      ["limit"],
    ),
    requestExample: {
      query: { limit: 100, enterpriseId: "ent_001" },
    },
    responseData: schema.object({
      items: schema.array(
        schema.object({
          outcomeType: schema.enum(["LEAD", "CUSTOMER", "CALL", "WECHAT_HANDOFF"]),
          sourceEntityId: schema.id(),
          sourceVersion: version,
          enterpriseId: schema.id("ent_"),
          analyticsSnapshotRef: schema.id("mas_"),
          analyticsSnapshotVersion: version,
          analyticsSnapshotHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
          occurredAt: time,
        }),
      ),
      nextCursor: PLATFORM_HTTP_SCHEMAS.Cursor,
    }),
    responseExample: {
      items: [
        {
          outcomeType: "CALL",
          sourceEntityId: "cal_001",
          sourceVersion: 1,
          enterpriseId: "ent_001",
          analyticsSnapshotRef: "mas_001",
          analyticsSnapshotVersion: 1,
          analyticsSnapshotHash: "3".repeat(64),
          occurredAt: "2026-08-10T02:00:00Z",
        },
      ],
      nextCursor: "cursor_001",
    },
    successStatus: 200,
    errors: [...COMMON_SERVICE_ERRORS, "MARKETING_CONTEXT_UNAVAILABLE"],
    sourceRefs: ["SYS-04 PRD 9.1 analytics outcomes", "SYS-06 PRD 8.1 compensation"],
  },
  {
    operationId: "sys04.analytics.getOutcomeSnapshot",
    system: "SYS-04",
    visibility: "INTERNAL",
    method: "GET",
    path: "/internal/v1/marketing/analytics-outcome-snapshots/{snapshotRef}",
    consumer: ["SYS-06"],
    audience: ["business-analytics"],
    auth: serviceAuth(["SYS-06"], ["marketing.analytics_outcome_snapshot.read"]),
    params: schema.object({ snapshotRef: schema.id("mas_") }),
    query: schema.object({
      snapshotVersion: version,
      expectedHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
    }),
    requestExample: {
      params: { snapshotRef: "mas_001" },
      query: { snapshotVersion: 1, expectedHash: "3".repeat(64) },
    },
    responseData: schema.object({
      snapshotType: schema.enum(["LEAD", "CUSTOMER", "CALL", "WECHAT_HANDOFF"]),
      enterpriseId: schema.id("ent_"),
      sourceEntityId: schema.id(),
      sourceVersion: version,
      snapshotVersion: version,
      snapshotHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      occurredAt: time,
      facts: schema.record(),
    }),
    responseExample: {
      snapshotType: "CALL",
      enterpriseId: "ent_001",
      sourceEntityId: "cal_001",
      sourceVersion: 1,
      snapshotVersion: 1,
      snapshotHash: "3".repeat(64),
      occurredAt: "2026-08-10T02:00:00Z",
      facts: {
        status: "COMPLETED",
        isRealAiCall: true,
        connected: true,
        durationSeconds: 120,
        intentLevel: "HIGH",
      },
    },
    successStatus: 200,
    errors: [...COMMON_SERVICE_ERRORS, "OBJECT_NOT_FOUND", "VERSION_CONFLICT"],
    sourceRefs: ["SYS-04 PRD 9.1 analytics outcome snapshots", "SYS-06 PRD 8.1 source readback"],
  },
  {
    operationId: "sys04.calling.createAdapterTask",
    system: "SYS-04",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/adapters/ai-calling/tasks",
    consumer: ["SYS-04.calling-worker"],
    audience: ["ai-calling-adapter"],
    auth: serviceAuth(["SYS-04"], ["ai_calling.task.create"]),
    idempotency: { keyFormat: "AI_CALL_TASK:{callTaskId}" },
    body: schema.object({
      callTaskId: schema.id("clt_"),
      customerSafeRef: schema.id("csr_"),
      scriptVersionRef: schema.id("scv_"),
      lineRef: schema.id("lin_"),
      policyVersion: version,
    }),
    requestExample: {
      body: {
        callTaskId: "clt_001",
        customerSafeRef: "csr_001",
        scriptVersionRef: "scv_001",
        lineRef: "lin_001",
        policyVersion: 3,
      },
    },
    responseData: schema.object({
      callTaskId: schema.id("clt_"),
      providerTaskRef: schema.id("ptk_"),
      status: schema.enum(["ACCEPTED", "QUEUED"]),
    }),
    responseExample: {
      callTaskId: "clt_001",
      providerTaskRef: "ptk_001",
      status: "ACCEPTED",
    },
    successStatus: 202,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "CALL_CAMPAIGN_NOT_APPROVED",
      "CALL_ADAPTER_UNHEALTHY",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 adapters/ai-calling/tasks"],
  },
  {
    operationId: "sys04.calling.receiveResult",
    system: "SYS-04",
    visibility: "CALLBACK",
    method: "POST",
    path: "/callbacks/v1/ai-calling/results",
    producer: "AI_CALLING_PROVIDER",
    consumer: ["SYS-04"],
    audience: ["ai-calling-callback"],
    auth: CALLBACK_AUTH,
    idempotency: {
      source: "PROVIDER_EVENT",
      keyFormat: "AI_CALL_RESULT:{providerAccountId}:{callId}:{resultVersion}",
    },
    body: schema.object({
      callId: schema.id("cal_"),
      callTaskId: schema.id("clt_"),
      providerTaskRef: schema.id("ptk_"),
      providerAccountId: schema.id("pac_"),
      resultVersion: version,
      status: schema.enum(["COMPLETED", "FAILED", "CANCELLED"]),
      connected: schema.boolean(),
      durationSeconds: schema.integer({ minimum: 0 }),
      intentLevel: schema.nullableEnum(["LOW", "MEDIUM", "HIGH"]),
      humanFollowupRequired: schema.boolean(),
      completedAt: time,
    }),
    requestExample: {
      body: {
        callId: "cal_001",
        callTaskId: "clt_001",
        providerTaskRef: "ptk_001",
        providerAccountId: "pac_001",
        resultVersion: 1,
        status: "COMPLETED",
        connected: true,
        durationSeconds: 120,
        intentLevel: "HIGH",
        humanFollowupRequired: true,
        completedAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      callId: schema.id("cal_"),
      resultVersion: version,
    }),
    responseExample: { accepted: true, callId: "cal_001", resultVersion: 1 },
    successStatus: 200,
    errors: [
      "CALLBACK_SIGNATURE_INVALID",
      "CALLBACK_PAYLOAD_MISMATCH",
      "CALL_RESULT_INCOMPLETE",
      "TENANT_SCOPE_VIOLATION",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 callbacks/ai-calling/results"],
  },
  {
    operationId: "sys04.wechat.receiveMessage",
    system: "SYS-04",
    visibility: "CALLBACK",
    method: "POST",
    path: "/callbacks/v1/wechat/messages",
    producer: "WECHAT_PROVIDER",
    consumer: ["SYS-04"],
    audience: ["wechat-callback"],
    auth: CALLBACK_AUTH,
    idempotency: {
      source: "PROVIDER_EVENT",
      keyFormat: "WECHAT_MESSAGE:{wechatAccountId}:{messageId}",
    },
    body: schema.object({
      wechatAccountId: schema.id("wxa_"),
      messageId: schema.id("wxm_"),
      conversationRef: schema.id("wxc_"),
      customerSafeRef: schema.id("csr_"),
      messageType: schema.enum(["TEXT", "IMAGE", "VOICE", "EVENT"]),
      contentSafeRef: schema.id("csr_"),
      sentAt: time,
    }),
    requestExample: {
      body: {
        wechatAccountId: "wxa_001",
        messageId: "wxm_001",
        conversationRef: "wxc_001",
        customerSafeRef: "csr_001",
        messageType: "TEXT",
        contentSafeRef: "csr_002",
        sentAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      messageId: schema.id("wxm_"),
      action: schema.enum(["QUEUED_FOR_AUTOMATION", "HUMAN_HANDOFF", "IGNORED"]),
    }),
    responseExample: {
      accepted: true,
      messageId: "wxm_001",
      action: "HUMAN_HANDOFF",
    },
    successStatus: 200,
    errors: [
      "CALLBACK_SIGNATURE_INVALID",
      "CALLBACK_PAYLOAD_MISMATCH",
      "TENANT_SCOPE_VIOLATION",
      "WECHAT_ADAPTER_UNHEALTHY",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 callbacks/wechat/messages"],
  },
  {
    operationId: "sys04.wechat.requestHandoff",
    system: "SYS-04",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/marketing/wechat/conversations/{conversationId}/handoff",
    consumer: ["marketing-web", "wechat-worker"],
    audience: ["marketing-user"],
    auth: actorAuth(["MARKETING_USER", "MARKETING_AUTOMATION"], ["marketing.wechat.handoff"]),
    idempotency: { keyFormat: "WECHAT_HANDOFF:{conversationId}:{activeConversationVersion}" },
    params: schema.object({ conversationId: schema.id("wxc_") }),
    body: schema.object({
      reasonCode: schema.string({ minLength: 2, maxLength: 80 }),
      contextSafeRef: schema.id("csr_"),
      assigneeUserId: nullableId,
    }),
    requestExample: {
      params: { conversationId: "wxc_001" },
      body: {
        reasonCode: "CUSTOMER_REQUESTED",
        contextSafeRef: "csr_010",
        assigneeUserId: "usr_sales_001",
      },
    },
    responseData: schema.object({
      handoffRef: schema.id("whf_"),
      status: schema.enum(["REQUESTED"]),
      handoffVersion: version,
    }),
    responseExample: {
      handoffRef: "whf_001",
      status: "REQUESTED",
      handoffVersion: 1,
    },
    successStatus: 202,
    errors: [
      ...COMMON_USER_ERRORS,
      "HUMAN_HANDOFF_REQUIRED",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-04 PRD 9.1 WeChat handoff"],
  },
]);

// SYS-05 — content lifecycle, review and channel publication orchestration.
register([
  {
    operationId: "sys05.asset.createUploadSession",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/content/assets/uploads",
    consumer: ["content-web"],
    audience: ["content-operator"],
    auth: actorAuth(["CONTENT_OPERATOR"], ["content.asset.upload"]),
    idempotency: { keyFormat: "ASSET_UPLOAD:{enterpriseId}:{fileHash}" },
    body: schema.object({
      fileName: schema.string({ minLength: 1, maxLength: 255 }),
      mediaType: schema.enum(["IMAGE", "VIDEO", "AUDIO", "DOCUMENT"]),
      contentType: schema.string({ minLength: 3, maxLength: 120 }),
      sizeBytes: schema.integer({ minimum: 1 }),
      fileHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      rightsStatus: schema.enum(["OWNED", "LICENSED", "PENDING"]),
    }),
    requestExample: {
      body: {
        fileName: "cover.jpg",
        mediaType: "IMAGE",
        contentType: "image/jpeg",
        sizeBytes: 102400,
        fileHash: "4".repeat(64),
        rightsStatus: "OWNED",
      },
    },
    responseData: schema.object({
      assetId: schema.id("ast_"),
      uploadSessionId: schema.id("upl_"),
      uploadUrlRef: schema.id("url_"),
      expiresAt: time,
      scanStatus: schema.enum(["PENDING"]),
    }),
    responseExample: {
      assetId: "ast_001",
      uploadSessionId: "upl_001",
      uploadUrlRef: "url_001",
      expiresAt: "2026-08-10T02:15:00Z",
      scanStatus: "PENDING",
    },
    successStatus: 201,
    errors: [...COMMON_USER_ERRORS, "IDEMPOTENCY_CONFLICT", "DEPENDENCY_UNAVAILABLE"],
    sourceRefs: ["SYS-05 PRD 7.1 content assets uploads"],
  },
  {
    operationId: "sys05.content.create",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/content/items",
    consumer: ["content-web", "agent-control-plane"],
    audience: ["content-operator"],
    auth: actorAuth(["CONTENT_OPERATOR"], ["content.item.create"]),
    idempotency: { keyFormat: "CONTENT_CREATE:{enterpriseId}:{clientRequestId}" },
    body: schema.object({
      clientRequestId: schema.id("req_"),
      title: schema.string({ minLength: 2, maxLength: 200 }),
      factRefs: schema.array(schema.id(), { minItems: 1, maxItems: 100 }),
      assetRefs: schema.array(schema.id("ast_"), { maxItems: 50 }),
      productRefs: schema.array(schema.id("prd_"), { maxItems: 50 }),
    }),
    requestExample: {
      body: {
        clientRequestId: "req_content_001",
        title: "示例商品内容",
        factRefs: ["fact_001"],
        assetRefs: ["ast_001"],
        productRefs: ["prd_001"],
      },
    },
    responseData: schema.object({
      contentId: schema.id("cnt_"),
      masterVersionId: schema.id("mcv_"),
      masterVersion: version,
      status: schema.enum(["DRAFT"]),
    }),
    responseExample: {
      contentId: "cnt_001",
      masterVersionId: "mcv_001",
      masterVersion: 1,
      status: "DRAFT",
    },
    successStatus: 201,
    errors: [...COMMON_USER_ERRORS, "FEATURE_DISABLED", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-05 PRD 7.1 content items"],
  },
  {
    operationId: "sys05.content.update",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "PATCH",
    path: "/api/v1/content/items/{contentId}",
    consumer: ["content-web"],
    audience: ["content-operator"],
    auth: actorAuth(["CONTENT_OPERATOR"], ["content.item.write"]),
    idempotency: { keyFormat: "CONTENT_UPDATE:{contentId}:{expectedVersion}:{clientRequestId}" },
    params: schema.object({ contentId: schema.id("cnt_") }),
    body: schema.object({
      expectedVersion: version,
      clientRequestId: schema.id("req_"),
      title: schema.string({ minLength: 2, maxLength: 200 }),
      factRefs: schema.array(schema.id(), { minItems: 1, maxItems: 100 }),
      assetRefs: schema.array(schema.id("ast_"), { maxItems: 50 }),
      productRefs: schema.array(schema.id("prd_"), { maxItems: 50 }),
    }),
    requestExample: {
      params: { contentId: "cnt_001" },
      body: {
        expectedVersion: 1,
        clientRequestId: "req_content_update_001",
        title: "示例商品内容（新版）",
        factRefs: ["fact_001"],
        assetRefs: ["ast_001"],
        productRefs: ["prd_001"],
      },
    },
    responseData: schema.object({
      contentId: schema.id("cnt_"),
      masterVersionId: schema.id("mcv_"),
      masterVersion: version,
      status: schema.enum(["DRAFT"]),
    }),
    responseExample: {
      contentId: "cnt_001",
      masterVersionId: "mcv_002",
      masterVersion: 2,
      status: "DRAFT",
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "CONTENT_VERSION_LOCKED",
      "VERSION_CONFLICT",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-05 PRD 7.1 content item update"],
  },
  {
    operationId: "sys05.content.createChannelVersion",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/content/items/{contentId}/channel-versions",
    consumer: ["content-web", "agent-control-plane"],
    audience: ["content-operator"],
    auth: actorAuth(["CONTENT_OPERATOR"], ["content.channel_version.create"]),
    idempotency: { keyFormat: "CHANNEL_VERSION:{contentId}:{masterVersion}:{channel}:{clientRequestId}" },
    params: schema.object({ contentId: schema.id("cnt_") }),
    body: schema.object({
      masterVersion: version,
      channel: schema.enum(["WOTAO", "DOUYIN"]),
      generationMode: schema.enum(["AI", "COPY", "MANUAL"]),
      clientRequestId: schema.id("req_"),
    }),
    requestExample: {
      params: { contentId: "cnt_001" },
      body: {
        masterVersion: 2,
        channel: "DOUYIN",
        generationMode: "AI",
        clientRequestId: "req_channel_version_001",
      },
    },
    responseData: schema.object({
      channelVersionId: schema.id("cnv_"),
      channel: schema.enum(["WOTAO", "DOUYIN"]),
      version: version,
      status: schema.enum(["DRAFT"]),
    }),
    responseExample: {
      channelVersionId: "cnv_001",
      channel: "DOUYIN",
      version: 1,
      status: "DRAFT",
    },
    successStatus: 201,
    errors: [...COMMON_USER_ERRORS, "CONTENT_VERSION_LOCKED", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-05 PRD 7.1 channel versions"],
  },
  {
    operationId: "sys05.review.submitOrDecide",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/content/channel-versions/{channelVersionId}/reviews",
    consumer: ["content-web", "review-web"],
    audience: ["content-operator", "content-reviewer"],
    auth: actorAuth(
      ["CONTENT_OPERATOR", "CONTENT_REVIEWER"],
      ["content.review.submit", "content.review.decide"],
    ),
    idempotency: { keyFormat: "CONTENT_REVIEW:{channelVersionId}:{expectedVersion}:{action}" },
    params: schema.object({ channelVersionId: schema.id("cnv_") }),
    body: schema.object(
      {
        action: schema.enum(["SUBMIT", "APPROVE", "REJECT", "REQUEST_CHANGES"]),
        reviewId: nullableId,
        expectedVersion: version,
        comment: schema.string({ minLength: 1, maxLength: 2000 }),
        evidenceRefs: schema.array(schema.id("evd_"), { maxItems: 50 }),
      },
      ["action", "reviewId", "expectedVersion", "comment", "evidenceRefs"],
    ),
    requestExample: {
      params: { channelVersionId: "cnv_001" },
      body: {
        action: "APPROVE",
        reviewId: "crv_001",
        expectedVersion: 1,
        comment: "内容审核通过",
        evidenceRefs: ["evd_001"],
      },
    },
    responseData: schema.object({
      reviewId: schema.id("crv_"),
      status: schema.enum(["SUBMITTED", "APPROVED", "REJECTED", "CHANGES_REQUESTED"]),
      reviewVersion: version,
    }),
    responseExample: {
      reviewId: "crv_001",
      status: "APPROVED",
      reviewVersion: 2,
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "APPROVAL_AUTHORIZATION_DENIED",
      "CONTENT_VERSION_LOCKED",
      "VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-05 PRD 7.1 channel version reviews"],
  },
  {
    operationId: "sys05.publication.confirm",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/content/publication-confirmations",
    consumer: ["content-web"],
    audience: ["content-publisher"],
    auth: actorAuth(["CONTENT_PUBLISHER"], ["content.publication.confirm"], true),
    idempotency: { keyFormat: "PUBLICATION_CONFIRM:{wotaoVersionId}:{douyinVersionId}:{clientRequestId}" },
    body: schema.object({
      clientRequestId: schema.id("req_"),
      wotaoChannelVersionId: schema.id("cnv_"),
      douyinChannelVersionId: schema.id("cnv_"),
      douyinExecutionMode: schema.enum(["ENTERPRISE_SELF", "PLATFORM_MANAGED", "OPC_RENTED"]),
      accountPolicyRef: schema.id("acp_"),
      scheduledAt: schema.nullableString({ format: "date-time" }),
      chargeSourceIntent: schema.enum(["QUOTA", "SERVICE_ORDER", "AUTHORIZED_BALANCE"]),
    }),
    requestExample: {
      body: {
        clientRequestId: "req_confirm_001",
        wotaoChannelVersionId: "cnv_wtt_001",
        douyinChannelVersionId: "cnv_dy_001",
        douyinExecutionMode: "OPC_RENTED",
        accountPolicyRef: "acp_001",
        scheduledAt: null,
        chargeSourceIntent: "QUOTA",
      },
    },
    responseData: schema.object({
      confirmationId: schema.id("pcf_"),
      publicationPlanId: schema.id("ppl_"),
      channelPublications: schema.array(
        schema.object({
          channelPublicationId: schema.id("chp_"),
          channel: schema.enum(["WOTAO", "DOUYIN"]),
          status: schema.enum(["PENDING_CHARGE", "PENDING_ASSIGNMENT", "READY"]),
        }),
        { minItems: 2, maxItems: 2 },
      ),
    }),
    responseExample: {
      confirmationId: "pcf_001",
      publicationPlanId: "ppl_001",
      channelPublications: [
        { channelPublicationId: "chp_wtt_001", channel: "WOTAO", status: "READY" },
        { channelPublicationId: "chp_dy_001", channel: "DOUYIN", status: "PENDING_CHARGE" },
      ],
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "CONTENT_NOT_APPROVED",
      "APPROVAL_AUTHORIZATION_DENIED",
      "VERSION_CONFLICT",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-05 PRD 7.1 publication confirmations"],
  },
  {
    operationId: "sys05.publication.cancelPlan",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/content/publication-plans/{publicationPlanId}/cancel",
    consumer: ["content-web"],
    audience: ["content-publisher"],
    auth: actorAuth(["CONTENT_PUBLISHER"], ["content.publication.cancel"], true),
    idempotency: { keyFormat: "PUBLICATION_PLAN_CANCEL:{publicationPlanId}:{expectedVersion}" },
    params: schema.object({ publicationPlanId: schema.id("ppl_") }),
    body: schema.object({
      reason: schema.string({ minLength: 2, maxLength: 500 }),
      expectedVersion: version,
    }),
    requestExample: {
      params: { publicationPlanId: "ppl_001" },
      body: { reason: "运营取消", expectedVersion: 2 },
    },
    responseData: schema.object({
      publicationPlanId: schema.id("ppl_"),
      status: schema.enum(["CANCELLED", "PARTIALLY_CANCELLED", "STATUS_CHECKING"]),
      channelStatuses: schema.array(schema.record()),
      assignmentReleaseStatus: schema.nullableEnum(["NOT_APPLICABLE", "PENDING", "RELEASED"]),
      version,
    }),
    responseExample: {
      publicationPlanId: "ppl_001",
      status: "CANCELLED",
      channelStatuses: [],
      assignmentReleaseStatus: "PENDING",
      version: 3,
    },
    successStatus: 202,
    errors: [
      ...COMMON_USER_ERRORS,
      "PUBLICATION_STATE_CONFLICT",
      "EXECUTION_STATUS_UNKNOWN",
      "VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-05 PRD 7.1 publication plan cancel"],
  },
  {
    operationId: "sys05.publication.retry",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/content/channel-publications/{channelPublicationId}/retry",
    consumer: ["content-web"],
    audience: ["content-publisher"],
    auth: actorAuth(["CONTENT_PUBLISHER"], ["content.publication.retry"], true),
    idempotency: { keyFormat: "PUBLICATION_RETRY:{channelPublicationId}:{retryRequestId}" },
    params: schema.object({ channelPublicationId: schema.id("chp_") }),
    body: schema.object({
      retryRequestId: schema.id("req_"),
      reason: schema.string({ minLength: 2, maxLength: 500 }),
      accountPolicyRef: schema.id("acp_"),
    }),
    requestExample: {
      params: { channelPublicationId: "chp_dy_001" },
      body: {
        retryRequestId: "req_retry_001",
        reason: "修复外部依赖后重试",
        accountPolicyRef: "acp_001",
      },
    },
    responseData: schema.object({
      channelPublicationId: schema.id("chp_"),
      executionId: schema.id("exe_"),
      status: schema.enum(["QUEUED"]),
    }),
    responseExample: {
      channelPublicationId: "chp_dy_001",
      executionId: "exe_002",
      status: "QUEUED",
    },
    successStatus: 202,
    errors: [
      ...COMMON_USER_ERRORS,
      "EXECUTION_STATUS_UNKNOWN",
      "PUBLICATION_CHARGE_NOT_RESERVED",
      "ASSIGNMENT_UNAVAILABLE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-05 PRD 7.1 channel publication retry"],
  },
  {
    operationId: "sys05.publication.createVisibilityCheck",
    system: "SYS-05",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/content/channel-publications/{channelPublicationId}/visibility-checks",
    consumer: ["content-web", "verification-worker"],
    audience: ["publication-verifier"],
    auth: actorAuth(["PUBLICATION_VERIFIER"], ["content.publication.verify"], true),
    idempotency: { keyFormat: "VISIBILITY_CHECK:{channelPublicationId}:{checkpoint}:{evidenceHash}" },
    params: schema.object({ channelPublicationId: schema.id("chp_") }),
    body: schema.object(
      {
        checkpoint: schema.enum(["FIRST_VISIBLE", "PLUS_24H", "LIABILITY_REVIEW"]),
        checkedAt: time,
        result: schema.enum(["VISIBLE", "NOT_VISIBLE", "REMOVED", "UNKNOWN"]),
        method: schema.enum(["AUTOMATED", "MANUAL"]),
        evidenceRefs: schema.array(schema.id("evd_"), { minItems: 1 }),
        evidenceHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
        reviewAction: schema.nullableEnum(["CONFIRM", "REJECT"]),
        expectedVersion: version,
      },
      [
        "checkpoint",
        "checkedAt",
        "result",
        "method",
        "evidenceRefs",
        "evidenceHash",
        "reviewAction",
        "expectedVersion",
      ],
    ),
    requestExample: {
      params: { channelPublicationId: "chp_dy_001" },
      body: {
        checkpoint: "PLUS_24H",
        checkedAt: "2026-08-11T02:00:00Z",
        result: "VISIBLE",
        method: "MANUAL",
        evidenceRefs: ["evd_101"],
        evidenceHash: "5".repeat(64),
        reviewAction: "CONFIRM",
        expectedVersion: 4,
      },
    },
    responseData: schema.object({
      visibilityCheckId: schema.id("vck_"),
      qualificationStatus: schema.enum(["RECORDED", "EFFECTIVE", "FAILED", "PENDING_REVIEW"]),
      sourceVersion: version,
    }),
    responseExample: {
      visibilityCheckId: "vck_001",
      qualificationStatus: "EFFECTIVE",
      sourceVersion: 5,
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "APPROVAL_AUTHORIZATION_DENIED",
      "PUBLICATION_STATE_CONFLICT",
      "VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-05 PRD 7.1 visibility checks"],
  },
  {
    operationId: "sys05.assignment.getReleaseEligibility",
    system: "SYS-05",
    visibility: "INTERNAL",
    method: "GET",
    path: "/internal/v1/content/channel-publications/{channelPublicationId}/executions/{executionId}/assignment-release-eligibility",
    consumer: ["SYS-07"],
    audience: ["opc-assignment-service"],
    auth: serviceAuth(["SYS-07"], ["content.assignment_release_eligibility.read"]),
    params: schema.object({
      channelPublicationId: schema.id("chp_"),
      executionId: schema.id("exe_"),
    }),
    requestExample: {
      params: { channelPublicationId: "chp_dy_001", executionId: "exe_001" },
    },
    responseData: schema.object({
      accountAssignmentId: schema.id("aas_"),
      executionStatus: schema.enum(["SUCCEEDED", "FAILED", "CANCELLED", "TERMINATED", "UNKNOWN"]),
      sourceVersion: version,
      releaseEligible: schema.boolean(),
      reasonCode: schema.string(),
    }),
    responseExample: {
      accountAssignmentId: "aas_001",
      executionStatus: "SUCCEEDED",
      sourceVersion: 5,
      releaseEligible: true,
      reasonCode: "PUBLICATION_COMPLETED",
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "OBJECT_NOT_FOUND",
      "EXECUTION_STATUS_UNKNOWN",
    ],
    sourceRefs: ["SYS-05 PRD 7.1 assignment release eligibility"],
  },
]);

// SYS-03 — merchant commerce, immutable product snapshots and inventory.
register([
  {
    operationId: "sys03.access.createRequest",
    system: "SYS-03",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/commerce/access-requests",
    consumer: ["merchant-web"],
    audience: ["enterprise-admin"],
    auth: actorAuth(["ENTERPRISE_ADMIN"], ["commerce.access.request"]),
    idempotency: { keyFormat: "COMMERCE_ACCESS:{enterpriseId}:{clientRequestId}" },
    body: schema.object({
      clientRequestId: schema.id("req_"),
      requestedScope: schema.enum(["STORE", "PRODUCT", "ORDER", "FULL_COMMERCE"]),
      contactRef: schema.id("ctc_"),
      evidenceRefs: schema.array(schema.id("evd_"), { minItems: 1, maxItems: 50 }),
    }),
    requestExample: {
      body: {
        clientRequestId: "req_commerce_access_001",
        requestedScope: "FULL_COMMERCE",
        contactRef: "ctc_001",
        evidenceRefs: ["evd_001"],
      },
    },
    responseData: schema.object({
      commerceAccessId: schema.id("cma_"),
      status: schema.enum(["SUBMITTED"]),
      version,
    }),
    responseExample: {
      commerceAccessId: "cma_001",
      status: "SUBMITTED",
      version: 1,
    },
    successStatus: 201,
    errors: [...COMMON_USER_ERRORS, "COMMERCE_NOT_ENABLED", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-03 PRD 9.1 commerce access requests"],
  },
  {
    operationId: "sys03.store.create",
    system: "SYS-03",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/commerce/stores",
    consumer: ["merchant-web"],
    audience: ["enterprise-operator"],
    auth: actorAuth(["ENTERPRISE_ADMIN", "COMMERCE_OPERATOR"], ["commerce.store.create"]),
    idempotency: { keyFormat: "STORE_CREATE:{enterpriseId}:{clientRequestId}" },
    body: schema.object({
      clientRequestId: schema.id("req_"),
      name: schema.string({ minLength: 2, maxLength: 120 }),
      businessScope: schema.array(schema.string(), { minItems: 1 }),
      serviceRegionCodes: schema.array(schema.string(), { minItems: 1 }),
    }),
    requestExample: {
      body: {
        clientRequestId: "req_store_001",
        name: "示例店铺",
        businessScope: ["TEA"],
        serviceRegionCodes: ["CN"],
      },
    },
    responseData: schema.object({
      storeId: schema.id("sto_"),
      enterpriseId: schema.id("ent_"),
      status: schema.enum(["DRAFT"]),
      version,
    }),
    responseExample: {
      storeId: "sto_001",
      enterpriseId: "ent_001",
      status: "DRAFT",
      version: 1,
    },
    successStatus: 201,
    errors: [...COMMON_USER_ERRORS, "COMMERCE_NOT_ENABLED", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-03 PRD 9.1 commerce stores"],
  },
  {
    operationId: "sys03.product.create",
    system: "SYS-03",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/commerce/products",
    consumer: ["merchant-web"],
    audience: ["commerce-operator"],
    auth: actorAuth(["COMMERCE_OPERATOR"], ["commerce.product.write"]),
    idempotency: { keyFormat: "PRODUCT_CREATE:{enterpriseId}:{draftId}" },
    body: schema.object(
      {
        draftId: schema.id("pdr_"),
        storeId: schema.id("sto_"),
        title: schema.string({ minLength: 2, maxLength: 200 }),
        salesModel: schema.enum(["SELF_OPERATED", "MERCHANT", "SUPPLIER"]),
        sellerEnterpriseId: schema.id("ent_"),
        supplierId: nullableId,
        payeeType: schema.enum(["PLATFORM", "MERCHANT", "SUPPLIER"]),
        categoryCode: schema.string({ minLength: 1, maxLength: 64 }),
      },
      [
        "draftId",
        "storeId",
        "title",
        "salesModel",
        "sellerEnterpriseId",
        "supplierId",
        "payeeType",
        "categoryCode",
      ],
    ),
    requestExample: {
      body: {
        draftId: "pdr_001",
        storeId: "sto_001",
        title: "示例茶叶",
        salesModel: "MERCHANT",
        sellerEnterpriseId: "ent_001",
        supplierId: null,
        payeeType: "MERCHANT",
        categoryCode: "TEA",
      },
    },
    responseData: schema.object({
      productId: schema.id("prd_"),
      productVersion: version,
      status: schema.enum(["DRAFT"]),
    }),
    responseExample: {
      productId: "prd_001",
      productVersion: 1,
      status: "DRAFT",
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "STORE_NOT_ACTIVE",
      "COMMERCIAL_USE_NOT_CLEARED",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 commerce products"],
  },
  {
    operationId: "sys03.inventory.command",
    system: "SYS-03",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/commerce/inventories/{inventoryId}/commands",
    consumer: ["merchant-web"],
    audience: ["inventory-operator"],
    auth: actorAuth(["COMMERCE_OPERATOR"], ["commerce.inventory.command"]),
    idempotency: { keyFormat: "INVENTORY_COMMAND:{inventoryId}:{businessKey}" },
    params: schema.object({ inventoryId: schema.id("inv_") }),
    body: schema.object({
      commandType: schema.enum(["SET", "INCREASE", "DECREASE"]),
      quantity: schema.integer({ minimum: 0 }),
      businessKey: schema.string({ minLength: 8, maxLength: 160 }),
      expectedVersion: version,
      reason: schema.string({ minLength: 2, maxLength: 500 }),
    }),
    requestExample: {
      params: { inventoryId: "inv_001" },
      body: {
        commandType: "SET",
        quantity: 100,
        businessKey: "MANUAL_STOCKTAKE:20260810",
        expectedVersion: 3,
        reason: "盘点调整",
      },
    },
    responseData: schema.object({
      inventoryId: schema.id("inv_"),
      availableQuantity: schema.integer({ minimum: 0 }),
      reservedQuantity: schema.integer({ minimum: 0 }),
      version,
    }),
    responseExample: {
      inventoryId: "inv_001",
      availableQuantity: 100,
      reservedQuantity: 0,
      version: 4,
    },
    successStatus: 200,
    errors: [...COMMON_USER_ERRORS, "INVENTORY_CONFLICT", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-03 PRD 9.1 inventory commands"],
  },
  {
    operationId: "sys03.inventory.reserve",
    system: "SYS-03",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/commerce/inventory-reservations",
    consumer: ["SYS-02"],
    audience: ["mall-order-saga"],
    auth: serviceAuth(["SYS-02"], ["inventory.reserve"]),
    idempotency: { keyFormat: "INVENTORY_RESERVE:{orderId}" },
    body: schema.object({
      commandId: schema.id("cmd_"),
      orderId: schema.id("ord_"),
      subOrderId: schema.id("sor_"),
      enterpriseId: schema.id("ent_"),
      storeId: schema.id("sto_"),
      items: schema.array(
        schema.object({
          skuId: schema.id("sku_"),
          quantity: schema.integer({ minimum: 1 }),
          productVersion: version,
        }),
        { minItems: 1, maxItems: 100 },
      ),
      expiresAt: time,
      traceId: PLATFORM_HTTP_SCHEMAS.TraceId,
      actorType: schema.enum(["SERVICE"]),
    }),
    requestExample: {
      body: {
        commandId: "cmd_reserve_001",
        orderId: "ord_001",
        subOrderId: "sor_001",
        enterpriseId: "ent_001",
        storeId: "sto_001",
        items: [{ skuId: "sku_001", quantity: 1, productVersion: 3 }],
        expiresAt: "2026-08-10T02:30:00Z",
        traceId: "trace_contract_example_001",
        actorType: "SERVICE",
      },
    },
    responseData: schema.object({
      reservationId: schema.id("irs_"),
      status: schema.enum(["RESERVED"]),
      reservationVersion: version,
      expiresAt: time,
    }),
    responseExample: {
      reservationId: "irs_001",
      status: "RESERVED",
      reservationVersion: 1,
      expiresAt: "2026-08-10T02:30:00Z",
    },
    successStatus: 201,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "OUT_OF_STOCK",
      "INVENTORY_CONFLICT",
      "COMMAND_IDEMPOTENCY_PAYLOAD_MISMATCH",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 inventory reservations", "SYS-02 PRD 9.2 ReserveInventory"],
  },
  {
    operationId: "sys03.inventory.commitReservation",
    system: "SYS-03",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/commerce/inventory-reservations/{reservationId}/commit",
    consumer: ["SYS-02"],
    audience: ["mall-order-saga"],
    auth: serviceAuth(["SYS-02"], ["inventory.commit"]),
    idempotency: { keyFormat: "INVENTORY_COMMIT:{reservationId}:{paymentId}" },
    params: schema.object({ reservationId: schema.id("irs_") }),
    body: schema.object({
      commandId: schema.id("cmd_"),
      orderId: schema.id("ord_"),
      subOrderId: schema.id("sor_"),
      paymentId: schema.id("pay_"),
      orderVersion: version,
      paidAt: time,
      traceId: PLATFORM_HTTP_SCHEMAS.TraceId,
    }),
    requestExample: {
      params: { reservationId: "irs_001" },
      body: {
        commandId: "cmd_commit_001",
        orderId: "ord_001",
        subOrderId: "sor_001",
        paymentId: "pay_001",
        orderVersion: 2,
        paidAt: "2026-08-10T02:10:00Z",
        traceId: "trace_contract_example_001",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      reservationId: schema.id("irs_"),
      reservationVersion: version,
      status: schema.enum(["COMMITTING", "COMMITTED"]),
    }),
    responseExample: {
      accepted: true,
      reservationId: "irs_001",
      reservationVersion: 2,
      status: "COMMITTED",
    },
    successStatus: 202,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "INVENTORY_RESERVATION_NOT_FOUND",
      "INVENTORY_CONFLICT",
      "COMMAND_IDEMPOTENCY_PAYLOAD_MISMATCH",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 commit inventory reservation"],
  },
  {
    operationId: "sys03.inventory.releaseReservation",
    system: "SYS-03",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/commerce/commands/release-inventory-reservation",
    consumer: ["SYS-02"],
    audience: ["mall-order-saga"],
    auth: serviceAuth(["SYS-02"], ["inventory.release"]),
    idempotency: { keyFormat: "INVENTORY_RELEASE:{reservationId}:{reasonFamily}" },
    body: schema.object({
      commandId: schema.id("cmd_"),
      reservationId: schema.id("irs_"),
      orderId: schema.id("ord_"),
      reason: schema.enum([
        "USER_CANCEL",
        "EXPIRED",
        "PAYMENT_CLOSED",
        "ORDER_CREATE_FAILED",
      ]),
      orderVersion: version,
      traceId: PLATFORM_HTTP_SCHEMAS.TraceId,
    }),
    requestExample: {
      body: {
        commandId: "cmd_release_001",
        reservationId: "irs_001",
        orderId: "ord_001",
        reason: "USER_CANCEL",
        orderVersion: 2,
        traceId: "trace_contract_example_001",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      reservationId: schema.id("irs_"),
      releaseVersion: version,
      status: schema.enum(["RELEASED"]),
    }),
    responseExample: {
      accepted: true,
      reservationId: "irs_001",
      releaseVersion: 2,
      status: "RELEASED",
    },
    successStatus: 202,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "INVENTORY_RESERVATION_NOT_FOUND",
      "INVENTORY_CONFLICT",
      "COMMAND_IDEMPOTENCY_PAYLOAD_MISMATCH",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 release inventory reservation"],
  },
  {
    operationId: "sys03.product.decideAudit",
    system: "SYS-03",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/admin/commerce/product-audits/{auditId}/decision",
    consumer: ["admin-web"],
    audience: ["product-reviewer"],
    auth: actorAuth(["PRODUCT_REVIEWER"], ["commerce.product.audit.decide"], true),
    idempotency: { keyFormat: "PRODUCT_AUDIT_DECISION:{auditId}:{expectedVersion}:{decision}" },
    params: schema.object({ auditId: schema.id("pda_") }),
    body: schema.object({
      decision: schema.enum(["APPROVE", "REJECT", "REQUEST_CHANGES"]),
      fieldIssues: schema.array(
        schema.object({
          field: schema.string(),
          code: schema.string(),
          message: schema.string(),
        }),
      ),
      reason: schema.string({ minLength: 2, maxLength: 1000 }),
      expectedVersion: version,
    }),
    requestExample: {
      params: { auditId: "pda_001" },
      body: {
        decision: "APPROVE",
        fieldIssues: [],
        reason: "商品资料合规",
        expectedVersion: 1,
      },
    },
    responseData: schema.object({
      auditId: schema.id("pda_"),
      status: schema.enum(["APPROVED", "REJECTED", "CHANGES_REQUESTED"]),
      version,
    }),
    responseExample: { auditId: "pda_001", status: "APPROVED", version: 2 },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "VERSION_CONFLICT",
      "APPROVAL_AUTHORIZATION_DENIED",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 product audit decision"],
  },
  {
    operationId: "sys03.product.publish",
    system: "SYS-03",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/commerce/products/{productId}/publication-commands",
    consumer: ["merchant-web", "admin-web"],
    audience: ["commerce-operator"],
    auth: actorAuth(
      ["COMMERCE_OPERATOR", "PLATFORM_OPERATOR"],
      ["commerce.product.publish"],
      true,
    ),
    idempotency: { keyFormat: "PRODUCT_PUBLICATION:{productId}:{productVersion}:{action}" },
    params: schema.object({ productId: schema.id("prd_") }),
    body: schema.object({
      action: schema.enum(["PUBLISH", "UNPUBLISH"]),
      productVersion: version,
      confirmation: schema.boolean(),
      reason: schema.string({ minLength: 2, maxLength: 500 }),
    }),
    requestExample: {
      params: { productId: "prd_001" },
      body: {
        action: "PUBLISH",
        productVersion: 3,
        confirmation: true,
        reason: "审核通过后发布",
      },
    },
    responseData: schema.object({
      productId: schema.id("prd_"),
      productVersion: version,
      publicStatus: schema.enum(["PUBLISHED", "UNPUBLISHED"]),
      publishedProductSnapshotRef: nullableId,
      snapshotHash: schema.nullableString({ pattern: "^[a-f0-9]{64}$" }),
    }),
    responseExample: {
      productId: "prd_001",
      productVersion: 3,
      publicStatus: "PUBLISHED",
      publishedProductSnapshotRef: "pps_001",
      snapshotHash: "e".repeat(64),
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "PRODUCT_REVIEW_REQUIRED",
      "COMMERCIAL_USE_NOT_CLEARED",
      "VERSION_CONFLICT",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 product publication commands"],
  },
  {
    operationId: "sys03.product.getPublishedSnapshot",
    system: "SYS-03",
    visibility: "INTERNAL",
    method: "GET",
    path: "/internal/v1/commerce/published-product-snapshots/{snapshotRef}",
    consumer: ["SYS-02"],
    audience: ["mall-product-ingestion"],
    auth: serviceAuth(["SYS-02"], ["commerce.published_snapshot.read"]),
    params: schema.object({ snapshotRef: schema.id("pps_") }),
    query: schema.object({
      productVersion: version,
      expectedHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
    }),
    responseData: schema.object(
      {
        publishedProductSnapshotRef: schema.id("pps_"),
        snapshotHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
        productId: schema.id("prd_"),
        productVersion: version,
        enterpriseId: schema.id("ent_"),
        storeId: schema.id("sto_"),
        salesModel: schema.enum(["SELF_OPERATED", "MERCHANT", "SUPPLIER"]),
        sellerEnterpriseId: schema.id("ent_"),
        supplierId: nullableId,
        payeeType: schema.enum(["PLATFORM", "MERCHANT", "SUPPLIER"]),
        title: schema.string(),
        skuSnapshots: schema.array(schema.record(), { minItems: 1 }),
        priceSnapshots: schema.array(schema.record(), { minItems: 1 }),
        publicStatus: schema.enum(["PUBLISHED"]),
        aftersalePolicyRef: schema.id("afp_"),
        publishedAt: time,
      },
      [
        "publishedProductSnapshotRef",
        "snapshotHash",
        "productId",
        "productVersion",
        "enterpriseId",
        "storeId",
        "salesModel",
        "sellerEnterpriseId",
        "supplierId",
        "payeeType",
        "title",
        "skuSnapshots",
        "priceSnapshots",
        "publicStatus",
        "aftersalePolicyRef",
        "publishedAt",
      ],
    ),
    requestExample: {
      params: { snapshotRef: "pps_001" },
      query: { productVersion: 3, expectedHash: "e".repeat(64) },
    },
    responseExample: {
      publishedProductSnapshotRef: "pps_001",
      snapshotHash: "e".repeat(64),
      productId: "prd_001",
      productVersion: 3,
      enterpriseId: "ent_001",
      storeId: "sto_001",
      salesModel: "MERCHANT",
      sellerEnterpriseId: "ent_001",
      supplierId: null,
      payeeType: "MERCHANT",
      title: "示例茶叶",
      skuSnapshots: [{ skuId: "sku_001", skuVersion: 2, status: "ACTIVE" }],
      priceSnapshots: [{ skuId: "sku_001", salePriceFen: 9900, currency: "CNY" }],
      publicStatus: "PUBLISHED",
      aftersalePolicyRef: "afp_001",
      publishedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "OBJECT_NOT_FOUND",
      "PUBLISHED_SNAPSHOT_VERSION_MISMATCH",
      "PUBLISHED_SNAPSHOT_HASH_MISMATCH",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 published-product-snapshots", "SYS-02 PRD 9.1 snapshot consumer"],
  },
  {
    operationId: "sys03.fulfillment.create",
    system: "SYS-03",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/commerce/orders/{orderId}/fulfillments",
    consumer: ["merchant-web"],
    audience: ["fulfillment-operator"],
    auth: actorAuth(["FULFILLMENT_OPERATOR"], ["commerce.fulfillment.create"]),
    idempotency: { keyFormat: "FULFILLMENT:{orderId}:{clientRequestId}" },
    params: schema.object({ orderId: schema.id("ord_") }),
    body: schema.object({
      clientRequestId: schema.id("req_"),
      carrierCode: schema.string({ minLength: 2, maxLength: 32 }),
      trackingNo: schema.string({ minLength: 4, maxLength: 80 }),
      note: schema.nullableString({ maxLength: 500 }),
      expectedOrderVersion: version,
    }),
    requestExample: {
      params: { orderId: "ord_001" },
      body: {
        clientRequestId: "req_fulfill_001",
        carrierCode: "SF",
        trackingNo: "SF1234567890",
        note: null,
        expectedOrderVersion: 2,
      },
    },
    responseData: schema.object({
      fulfillmentId: schema.id("ful_"),
      fulfillmentVersion: version,
      syncStatus: schema.enum(["PENDING_SYS02", "REGISTERED"]),
      commandId: schema.id("cmd_"),
    }),
    responseExample: {
      fulfillmentId: "ful_001",
      fulfillmentVersion: 1,
      syncStatus: "PENDING_SYS02",
      commandId: "cmd_ship_001",
    },
    successStatus: 202,
    errors: [
      ...COMMON_USER_ERRORS,
      "ORDER_STATE_CONFLICT",
      "ORDER_INVENTORY_NOT_COMMITTED",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 order fulfillments"],
  },
  {
    operationId: "sys03.settlement.getEvidence",
    system: "SYS-03",
    visibility: "INTERNAL",
    method: "GET",
    path: "/internal/v1/commerce/orders/{orderId}/settlement-evidence",
    consumer: ["SYS-08"],
    audience: ["ledger-settlement"],
    auth: serviceAuth(["SYS-08"], ["commerce.settlement_evidence.read"]),
    params: schema.object({ orderId: schema.id("ord_") }),
    query: schema.object(
      {
        eligibilityVersion: version,
        evidenceVersion: schema.nullableInteger({ minimum: 1 }),
      },
      ["eligibilityVersion"],
    ),
    requestExample: {
      params: { orderId: "ord_001" },
      query: { eligibilityVersion: 1, evidenceVersion: 2 },
    },
    responseData: schema.object(
      {
        orderId: schema.id("ord_"),
        subOrderId: schema.id("sor_"),
        eligibilityVersion: version,
        evidenceVersion: version,
        salesModel: schema.enum(["SELF_OPERATED", "MERCHANT", "SUPPLIER"]),
        sellerEnterpriseId: schema.id("ent_"),
        storeId: schema.id("sto_"),
        supplierId: nullableId,
        payeeType: schema.enum(["PLATFORM", "MERCHANT", "SUPPLIER"]),
        payeeId: schema.id(),
        evidenceItems: schema.array(
          schema.object({
            costEvidenceId: schema.id("cev_"),
            evidenceType: schema.string(),
            payeeType: schema.enum(["PLATFORM", "MERCHANT", "SUPPLIER"]),
            payeeId: schema.id(),
            declaredAmountFen: money,
            currency: schema.enum(["CNY"]),
            sourceRef: schema.id(),
            evidenceRefs: schema.array(schema.id("evd_")),
            evidenceVersion: version,
            status: schema.enum(["DECLARED", "SUPERSEDED"]),
          }),
          { minItems: 1 },
        ),
        completenessStatus: schema.enum(["COMPLETE", "INCOMPLETE"]),
        evidenceSnapshotHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      },
      [
        "orderId",
        "subOrderId",
        "eligibilityVersion",
        "evidenceVersion",
        "salesModel",
        "sellerEnterpriseId",
        "storeId",
        "supplierId",
        "payeeType",
        "payeeId",
        "evidenceItems",
        "completenessStatus",
        "evidenceSnapshotHash",
      ],
    ),
    responseExample: {
      orderId: "ord_001",
      subOrderId: "sor_001",
      eligibilityVersion: 1,
      evidenceVersion: 2,
      salesModel: "MERCHANT",
      sellerEnterpriseId: "ent_001",
      storeId: "sto_001",
      supplierId: null,
      payeeType: "MERCHANT",
      payeeId: "ent_001",
      evidenceItems: [
        {
          costEvidenceId: "cev_001",
          evidenceType: "MERCHANT_PAYABLE",
          payeeType: "MERCHANT",
          payeeId: "ent_001",
          declaredAmountFen: 7000,
          currency: "CNY",
          sourceRef: "src_001",
          evidenceRefs: ["evd_100"],
          evidenceVersion: 2,
          status: "DECLARED",
        },
      ],
      completenessStatus: "COMPLETE",
      evidenceSnapshotHash: "f".repeat(64),
    },
    successStatus: 200,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "OBJECT_NOT_FOUND",
      "VERSION_CONFLICT",
      "COST_INCOMPLETE",
    ],
    sourceRefs: ["SYS-03 PRD 9.1 settlement evidence", "SYS-08 PRD 9.3.1"],
  },
]);

// SYS-02 — consumer mall, order aggregate and merchant-facing internal facts.
register([
  {
    operationId: "sys02.consumer.getProfile",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/mall/me/profile",
    consumer: ["mall-web"],
    audience: ["consumer"],
    auth: actorAuth(["CONSUMER"], ["mall.profile.read"]),
    responseData: schema.object({
      consumerProfileId: schema.id("cpr_"),
      userId: schema.id("usr_"),
      displayNameMasked: schema.nullableString(),
      status: schema.enum(["ACTIVE", "SUSPENDED"]),
    }),
    responseExample: {
      consumerProfileId: "cpr_001",
      userId: "usr_001",
      displayNameMasked: "张*",
      status: "ACTIVE",
    },
    successStatus: 200,
    errors: ["AUTH_REQUIRED", "TENANT_SCOPE_VIOLATION"],
    sourceRefs: ["SYS-02 PRD 9.1 mall/me/profile"],
  },
  {
    operationId: "sys02.consumer.mergeAnonymousSubject",
    system: "SYS-02",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/mall/anonymous-subjects/{anonymousId}/merge",
    consumer: ["SYS-01"],
    audience: ["trusted-login-callback"],
    auth: serviceAuth(["SYS-01", "SYS-02"], ["mall.anonymous.merge"]),
    idempotency: {
      keyFormat: "ANON_MERGE:{anonymousId}:{userId}:{mergePurpose}",
    },
    params: schema.object({
      anonymousId: schema.id("ano_"),
    }),
    body: schema.object(
      {
        userId: schema.id("usr_"),
        mergePurpose: schema.enum(["LOGIN", "CHECKOUT"]),
        expectedMergeVersion: version,
        cartDecision: schema.nullableEnum(["KEEP_USER", "KEEP_ANONYMOUS"]),
      },
      ["userId", "mergePurpose", "expectedMergeVersion", "cartDecision"],
    ),
    requestExample: {
      params: { anonymousId: "ano_001" },
      body: {
        userId: "usr_001",
        mergePurpose: "LOGIN",
        expectedMergeVersion: 1,
        cartDecision: "KEEP_USER",
      },
    },
    responseData: schema.object({
      consumerProfileId: schema.id("cpr_"),
      mergeVersion: version,
      cartMergeStatus: schema.enum(["MERGED", "UNCHANGED"]),
      attributionMergeStatus: schema.enum(["MERGED", "UNCHANGED"]),
    }),
    responseExample: {
      consumerProfileId: "cpr_001",
      mergeVersion: 2,
      cartMergeStatus: "MERGED",
      attributionMergeStatus: "MERGED",
    },
    successStatus: 200,
    errors: [...COMMON_SERVICE_ERRORS, "VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-02 PRD 9.1 anonymous subject merge"],
  },
  {
    operationId: "sys02.trial.getEligibility",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/mall/trial-eligibility",
    consumer: ["mall-web"],
    audience: ["consumer"],
    auth: actorAuth(["CONSUMER"], ["mall.trial.read"]),
    responseData: schema.object({
      canBrowse: schema.boolean(),
      canStartTransaction: schema.boolean(),
      subjectType: schema.enum(["USER", "PHONE_HASH", "INVITATION"]),
      expiresAt: schema.nullableString({ format: "date-time" }),
      reasonCode: schema.nullableString(),
    }),
    responseExample: {
      canBrowse: true,
      canStartTransaction: true,
      subjectType: "USER",
      expiresAt: "2026-08-31T16:00:00Z",
      reasonCode: null,
    },
    successStatus: 200,
    errors: ["AUTH_REQUIRED", "DEPENDENCY_UNAVAILABLE"],
    sourceRefs: ["SYS-02 PRD 9.1 trial eligibility"],
  },
  {
    operationId: "sys02.mall.getHome",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/mall/home",
    consumer: ["mall-web"],
    audience: ["public-mall"],
    auth: PUBLIC_AUTH,
    query: schema.object(
      {
        cursor: PLATFORM_HTTP_SCHEMAS.Cursor,
        regionCode: schema.nullableString({ maxLength: 32 }),
      },
      [],
    ),
    requestExample: {
      query: { cursor: null, regionCode: "CN-11" },
    },
    responseData: schema.object({
      placements: schema.array(schema.record()),
      categories: schema.array(schema.record()),
      products: schema.array(schema.record()),
      contents: schema.array(schema.record()),
      nextCursor: PLATFORM_HTTP_SCHEMAS.Cursor,
    }),
    responseExample: {
      placements: [],
      categories: [{ categoryCode: "TEA", name: "茶叶" }],
      products: [{ productId: "prd_001", title: "示例茶叶" }],
      contents: [],
      nextCursor: null,
    },
    successStatus: 200,
    errors: ["VALIDATION_ERROR", "DEPENDENCY_UNAVAILABLE"],
    sourceRefs: ["SYS-02 PRD 9.1 mall home"],
  },
  {
    operationId: "sys02.mall.getProduct",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/mall/products/{productId}",
    consumer: ["mall-web"],
    audience: ["public-mall"],
    auth: PUBLIC_AUTH,
    params: schema.object({
      productId: schema.id("prd_"),
    }),
    query: schema.object(
      {
        regionCode: schema.nullableString({ maxLength: 32 }),
      },
      [],
    ),
    requestExample: {
      params: { productId: "prd_001" },
      query: { regionCode: "CN-11" },
    },
    responseData: schema.object({
      productId: schema.id("prd_"),
      productVersion: version,
      title: schema.string(),
      storeId: schema.id("sto_"),
      salesModel: schema.enum(["SELF_OPERATED", "MERCHANT", "SUPPLIER"]),
      responsibilityLabel: schema.string(),
      skuItems: schema.array(
        schema.object({
          skuId: schema.id("sku_"),
          priceFen: money,
          currency: schema.enum(["CNY"]),
          stockStatus: schema.enum(["IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"]),
        }),
      ),
      aftersalePolicyRef: schema.id("afp_"),
    }),
    responseExample: {
      productId: "prd_001",
      productVersion: 3,
      title: "示例茶叶",
      storeId: "sto_001",
      salesModel: "MERCHANT",
      responsibilityLabel: "商家销售并履约",
      skuItems: [
        {
          skuId: "sku_001",
          priceFen: 9900,
          currency: "CNY",
          stockStatus: "IN_STOCK",
        },
      ],
      aftersalePolicyRef: "afp_001",
    },
    successStatus: 200,
    errors: ["OBJECT_NOT_FOUND", "PRODUCT_UNAVAILABLE"],
    sourceRefs: ["SYS-02 PRD 9.1 mall products"],
  },
  {
    operationId: "sys02.publication.putChannelPublication",
    system: "SYS-02",
    visibility: "INTERNAL",
    method: "PUT",
    path: "/internal/v1/mall/channel-publications/{channelPublicationId}",
    consumer: ["SYS-05"],
    audience: ["mall-publication-ingress"],
    auth: serviceAuth(["SYS-05"], ["mall.channel_publication.write"]),
    idempotency: {
      keyFormat: "WTT_PUBLISH:{channelPublicationId}:{publicationVersion}",
    },
    params: schema.object({
      channelPublicationId: schema.id("chp_"),
    }),
    body: schema.object({
      contentId: schema.id("cnt_"),
      contentVersionId: schema.id("cnv_"),
      enterpriseId: schema.id("ent_"),
      promoterEnterpriseId: schema.id("ent_"),
      productRefs: schema.array(
        schema.object({
          productId: schema.id("prd_"),
          productVersion: version,
        }),
        { minItems: 1, maxItems: 50 },
      ),
      mediaRefs: schema.array(schema.id("med_"), { maxItems: 50 }),
      title: schema.string({ minLength: 1, maxLength: 200 }),
      bodySafeRef: schema.id("bsr_"),
      publicationVersion: version,
      snapshotHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      confirmationRef: schema.id("pcf_"),
      executionId: schema.id("exe_"),
    }),
    requestExample: {
      params: { channelPublicationId: "chp_001" },
      body: {
        contentId: "cnt_001",
        contentVersionId: "cnv_003",
        enterpriseId: "ent_001",
        promoterEnterpriseId: "ent_001",
        productRefs: [{ productId: "prd_001", productVersion: 3 }],
        mediaRefs: ["med_001"],
        title: "示例内容",
        bodySafeRef: "bsr_001",
        publicationVersion: 1,
        snapshotHash: "c".repeat(64),
        confirmationRef: "pcf_001",
        executionId: "exe_001",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      publicationVersion: version,
      status: schema.enum(["PROCESSING"]),
    }),
    responseExample: {
      accepted: true,
      publicationVersion: 1,
      status: "PROCESSING",
    },
    successStatus: 202,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "PRODUCT_UNAVAILABLE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-02 PRD 9.1 channel publication PUT", "SYS-05 PRD IF-CNT-004"],
  },
  {
    operationId: "sys02.publication.getChannelPublication",
    system: "SYS-02",
    visibility: "INTERNAL",
    method: "GET",
    path: "/internal/v1/mall/channel-publications/{channelPublicationId}",
    consumer: ["SYS-05"],
    audience: ["mall-publication-readback"],
    auth: serviceAuth(["SYS-05"], ["mall.channel_publication.read"]),
    params: schema.object({
      channelPublicationId: schema.id("chp_"),
    }),
    query: schema.object({
      publicationVersion: version,
      expectedHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
    }),
    requestExample: {
      params: { channelPublicationId: "chp_001" },
      query: { publicationVersion: 1, expectedHash: "c".repeat(64) },
    },
    responseData: schema.object({
      status: schema.enum(["PROCESSING", "ACCESSIBLE", "REJECTED", "WITHDRAWN"]),
      publicUrlRef: nullableId,
      productCardStatuses: schema.array(
        schema.object({
          productId: schema.id("prd_"),
          status: schema.enum(["MATCHED", "MISSING", "MISMATCHED"]),
        }),
      ),
      publicationVersion: version,
      snapshotHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
      firstAccessibleAt: schema.nullableString({ format: "date-time" }),
      checkedAt: time,
    }),
    responseExample: {
      status: "ACCESSIBLE",
      publicUrlRef: "url_001",
      productCardStatuses: [{ productId: "prd_001", status: "MATCHED" }],
      publicationVersion: 1,
      snapshotHash: "c".repeat(64),
      firstAccessibleAt: "2026-08-10T02:05:00Z",
      checkedAt: "2026-08-10T02:06:00Z",
    },
    successStatus: 200,
    errors: [...COMMON_SERVICE_ERRORS, "OBJECT_NOT_FOUND", "VERSION_CONFLICT"],
    sourceRefs: ["SYS-02 PRD 9.1 channel publication GET", "SYS-05 PRD IF-CNT-004"],
  },
  {
    operationId: "sys02.attribution.createCandidate",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/mall/attribution-candidates",
    consumer: ["mall-web"],
    audience: ["mall-visitor"],
    auth: PUBLIC_AUTH,
    idempotency: {
      keyFormat: "ATTRIBUTION_CANDIDATE:{visitorSubject}:{channelPublicationId}:{clickedAtBucket}",
    },
    body: schema.object({
      contentId: schema.id("cnt_"),
      channelPublicationId: schema.id("chp_"),
      productId: schema.id("prd_"),
      clickedAt: time,
    }),
    requestExample: {
      body: {
        contentId: "cnt_001",
        channelPublicationId: "chp_001",
        productId: "prd_001",
        clickedAt: "2026-08-10T02:00:00Z",
      },
    },
    responseData: schema.object({
      attributionCandidateId: schema.id("atc_"),
      acceptedAt: time,
    }),
    responseExample: {
      attributionCandidateId: "atc_001",
      acceptedAt: "2026-08-10T02:00:00Z",
    },
    successStatus: 202,
    errors: ["VALIDATION_ERROR", "PRODUCT_UNAVAILABLE", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-02 PRD 9.1 attribution candidates"],
  },
  {
    operationId: "sys02.cart.addItem",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/mall/carts/items",
    consumer: ["mall-web"],
    audience: ["consumer-or-anonymous-session"],
    auth: PUBLIC_AUTH,
    idempotency: {
      keyFormat: "CART_ITEM:{cartOwner}:{skuId}:{clientRequestId}",
    },
    body: schema.object({
      skuId: schema.id("sku_"),
      quantity: schema.integer({ minimum: 1, maximum: 999 }),
      expectedCartVersion: schema.nullableInteger({ minimum: 1 }),
      clientRequestId: schema.id("req_"),
    }),
    requestExample: {
      body: {
        skuId: "sku_001",
        quantity: 1,
        expectedCartVersion: null,
        clientRequestId: "req_cart_001",
      },
    },
    responseData: schema.object({
      cartId: schema.id("crt_"),
      cartVersion: version,
      storeId: schema.id("sto_"),
      items: schema.array(schema.record()),
    }),
    responseExample: {
      cartId: "crt_001",
      cartVersion: 1,
      storeId: "sto_001",
      items: [{ skuId: "sku_001", quantity: 1 }],
    },
    successStatus: 201,
    errors: ["VALIDATION_ERROR", "CART_STORE_CONFLICT", "PRODUCT_UNAVAILABLE", "IDEMPOTENCY_CONFLICT"],
    sourceRefs: ["SYS-02 PRD 9.1 cart items"],
  },
  {
    operationId: "sys02.checkout.preview",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/mall/checkout/preview",
    consumer: ["mall-web"],
    audience: ["consumer"],
    auth: actorAuth(["CONSUMER"], ["mall.checkout.preview"]),
    idempotency: {
      keyFormat: "CHECKOUT_PREVIEW:{consumerProfileId}:{cartVersion}:{addressRef}",
    },
    body: schema.object({
      cartId: schema.id("crt_"),
      cartVersion: version,
      addressRef: schema.id("adr_"),
    }),
    requestExample: {
      body: {
        cartId: "crt_001",
        cartVersion: 1,
        addressRef: "adr_001",
      },
    },
    responseData: schema.object({
      previewVersion: schema.id("cpv_"),
      salesModel: schema.enum(["SELF_OPERATED", "MERCHANT", "SUPPLIER"]),
      responsibilityLabel: schema.string(),
      itemAmountFen: money,
      shippingFen: money,
      payableFen: money,
      currency: schema.enum(["CNY"]),
      expiresAt: time,
    }),
    responseExample: {
      previewVersion: "cpv_001",
      salesModel: "MERCHANT",
      responsibilityLabel: "商家销售并履约",
      itemAmountFen: 9900,
      shippingFen: 0,
      payableFen: 9900,
      currency: "CNY",
      expiresAt: "2026-08-10T02:15:00Z",
    },
    successStatus: 200,
    errors: [
      ...COMMON_USER_ERRORS,
      "CONSUMER_TRIAL_WHITELIST_REQUIRED",
      "PRODUCT_SALES_MODEL_INVALID",
      "PRICE_CHANGED",
      "OUT_OF_STOCK",
    ],
    sourceRefs: ["SYS-02 PRD 9.1 checkout preview"],
  },
  {
    operationId: "sys02.order.create",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/mall/orders",
    consumer: ["mall-web"],
    audience: ["consumer"],
    auth: actorAuth(["CONSUMER"], ["mall.order.create"]),
    idempotency: {
      keyFormat: "ORDER_CREATE:{consumerProfileId}:{clientRequestId}",
    },
    body: schema.object(
      {
        previewVersion: schema.id("cpv_"),
        addressRef: schema.id("adr_"),
        attributionCandidateRef: nullableId,
        clientRequestId: schema.id("req_"),
      },
      [
        "previewVersion",
        "addressRef",
        "attributionCandidateRef",
        "clientRequestId",
      ],
    ),
    requestExample: {
      body: {
        previewVersion: "cpv_001",
        addressRef: "adr_001",
        attributionCandidateRef: "atc_001",
        clientRequestId: "req_order_001",
      },
    },
    responseData: schema.object({
      orderId: schema.id("ord_"),
      subOrderId: schema.id("sor_"),
      reservationId: schema.id("irs_"),
      salesModel: schema.enum(["SELF_OPERATED", "MERCHANT", "SUPPLIER"]),
      distributionContextStatus: schema.enum(["RESOLVED", "PENDING_DISTRIBUTION_RULE"]),
      expiresAt: time,
      payableFen: money,
      currency: schema.enum(["CNY"]),
    }),
    responseExample: {
      orderId: "ord_001",
      subOrderId: "sor_001",
      reservationId: "irs_001",
      salesModel: "MERCHANT",
      distributionContextStatus: "RESOLVED",
      expiresAt: "2026-08-10T02:30:00Z",
      payableFen: 9900,
      currency: "CNY",
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "CONSUMER_TRIAL_WHITELIST_REQUIRED",
      "PRICE_CHANGED",
      "OUT_OF_STOCK",
      "INVENTORY_RESERVATION_CONFLICT",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-02 PRD 9.1 mall orders"],
  },
  {
    operationId: "sys02.order.get",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "GET",
    path: "/api/v1/mall/orders/{orderId}",
    consumer: ["mall-web"],
    audience: ["consumer"],
    auth: actorAuth(["CONSUMER"], ["mall.order.read"]),
    params: schema.object({
      orderId: schema.id("ord_"),
    }),
    requestExample: {
      params: { orderId: "ord_001" },
    },
    responseData: schema.object({
      orderId: schema.id("ord_"),
      subOrderId: schema.id("sor_"),
      orderVersion: version,
      orderStatus: schema.enum([
        "PENDING_PAYMENT",
        "PAID",
        "SHIPPED",
        "RECEIVED",
        "CANCELLED",
        "CLOSED",
      ]),
      paymentStatus: schema.enum(["NOT_CREATED", "PENDING", "SUCCEEDED", "FAILED"]),
      inventoryCommitStatus: schema.enum(["RESERVED", "PENDING", "COMMITTED", "RELEASED"]),
      allowedActions: schema.array(schema.string()),
      payableFen: money,
    }),
    responseExample: {
      orderId: "ord_001",
      subOrderId: "sor_001",
      orderVersion: 2,
      orderStatus: "PAID",
      paymentStatus: "SUCCEEDED",
      inventoryCommitStatus: "COMMITTED",
      allowedActions: [],
      payableFen: 9900,
    },
    successStatus: 200,
    errors: ["AUTH_REQUIRED", "OBJECT_NOT_FOUND", "TENANT_SCOPE_VIOLATION"],
    sourceRefs: ["SYS-02 PRD 9.1 order detail"],
  },
  {
    operationId: "sys02.payment.create",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/mall/orders/{orderId}/payments",
    consumer: ["mall-web"],
    audience: ["consumer"],
    auth: actorAuth(["CONSUMER"], ["mall.payment.create"]),
    idempotency: {
      keyFormat: "MALL_PAYMENT:{orderId}:{channel}:{clientRequestId}",
    },
    params: schema.object({
      orderId: schema.id("ord_"),
    }),
    body: schema.object({
      channel: schema.enum(["WECHAT", "ALIPAY"]),
      clientRequestId: schema.id("req_"),
    }),
    requestExample: {
      params: { orderId: "ord_001" },
      body: { channel: "WECHAT", clientRequestId: "req_payment_001" },
    },
    responseData: schema.object({
      paymentId: schema.id("pay_"),
      status: schema.enum(["PENDING", "SUCCEEDED"]),
      paymentParameters: schema.record(),
      expiresAt: time,
    }),
    responseExample: {
      paymentId: "pay_001",
      status: "PENDING",
      paymentParameters: { prepayId: "<provider-prepay-reference>" },
      expiresAt: "2026-08-10T02:30:00Z",
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "ORDER_STATE_CONFLICT",
      "CONSUMER_TRIAL_WHITELIST_REQUIRED",
      "PAYMENT_CHANNEL_UNAVAILABLE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-02 PRD 9.1 order payments"],
  },
  {
    operationId: "sys02.order.registerShipment",
    system: "SYS-02",
    visibility: "INTERNAL",
    method: "POST",
    path: "/internal/v1/mall/commands/register-order-shipment",
    consumer: ["SYS-03"],
    audience: ["mall-order-command"],
    auth: serviceAuth(
      ["SYS-03"],
      ["shipment.register"],
      true,
    ),
    idempotency: {
      keyFormat: "SHIPMENT_REGISTER:{fulfillmentId}:{fulfillmentVersion}",
    },
    body: schema.object(
      {
        commandId: schema.id("cmd_"),
        fulfillmentId: schema.id("ful_"),
        orderId: schema.id("ord_"),
        subOrderId: schema.id("sor_"),
        enterpriseId: schema.id("ent_"),
        storeId: schema.id("sto_"),
        carrierCode: schema.string(),
        trackingNoRef: schema.id("trk_"),
        trackingNoMasked: schema.string(),
        shippedAt: time,
        fulfillmentVersion: version,
        expectedOrderVersion: version,
        actorRef: schema.id("usr_"),
        approvalRef: nullableId,
        traceId: PLATFORM_HTTP_SCHEMAS.TraceId,
      },
      [
        "commandId",
        "fulfillmentId",
        "orderId",
        "subOrderId",
        "enterpriseId",
        "storeId",
        "carrierCode",
        "trackingNoRef",
        "trackingNoMasked",
        "shippedAt",
        "fulfillmentVersion",
        "expectedOrderVersion",
        "actorRef",
        "approvalRef",
        "traceId",
      ],
    ),
    requestExample: {
      body: {
        commandId: "cmd_ship_001",
        fulfillmentId: "ful_001",
        orderId: "ord_001",
        subOrderId: "sor_001",
        enterpriseId: "ent_001",
        storeId: "sto_001",
        carrierCode: "SF",
        trackingNoRef: "trk_001",
        trackingNoMasked: "SF****1234",
        shippedAt: "2026-08-10T02:00:00Z",
        fulfillmentVersion: 1,
        expectedOrderVersion: 2,
        actorRef: "usr_merchant_001",
        approvalRef: null,
        traceId: "trace_contract_example_001",
      },
    },
    responseData: schema.object({
      accepted: schema.boolean(),
      commandId: schema.id("cmd_"),
      currentOrderVersion: version,
    }),
    responseExample: {
      accepted: true,
      commandId: "cmd_ship_001",
      currentOrderVersion: 2,
    },
    successStatus: 202,
    errors: [
      ...COMMON_SERVICE_ERRORS,
      "TOOL_AUTHORIZATION_INVALID",
      "ORDER_STATE_CONFLICT",
      "ORDER_INVENTORY_NOT_COMMITTED",
      "COMMAND_IDEMPOTENCY_PAYLOAD_MISMATCH",
    ],
    sourceRefs: ["SYS-02 PRD 9.1 register-order-shipment", "SYS-03 PRD 9.3 frozen command"],
  },
  {
    operationId: "sys02.analytics.getOrderOutcomeSnapshot",
    system: "SYS-02",
    visibility: "INTERNAL",
    method: "GET",
    path: "/internal/v1/mall/order-outcome-snapshots/{snapshotRef}",
    consumer: ["SYS-04", "SYS-06"],
    audience: ["marketing-analytics", "business-analytics"],
    auth: serviceAuth(
      ["SYS-04", "SYS-06"],
      ["mall.order_outcome_snapshot.read"],
    ),
    params: schema.object({
      snapshotRef: schema.id("oas_"),
    }),
    query: schema.object({
      outcomeVersion: version,
      expectedHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
    }),
    requestExample: {
      params: { snapshotRef: "oas_001" },
      query: { outcomeVersion: 2, expectedHash: "d".repeat(64) },
    },
    responseData: schema.object({
      orderId: schema.id("ord_"),
      subOrderId: schema.id("sor_"),
      sellerEnterpriseId: schema.id("ent_"),
      storeId: schema.id("sto_"),
      attributionId: schema.id("att_"),
      salesModel: schema.enum(["SELF_OPERATED", "MERCHANT", "SUPPLIER"]),
      outcomeType: schema.enum(["PAID", "REFUNDED"]),
      outcomeVersion: version,
      productLines: schema.array(
        schema.object({
          productId: schema.id("prd_"),
          skuId: schema.id("sku_"),
          productVersion: version,
          quantity: schema.integer({ minimum: 1 }),
          lineGrossFen: money,
          linePaidFen: money,
          lineRefundedFen: money,
        }),
      ),
      outcomeAmountFen: money,
      cumulativeRefundedFen: money,
      currency: schema.enum(["CNY"]),
      occurredAt: time,
      analyticsSnapshotVersion: version,
      analyticsSnapshotHash: schema.string({ pattern: "^[a-f0-9]{64}$" }),
    }),
    responseExample: {
      orderId: "ord_001",
      subOrderId: "sor_001",
      sellerEnterpriseId: "ent_001",
      storeId: "sto_001",
      attributionId: "att_001",
      salesModel: "MERCHANT",
      outcomeType: "PAID",
      outcomeVersion: 2,
      productLines: [
        {
          productId: "prd_001",
          skuId: "sku_001",
          productVersion: 3,
          quantity: 1,
          lineGrossFen: 9900,
          linePaidFen: 9900,
          lineRefundedFen: 0,
        },
      ],
      outcomeAmountFen: 9900,
      cumulativeRefundedFen: 0,
      currency: "CNY",
      occurredAt: "2026-08-10T02:00:00Z",
      analyticsSnapshotVersion: 2,
      analyticsSnapshotHash: "d".repeat(64),
    },
    successStatus: 200,
    errors: [...COMMON_SERVICE_ERRORS, "OBJECT_NOT_FOUND", "VERSION_CONFLICT"],
    sourceRefs: ["SYS-02 PRD 9.1 order outcome snapshot", "SYS-06 PRD 8.1 source readback"],
  },
  {
    operationId: "sys02.aftersale.create",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/mall/after-sales",
    consumer: ["mall-web"],
    audience: ["consumer"],
    auth: actorAuth(["CONSUMER"], ["mall.aftersale.create"]),
    idempotency: {
      keyFormat: "AFTERSALE_CREATE:{consumerProfileId}:{clientRequestId}",
    },
    body: schema.object({
      clientRequestId: schema.id("req_"),
      orderId: schema.id("ord_"),
      subOrderId: schema.id("sor_"),
      items: schema.array(
        schema.object({
          skuId: schema.id("sku_"),
          quantity: schema.integer({ minimum: 1 }),
        }),
        { minItems: 1 },
      ),
      type: schema.enum(["REFUND_ONLY", "RETURN_REFUND"]),
      reason: schema.string({ minLength: 2, maxLength: 1000 }),
      amountFen: money,
      evidenceRefs: schema.array(schema.id("evd_"), { maxItems: 20 }),
    }),
    requestExample: {
      body: {
        clientRequestId: "req_aftersale_001",
        orderId: "ord_001",
        subOrderId: "sor_001",
        items: [{ skuId: "sku_001", quantity: 1 }],
        type: "REFUND_ONLY",
        reason: "商品破损",
        amountFen: 9900,
        evidenceRefs: ["evd_010"],
      },
    },
    responseData: schema.object({
      aftersaleId: schema.id("afs_"),
      status: schema.enum(["SUBMITTED"]),
      deadlineAt: time,
      version,
    }),
    responseExample: {
      aftersaleId: "afs_001",
      status: "SUBMITTED",
      deadlineAt: "2026-08-12T02:00:00Z",
      version: 1,
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "AFTERSALE_NOT_ELIGIBLE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-02 PRD 9.1 after-sales"],
  },
  {
    operationId: "sys02.review.create",
    system: "SYS-02",
    visibility: "PUBLIC",
    method: "POST",
    path: "/api/v1/mall/reviews",
    consumer: ["mall-web"],
    audience: ["consumer"],
    auth: actorAuth(["CONSUMER"], ["mall.review.create"]),
    idempotency: {
      keyFormat: "REVIEW_CREATE:{orderId}:{subOrderId}:{skuId}:{buyerUserId}",
    },
    body: schema.object({
      orderId: schema.id("ord_"),
      subOrderId: schema.id("sor_"),
      productId: schema.id("prd_"),
      skuId: schema.id("sku_"),
      rating: schema.integer({ minimum: 1, maximum: 5 }),
      text: schema.string({ maxLength: 2000 }),
      imageRefs: schema.array(schema.id("img_"), { maxItems: 9 }),
    }),
    requestExample: {
      body: {
        orderId: "ord_001",
        subOrderId: "sor_001",
        productId: "prd_001",
        skuId: "sku_001",
        rating: 5,
        text: "商品很好",
        imageRefs: [],
      },
    },
    responseData: schema.object({
      reviewId: schema.id("rev_"),
      status: schema.enum(["PENDING_MODERATION", "PUBLIC"]),
      version,
    }),
    responseExample: {
      reviewId: "rev_001",
      status: "PENDING_MODERATION",
      version: 1,
    },
    successStatus: 201,
    errors: [
      ...COMMON_USER_ERRORS,
      "REVIEW_NOT_ELIGIBLE",
      "IDEMPOTENCY_CONFLICT",
    ],
    sourceRefs: ["SYS-02 PRD 9.1 mall reviews"],
  },
]);

/**
 * Generator entry point. The array is frozen after all per-system registrations
 * so OpenAPI, SDK, mock and contract-test generators consume the same snapshot.
 */
export const PLATFORM_HTTP_CONTRACTS: readonly PlatformHttpContract[] =
  Object.freeze(CONTRACTS.slice());

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pathPrefixFor(visibility: PlatformApiVisibility): string {
  if (visibility === "PUBLIC") return "/api/v1/";
  if (visibility === "INTERNAL") return "/internal/v1/";
  return "/callbacks/v1/";
}

/**
 * Validates structural invariants that are easy to accidentally break when a
 * PRD route is promoted into the executable registry.
 */
export function validatePlatformHttpContracts(): string[] {
  const issues: string[] = [];
  const operationIds = new Set<string>();
  const routes = new Set<string>();
  const systems = new Set<PlatformSystem>();

  for (const contract of PLATFORM_HTTP_CONTRACTS) {
    systems.add(contract.system);
    if (operationIds.has(contract.operationId)) {
      issues.push("duplicate operationId: " + contract.operationId);
    }
    operationIds.add(contract.operationId);

    const route = contract.method + " " + contract.path;
    if (routes.has(route)) {
      issues.push("duplicate route: " + route);
    }
    routes.add(route);

    const expectedPrefix = pathPrefixFor(contract.visibility);
    if (!contract.path.startsWith(expectedPrefix)) {
      issues.push(
        contract.operationId +
          " must use " +
          expectedPrefix +
          " for visibility " +
          contract.visibility,
      );
    }
    if (contract.path.includes("/api/v1/internal")) {
      issues.push(contract.operationId + " uses deprecated /api/v1/internal");
    }
    if (contract.owner !== contract.system) {
      issues.push(contract.operationId + " owner must equal system");
    }
    if (contract.producer.length === 0 || contract.consumer.length === 0) {
      issues.push(contract.operationId + " must declare producer and consumer");
    }
    if (contract.audience.length === 0) {
      issues.push(contract.operationId + " must declare an audience");
    }

    if (
      (contract.auth.mode === "USER_SESSION" ||
        contract.auth.mode === "USER_SESSION_STRONG") &&
      contract.auth.roles.length === 0
    ) {
      issues.push(contract.operationId + " user-session auth requires roles");
    }
    if (
      (contract.auth.mode === "SERVICE_MTLS" ||
        contract.auth.mode === "SERVICE_MTLS_USER_DELEGATION") &&
      contract.auth.servicePrincipals.length === 0
    ) {
      issues.push(contract.operationId + " service auth requires principals");
    }
    if (
      contract.visibility === "CALLBACK" &&
      contract.auth.mode !== "SIGNED_PROVIDER_CALLBACK"
    ) {
      issues.push(contract.operationId + " callback must use signed provider auth");
    }

    if (
      contract.method !== "GET" &&
      contract.idempotency.required !== true
    ) {
      issues.push(contract.operationId + " write operation requires idempotency");
    }
    if (
      contract.idempotency.source === "HEADER" &&
      contract.idempotency.headerName !== "Idempotency-Key"
    ) {
      issues.push(contract.operationId + " header idempotency name is invalid");
    }
    if (
      contract.idempotency.required &&
      (!contract.idempotency.keyFormat ||
        contract.idempotency.keyFormat.trim().length === 0)
    ) {
      issues.push(contract.operationId + " has no idempotency key format");
    }

    const requestProperties = contract.request.schema.properties;
    if (!requestProperties?.headers) {
      issues.push(contract.operationId + " request schema has no headers object");
    }
    const placeholders = Array.from(
      contract.path.matchAll(/\{([A-Za-z][A-Za-z0-9]*)\}/g),
      (match) => match[1],
    );
    const paramsSchema = requestProperties?.params;
    for (const placeholder of placeholders) {
      if (!placeholder || !paramsSchema?.properties?.[placeholder]) {
        issues.push(
          contract.operationId +
            " has no params schema for path placeholder " +
            String(placeholder),
        );
      }
    }

    if (contract.response.successSchema.type !== "object") {
      issues.push(contract.operationId + " success response must be an object envelope");
    }
    if (contract.response.errorSchema.type !== "object") {
      issues.push(contract.operationId + " error response must be an object envelope");
    }
    const successRequired = new Set(contract.response.successSchema.required ?? []);
    for (const field of ["data", "requestId", "traceId"]) {
      if (!successRequired.has(field)) {
        issues.push(contract.operationId + " success response missing " + field);
      }
    }
    const errorRequired = new Set(contract.response.errorSchema.required ?? []);
    for (const field of [
      "code",
      "message",
      "retryable",
      "requestId",
      "traceId",
      "fieldErrors",
    ]) {
      if (!errorRequired.has(field)) {
        issues.push(contract.operationId + " error response missing " + field);
      }
    }
    if (contract.errors.length === 0) {
      issues.push(contract.operationId + " has no declared error response");
    }
    for (const error of contract.errors) {
      if (!Object.prototype.hasOwnProperty.call(PLATFORM_ERROR_REGISTRY, error.code)) {
        issues.push(contract.operationId + " uses unknown error code " + error.code);
      }
    }

    const successExample = contract.examples.success.response;
    if (
      !isObjectRecord(successExample) ||
      typeof successExample.requestId !== "string" ||
      typeof successExample.traceId !== "string" ||
      !Object.prototype.hasOwnProperty.call(successExample, "data")
    ) {
      issues.push(contract.operationId + " has an invalid success example envelope");
    }
    const failureExample = contract.examples.failure.response;
    if (
      !isObjectRecord(failureExample) ||
      typeof failureExample.code !== "string" ||
      typeof failureExample.requestId !== "string" ||
      typeof failureExample.traceId !== "string"
    ) {
      issues.push(contract.operationId + " has an invalid failure example envelope");
    }
  }

  for (const system of [
    "SYS-01",
    "SYS-02",
    "SYS-03",
    "SYS-04",
    "SYS-05",
    "SYS-06",
    "SYS-07",
    "SYS-08",
  ] as const) {
    if (!systems.has(system)) {
      issues.push("missing HTTP contracts for " + system);
    }
  }

  const publicationCharge = PLATFORM_HTTP_CONTRACTS.filter(
    (contract) =>
      contract.operationId === "sys08.publicationCharge.reserve" ||
      contract.path === "/internal/v1/ledger/publication-charge-reservations",
  );
  if (publicationCharge.length !== 1) {
    issues.push("publication charge reservation must have exactly one HTTP contract");
  } else if (
    publicationCharge[0]?.idempotency.keyFormat !==
    "PUBLICATION_CHARGE:{channelPublicationId}"
  ) {
    issues.push(
      "publication charge reservation key must be PUBLICATION_CHARGE:{channelPublicationId}",
    );
  }
  for (const contract of PLATFORM_HTTP_CONTRACTS) {
    if (contract.idempotency.keyFormat?.startsWith("PUB_CHARGE_RESERVE:")) {
      issues.push(
        contract.operationId + " uses forbidden legacy PUB_CHARGE_RESERVE key",
      );
    }
  }

  return issues;
}
