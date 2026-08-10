import { mkdir, readFile, readdir, unlink, writeFile } from "node:fs/promises";
import { dirname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import {
  PLATFORM_ERROR_REGISTRY,
  PLATFORM_HTTP_CONTRACTS,
  PLATFORM_HTTP_SCHEMAS,
  type PlatformHttpErrorContract,
  type PlatformHttpContract,
  type PlatformJsonSchema,
} from "../packages/contracts/src/platform/http-contracts.js";
import {
  PLATFORM_EVENT_CONTRACTS,
  PLATFORM_EVENT_SCHEMAS,
  type JsonSchema,
  type PlatformEventContract,
} from "../packages/contracts/src/platform/event-contracts.js";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const CONTRACT_VERSION = "1.0.0";
const GENERATED_ROOT = "packages/contracts/platform";

type JsonObject = Record<string, unknown>;
type GeneratedFiles = Map<string, string>;

const HTTP_METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);

function json(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function schemaObject(value: PlatformJsonSchema | JsonSchema | undefined): JsonObject {
  return value && typeof value === "object" ? clone(value) as JsonObject : {};
}

function withoutDialect(schema: PlatformJsonSchema | undefined): JsonObject {
  const result = schemaObject(schema);
  delete result.$schema;
  delete result.$id;
  return result;
}

function asSchema(value: unknown): PlatformJsonSchema | undefined {
  return value && typeof value === "object"
    ? value as PlatformJsonSchema
    : undefined;
}

function propertiesOf(schema: PlatformJsonSchema | undefined): Record<string, PlatformJsonSchema> {
  return (schema?.properties ?? {}) as Record<string, PlatformJsonSchema>;
}

function requiredOf(schema: PlatformJsonSchema | undefined): Set<string> {
  return new Set(schema?.required ?? []);
}

function titleHeader(name: string): string {
  const known: Record<string, string> = {
    "idempotency-key": "Idempotency-Key",
    "x-csrf-token": "X-Csrf-Token",
    "x-provider-nonce": "X-Provider-Nonce",
    "x-provider-signature": "X-Provider-Signature",
    "x-provider-timestamp": "X-Provider-Timestamp",
    "x-service-authorization": "X-Service-Authorization",
    "x-trace-id": "X-Trace-Id",
    "x-user-delegation": "X-User-Delegation",
  };
  return known[name.toLowerCase()] ?? name;
}

function securityFor(contract: PlatformHttpContract): JsonObject[] | undefined {
  switch (contract.auth.mode) {
    case "PUBLIC":
      return undefined;
    case "USER_SESSION":
      return [{ BearerAuth: [] }];
    case "USER_SESSION_STRONG":
      return [{ BearerAuth: [], CsrfToken: [] }];
    case "SERVICE_MTLS":
      return [{ MutualTLS: [] }];
    case "SERVICE_MTLS_USER_DELEGATION":
      return [{ MutualTLS: [], UserDelegation: [] }];
    case "SIGNED_PROVIDER_CALLBACK":
      return [{ ProviderSignature: [], ProviderTimestamp: [], ProviderNonce: [] }];
  }
}

function parameterObjects(
  location: "path" | "query" | "header",
  schema: PlatformJsonSchema | undefined,
  example: unknown,
): JsonObject[] {
  const required = requiredOf(schema);
  const values = example && typeof example === "object"
    ? example as Record<string, unknown>
    : {};
  return Object.entries(propertiesOf(schema))
    .filter(([name]) => !(location === "header" && name.toLowerCase() === "authorization"))
    .map(([name, child]) => ({
      name: location === "header" ? titleHeader(name) : name,
      in: location,
      required: location === "path" || required.has(name),
      schema: withoutDialect(child),
      ...(name in values ? { example: values[name] } : {}),
    }));
}

function errorSchemaForCodes(
  source: PlatformJsonSchema,
  codes: readonly string[],
): JsonObject {
  const result = withoutDialect(source);
  const properties = result.properties as Record<string, JsonObject> | undefined;
  if (properties?.code) properties.code.enum = [...codes];
  return result;
}

function errorExampleFor(
  contract: PlatformHttpContract,
  error: PlatformHttpErrorContract,
): JsonObject {
  const primary = clone(
    contract.examples.failure.response as Record<string, unknown>,
  );
  return {
    ...primary,
    code: error.code,
    message: error.description,
    retryable: error.retryable,
  };
}

function openApiOperation(contract: PlatformHttpContract): JsonObject {
  const requestSchema = contract.request.schema;
  const requestProperties = propertiesOf(requestSchema);
  const requestExample = contract.examples.success.request;
  const requestBodySchema = requestProperties.body;
  const requestBodyRequired = requiredOf(requestSchema).has("body");
  const successResponse = contract.examples.success.response;
  const errorStatuses = new Map<number, string[]>();
  for (const error of contract.errors) {
    const codes = errorStatuses.get(error.httpStatus) ?? [];
    codes.push(error.code);
    errorStatuses.set(error.httpStatus, codes);
  }

  const responses: Record<string, JsonObject> = {
    [String(contract.response.successStatus)]: {
      description: "Successful response",
      headers: {
        "X-Trace-Id": {
          description: "End-to-end trace identifier",
          schema: { $ref: "#/components/schemas/TraceId" },
        },
      },
      content: {
        "application/json": {
          schema: withoutDialect(contract.response.successSchema),
          examples: { success: { value: successResponse } },
        },
      },
    },
  };

  for (const [status, codes] of [...errorStatuses].sort(([left], [right]) => left - right)) {
    const examples = Object.fromEntries(
      contract.errors
        .filter((error) => error.httpStatus === status)
        .map((error) => [error.code, { value: errorExampleFor(contract, error) }]),
    );
    responses[String(status)] = {
      description: codes.join(", "),
      "x-error-codes": codes,
      content: {
        "application/json": {
          schema: errorSchemaForCodes(contract.response.errorSchema, codes),
          examples,
        },
      },
    };
  }

  const parameters = [
    ...parameterObjects("path", requestProperties.params, requestExample.params),
    ...parameterObjects("query", requestProperties.query, requestExample.query),
    ...parameterObjects("header", requestProperties.headers, requestExample.headers),
  ];

  return {
    operationId: contract.operationId,
    summary: contract.sourceRefs[0] ?? contract.operationId,
    description: contract.sourceRefs.join("; "),
    tags: [contract.system],
    ...(parameters.length > 0 ? { parameters } : {}),
    ...(requestBodySchema
      ? {
          requestBody: {
            required: requestBodyRequired,
            content: {
              [contract.request.contentType]: {
                schema: withoutDialect(requestBodySchema),
                ...(requestExample.body === undefined
                  ? {}
                  : { examples: { success: { value: requestExample.body } } }),
              },
            },
          },
        }
      : {}),
    responses,
    ...(securityFor(contract) ? { security: securityFor(contract) } : {}),
    "x-system": contract.system,
    "x-visibility": contract.visibility,
    "x-owner": contract.owner,
    "x-producer": contract.producer,
    "x-consumers": contract.consumer,
    "x-audience": contract.audience,
    "x-auth": contract.auth,
    "x-idempotency": contract.idempotency,
    "x-source-refs": contract.sourceRefs,
  };
}

function buildOpenApi(): JsonObject {
  const paths: Record<string, Record<string, JsonObject>> = {};
  for (const contract of PLATFORM_HTTP_CONTRACTS) {
    if (!HTTP_METHODS.has(contract.method)) {
      throw new Error(`Unsupported HTTP method: ${contract.method}`);
    }
    const path = paths[contract.path] ?? {};
    const method = contract.method.toLowerCase();
    if (path[method]) throw new Error(`Duplicate operation: ${contract.method} ${contract.path}`);
    path[method] = openApiOperation(contract);
    paths[contract.path] = path;
  }

  const componentSchemas = Object.fromEntries(
    Object.entries(PLATFORM_HTTP_SCHEMAS)
      .filter(([, value]) => typeof value === "object")
      .map(([name, value]) => [name, withoutDialect(value as PlatformJsonSchema)]),
  );

  return {
    openapi: "3.1.0",
    jsonSchemaDialect: "https://json-schema.org/draft/2020-12/schema",
    info: {
      title: "Wotao Full Platform API",
      version: CONTRACT_VERSION,
      description:
        "Executable integration boundary for SYS-01 through SYS-08. The legacy MVP OpenAPI remains a compatibility artifact.",
    },
    servers: [
      { url: "http://localhost:4011", description: "Deterministic contract mock" },
      { url: "https://dev-api.example.invalid", description: "Dev placeholder; replace through environment configuration" },
    ],
    tags: Array.from({ length: 8 }, (_, index) => ({
      name: `SYS-0${index + 1}`,
      description: `System ${index + 1} owned operations`,
    })),
    paths,
    components: {
      securitySchemes: {
        BearerAuth: { type: "http", scheme: "bearer", bearerFormat: "JWT" },
        CsrfToken: { type: "apiKey", in: "header", name: "X-Csrf-Token" },
        MutualTLS: { type: "mutualTLS" },
        UserDelegation: { type: "apiKey", in: "header", name: "X-User-Delegation" },
        ProviderSignature: { type: "apiKey", in: "header", name: "X-Provider-Signature" },
        ProviderTimestamp: { type: "apiKey", in: "header", name: "X-Provider-Timestamp" },
        ProviderNonce: { type: "apiKey", in: "header", name: "X-Provider-Nonce" },
      },
      schemas: componentSchemas,
    },
    "x-contract-family": "full-platform",
    "x-contract-version": CONTRACT_VERSION,
  };
}

function eventSchema(contract: PlatformEventContract): JsonObject {
  const schema = schemaObject(PLATFORM_EVENT_SCHEMAS[contract.eventType]);
  return {
    ...schema,
    description: contract.notes ?? contract.businessUniqueness,
    examples: [contract.example],
    "x-topic": contract.topic,
    "x-producer": contract.producer,
    "x-consumers": contract.consumers,
    "x-idempotency-key-format": contract.idempotencyKey,
  };
}

function eventFileName(contract: PlatformEventContract): string {
  return `${contract.eventType}.v${contract.schemaVersion}.schema.json`;
}

function asyncName(contract: PlatformEventContract): string {
  return `${contract.eventType}V${contract.schemaVersion}`.replace(/[^A-Za-z0-9_]/g, "_");
}

function buildAsyncApi(): JsonObject {
  const channels: Record<string, JsonObject> = {};
  const operations: Record<string, JsonObject> = {};
  const messages: Record<string, JsonObject> = {};
  const schemas: Record<string, JsonObject> = {};

  for (const contract of PLATFORM_EVENT_CONTRACTS) {
    const name = asyncName(contract);
    const channelName = `${name}Channel`;
    const messageName = `${name}Message`;
    const schemaName = `${name}Envelope`;
    channels[channelName] = {
      address: `wotao.{environment}.${contract.topic}`,
      description: `${contract.eventType} produced by ${contract.producer}`,
      parameters: {
        environment: {
          description: "Deployment environment",
          enum: ["dev", "test", "staging", "prod"],
          default: "dev",
        },
      },
      messages: {
        [messageName]: { $ref: `#/components/messages/${messageName}` },
      },
      "x-logical-topic": contract.topic,
      "x-producer": contract.producer,
      "x-consumers": contract.consumers,
      "x-audience": contract.audience,
    };
    operations[`publish${name}`] = {
      action: "send",
      channel: { $ref: `#/channels/${channelName}` },
      messages: [{ $ref: `#/channels/${channelName}/messages/${messageName}` }],
      "x-owner": contract.producer,
      "x-consumers": contract.consumers,
    };
    messages[messageName] = {
      name: contract.eventType,
      title: `${contract.eventType} v${contract.schemaVersion}`,
      summary: contract.businessUniqueness,
      contentType: "application/json",
      payload: { $ref: `#/components/schemas/${schemaName}` },
      examples: [{ name: "fixed", payload: contract.example }],
      "x-schema-version": contract.schemaVersion,
      "x-idempotency-key-format": contract.idempotencyKey,
      "x-idempotency-conflict-policy": contract.conflictPolicy,
      "x-pii-policy": contract.piiPolicy,
    };
    // Embed schemas so compatibility gates can compare payload semantics without
    // losing the separately generated Draft 2020-12 schema artifact.
    schemas[schemaName] = eventSchema(contract);
  }

  return {
    asyncapi: "3.0.0",
    info: {
      title: "Wotao Full Platform Events",
      version: CONTRACT_VERSION,
      description:
        "Versioned asynchronous contracts for SYS-01 through SYS-08. Physical topics prepend wotao.<environment> to the registered logical topic.",
    },
    defaultContentType: "application/json",
    servers: {
      development: {
        host: "localhost:9092",
        protocol: "kafka",
        description: "Local/Dev placeholder broker",
      },
    },
    channels,
    operations,
    components: { messages, schemas },
    "x-contract-version": CONTRACT_VERSION,
  };
}

function buildRegistry(): JsonObject {
  const errors = Object.fromEntries(
    Object.entries(PLATFORM_ERROR_REGISTRY).map(([code, definition]) => [
      code,
      { code, ...definition },
    ]),
  );
  const topics = PLATFORM_EVENT_CONTRACTS.map((contract) => ({
    eventType: contract.eventType,
    messageKind: contract.messageKind,
    logicalTopic: contract.topic,
    physicalTopicTemplate: `wotao.{environment}.${contract.topic}`,
    schemaVersion: contract.schemaVersion,
    producer: contract.producer,
    consumers: contract.consumers,
    audience: contract.audience,
    schema: `events/${eventFileName(contract)}`,
    idempotencyKeyFormat: contract.idempotencyKey,
    conflictPolicy: contract.conflictPolicy,
    compatibility: contract.compatibility,
    piiPolicy: contract.piiPolicy,
  }));
  const httpIdempotency = PLATFORM_HTTP_CONTRACTS
    .filter((contract) => contract.idempotency.required)
    .map((contract) => ({
      operationId: contract.operationId,
      method: contract.method,
      path: contract.path,
      source: contract.idempotency.source,
      headerName: contract.idempotency.headerName,
      keyFormat: contract.idempotency.keyFormat,
      replayBehavior: contract.idempotency.replayBehavior,
      payloadConflictHttpStatus: contract.idempotency.payloadConflictHttpStatus,
    }));
  const eventIdempotency = PLATFORM_EVENT_CONTRACTS.map((contract) => ({
    eventType: contract.eventType,
    topic: contract.topic,
    keyFormat: contract.idempotencyKey,
    example: contract.idempotencyExample,
    businessUniqueness: contract.businessUniqueness,
    conflictPolicy: contract.conflictPolicy,
  }));

  return {
    contractVersion: CONTRACT_VERSION,
    generatedFrom: [
      "packages/contracts/src/platform/http-contracts.ts",
      "packages/contracts/src/platform/event-contracts.ts",
    ],
    topicAddressRule: "wotao.{environment}.{logicalTopic}",
    errors,
    topics,
    idempotency: { http: httpIdempotency, events: eventIdempotency },
  };
}

function buildMatrix(): JsonObject {
  return {
    contractVersion: CONTRACT_VERSION,
    http: PLATFORM_HTTP_CONTRACTS.map((contract) => ({
      operationId: contract.operationId,
      method: contract.method,
      path: contract.path,
      provider: contract.owner,
      producer: contract.producer,
      consumers: contract.consumer,
      visibility: contract.visibility,
      authMode: contract.auth.mode,
    })),
    events: PLATFORM_EVENT_CONTRACTS.map((contract) => ({
      eventType: contract.eventType,
      topic: contract.topic,
      physicalTopicTemplate: `wotao.{environment}.${contract.topic}`,
      provider: contract.producer,
      consumers: contract.consumers,
      schemaVersion: contract.schemaVersion,
    })),
  };
}

function addHttpArtifacts(files: GeneratedFiles): void {
  const operations: Record<string, JsonObject> = {};
  for (const contract of PLATFORM_HTTP_CONTRACTS) {
    const success = {
      operationId: contract.operationId,
      method: contract.method,
      path: contract.path,
      request: contract.examples.success.request,
      status: contract.response.successStatus,
      response: contract.examples.success.response,
    };
    const failureCode = (contract.examples.failure.response as Record<string, unknown>)?.code;
    const failure = {
      operationId: contract.operationId,
      method: contract.method,
      path: contract.path,
      request: contract.examples.failure.request,
      status:
        contract.errors.find((error) => error.code === failureCode)?.httpStatus ??
        contract.errors[0]?.httpStatus ?? 400,
      response: contract.examples.failure.response,
    };
    const failures = Object.fromEntries(
      contract.errors.map((error) => [
        error.code,
        {
          operationId: contract.operationId,
          method: contract.method,
          path: contract.path,
          request: contract.examples.failure.request,
          status: error.httpStatus,
          response: errorExampleFor(contract, error),
        },
      ]),
    );
    operations[contract.operationId] = {
      method: contract.method,
      path: contract.path,
      status: contract.response.successStatus,
      auth: contract.auth,
      idempotency: contract.idempotency,
      request: contract.examples.success.request,
      response: contract.examples.success.response,
      failure,
      failures,
    };
    files.set(`${GENERATED_ROOT}/examples/http/${contract.operationId}.success.json`, json(success));
    files.set(`${GENERATED_ROOT}/examples/http/${contract.operationId}.failure.json`, json(failure));
  }
  files.set(
    `${GENERATED_ROOT}/fixtures/http/index.json`,
    json({ contractVersion: CONTRACT_VERSION, operations }),
  );
}

function addEventArtifacts(files: GeneratedFiles): void {
  const index: JsonObject[] = [];
  for (const contract of PLATFORM_EVENT_CONTRACTS) {
    const schemaFile = eventFileName(contract);
    const fixtureFile = `${contract.eventType}.v${contract.schemaVersion}.json`;
    files.set(`${GENERATED_ROOT}/events/${schemaFile}`, json(eventSchema(contract)));
    files.set(`${GENERATED_ROOT}/examples/events/${fixtureFile}`, json(contract.example));
    files.set(`${GENERATED_ROOT}/fixtures/events/${fixtureFile}`, json(contract.example));
    index.push({
      eventType: contract.eventType,
      topic: contract.topic,
      schemaVersion: contract.schemaVersion,
      schema: `../../events/${schemaFile}`,
      fixture: fixtureFile,
    });
  }
  files.set(
    `${GENERATED_ROOT}/fixtures/events/index.json`,
    json({ contractVersion: CONTRACT_VERSION, events: index }),
  );
}

function generateFiles(): GeneratedFiles {
  const files: GeneratedFiles = new Map();
  files.set(`${GENERATED_ROOT}/openapi.json`, json(buildOpenApi()));
  files.set(`${GENERATED_ROOT}/asyncapi.json`, json(buildAsyncApi()));
  files.set(`${GENERATED_ROOT}/registry.json`, json(buildRegistry()));
  files.set(`${GENERATED_ROOT}/provider-consumer-matrix.json`, json(buildMatrix()));
  addHttpArtifacts(files);
  addEventArtifacts(files);
  return files;
}

async function generatedJsonFiles(directory: string): Promise<string[]> {
  const absolute = resolve(ROOT, directory);
  try {
    const entries = await readdir(absolute, { withFileTypes: true });
    const result: string[] = [];
    for (const entry of entries) {
      const child = `${directory}/${entry.name}`;
      if (entry.isDirectory()) result.push(...await generatedJsonFiles(child));
      else if (entry.isFile() && entry.name.endsWith(".json")) result.push(child);
    }
    return result;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function check(files: GeneratedFiles): Promise<void> {
  const errors: string[] = [];
  for (const [path, expected] of files) {
    try {
      const actual = await readFile(resolve(ROOT, path), "utf8");
      if (actual !== expected) errors.push(`${path} differs from its source manifest`);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") errors.push(`${path} is missing`);
      else throw error;
    }
  }

  const actualGenerated = await generatedJsonFiles(GENERATED_ROOT);
  const expectedPaths = new Set(files.keys());
  for (const path of actualGenerated) {
    if (path.includes("/baseline/")) continue;
    if (!expectedPaths.has(path)) errors.push(`${path} is a stale generated artifact`);
  }

  if (errors.length > 0) {
    throw new Error(`Platform contract generation check failed:\n- ${errors.join("\n- ")}`);
  }
  console.log(`Platform contracts are current (${files.size} generated artifacts).`);
}

async function write(files: GeneratedFiles): Promise<void> {
  const expectedPaths = new Set(files.keys());
  const generatedRoot = resolve(ROOT, GENERATED_ROOT);
  let removed = 0;
  for (const path of await generatedJsonFiles(GENERATED_ROOT)) {
    if (path.includes("/baseline/") || expectedPaths.has(path)) continue;
    const absolute = resolve(ROOT, path);
    if (
      absolute !== generatedRoot &&
      !absolute.startsWith(`${generatedRoot}${sep}`)
    ) {
      throw new Error(
        `Refusing to remove stale artifact outside ${GENERATED_ROOT}: ${path}`,
      );
    }
    await unlink(absolute);
    removed += 1;
  }
  for (const [path, content] of files) {
    const absolute = resolve(ROOT, path);
    await mkdir(dirname(absolute), { recursive: true });
    await writeFile(absolute, content, "utf8");
  }
  console.log(
    `Generated ${files.size} platform contract artifacts under ${relative(process.cwd(), generatedRoot)}` +
      (removed > 0 ? ` and removed ${removed} stale artifact(s).` : "."),
  );
}

async function main(): Promise<void> {
  const files = generateFiles();
  if (process.argv.includes("--check")) await check(files);
  else await write(files);
}

void main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
