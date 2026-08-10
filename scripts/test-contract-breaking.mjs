import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const openApiPath = resolve("packages/contracts/platform/openapi.json");
const asyncApiPath = resolve("packages/contracts/platform/asyncapi.json");
const registryPath = resolve("packages/contracts/platform/registry.json");
const checker = resolve("scripts/check-contract-breaking.mjs");
const temporaryDirectory = mkdtempSync(join(tmpdir(), "wotao-breaking-gate-"));

function clone(value) {
  return structuredClone(value);
}

function writeJson(name, value) {
  const path = join(temporaryDirectory, name);
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  return path;
}

function assertRejected(
  name,
  currentOpenApi,
  currentAsyncApi,
  currentRegistry,
  expectedText,
) {
  const openApi = writeJson(`${name}.openapi.json`, currentOpenApi);
  const asyncApi = writeJson(`${name}.asyncapi.json`, currentAsyncApi);
  const registry = writeJson(`${name}.registry.json`, currentRegistry);
  const result = spawnSync(
    process.execPath,
    [
      checker,
      "--current-openapi",
      openApi,
      "--current-asyncapi",
      asyncApi,
      "--current-registry",
      registry,
      "--baseline-openapi",
      openApiPath,
      "--baseline-asyncapi",
      asyncApiPath,
      "--baseline-registry",
      registryPath,
    ],
    { encoding: "utf8" },
  );
  const output = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
  if (result.status === 0 || !output.includes(expectedText)) {
    throw new Error(
      `Breaking gate self-test ${name} did not reject the mutation.\n${output}`,
    );
  }
}

function assertAccepted(name, currentOpenApi, currentAsyncApi, currentRegistry) {
  const openApiFile = writeJson(`${name}.openapi.json`, currentOpenApi);
  const asyncApiFile = writeJson(`${name}.asyncapi.json`, currentAsyncApi);
  const registryFile = writeJson(`${name}.registry.json`, currentRegistry);
  const result = spawnSync(
    process.execPath,
    [
      checker,
      "--current-openapi",
      openApiFile,
      "--current-asyncapi",
      asyncApiFile,
      "--current-registry",
      registryFile,
      "--baseline-openapi",
      openApiPath,
      "--baseline-asyncapi",
      asyncApiPath,
      "--baseline-registry",
      registryPath,
    ],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(
      `Breaking gate self-test ${name} rejected a versioned compatible change.\n` +
        `${result.stdout ?? ""}\n${result.stderr ?? ""}`,
    );
  }
}

const openApi = JSON.parse(readFileSync(openApiPath, "utf8"));
const asyncApi = JSON.parse(readFileSync(asyncApiPath, "utf8"));
const registry = JSON.parse(readFileSync(registryPath, "utf8"));

try {
  const removedPath = clone(openApi);
  const firstPath = Object.keys(removedPath.paths)[0];
  delete removedPath.paths[firstPath];
  assertRejected("removed-path", removedPath, asyncApi, registry, "OpenAPI path removed");

  const unversionedCompatibleChange = clone(openApi);
  const compatibleOperation = Object.values(unversionedCompatibleChange.paths)[0];
  const compatibleResponse = Object.values(compatibleOperation)[0].responses;
  const compatibleSuccess = Object.values(compatibleResponse).find(
    (response) => response.content?.["application/json"]?.schema?.properties?.data,
  );
  compatibleSuccess.content["application/json"].schema.properties.data.properties
    .futureOptionalField = { type: "string" };
  assertRejected(
    "unversioned-compatible-change",
    unversionedCompatibleChange,
    asyncApi,
    registry,
    "without a version advance",
  );

  const versionedCompatibleChange = clone(unversionedCompatibleChange);
  const versionedAsyncApi = clone(asyncApi);
  const versionedRegistry = clone(registry);
  versionedCompatibleChange.info.version = "1.0.1";
  versionedAsyncApi.info.version = "1.0.1";
  versionedRegistry.contractVersion = "1.0.1";
  const versionedOperation = Object.values(
    Object.values(versionedCompatibleChange.paths)[0],
  )[0];
  const [compatibleErrorStatus, compatibleErrorResponse] = Object.entries(
    versionedOperation.responses,
  ).find(([, response]) => Array.isArray(response["x-error-codes"]));
  compatibleErrorResponse["x-error-codes"].push("CONTRACT_TEST_ERROR");
  compatibleErrorResponse.content["application/json"].schema.properties.code.enum.push(
    "CONTRACT_TEST_ERROR",
  );
  versionedRegistry.errors.CONTRACT_TEST_ERROR = {
    code: "CONTRACT_TEST_ERROR",
    httpStatus: Number(compatibleErrorStatus),
    retryable: false,
    description: "Compatible new error-code self-test.",
  };
  assertAccepted(
    "versioned-compatible-change",
    versionedCompatibleChange,
    versionedAsyncApi,
    versionedRegistry,
  );

  const removedHttpConsumer = clone(openApi);
  const operationWithConsumer = Object.values(removedHttpConsumer.paths)
    .flatMap((pathItem) => Object.values(pathItem))
    .find((operation) => operation["x-consumers"]?.length > 0);
  const removedConsumer = operationWithConsumer["x-consumers"].shift();
  assertRejected(
    "removed-http-consumer",
    removedHttpConsumer,
    asyncApi,
    registry,
    `x-consumers entry ${removedConsumer} was removed`,
  );

  const changedSecurityScheme = clone(openApi);
  changedSecurityScheme.components.securitySchemes.BearerAuth.scheme = "basic";
  assertRejected(
    "changed-security-scheme",
    changedSecurityScheme,
    asyncApi,
    registry,
    "security scheme BearerAuth: scheme changed",
  );

  const narrowedResponse = clone(openApi);
  const firstPathItem = Object.values(narrowedResponse.paths)[0];
  const firstOperation = Object.values(firstPathItem)[0];
  const firstSuccess = Object.values(firstOperation.responses).find(
    (response) => response.content?.["application/json"]?.schema?.properties?.data,
  );
  const dataProperties = firstSuccess.content["application/json"].schema.properties.data.properties;
  const responseField = Object.keys(dataProperties)[0];
  delete dataProperties[responseField];
  assertRejected(
    "removed-response-field",
    narrowedResponse,
    asyncApi,
    registry,
    "property",
  );

  const widenedResponseEnum = clone(openApi);
  widenedResponseEnum.components.schemas.Currency.enum.push("USD");
  assertRejected(
    "widened-response-enum",
    widenedResponseEnum,
    asyncApi,
    registry,
    'enum value "USD" was added to an output',
  );

  const changedQueryEncoding = clone(openApi);
  const metricsOperation = changedQueryEncoding.paths[
    "/api/v1/analytics/metrics/{metricId}"
  ].get;
  const dimensions = metricsOperation.parameters.find(
    (parameter) => parameter.in === "query" && parameter.name === "dimensions",
  );
  dimensions.explode = false;
  assertRejected(
    "changed-query-encoding",
    changedQueryEncoding,
    asyncApi,
    registry,
    "parameter query:dimensions explode changed",
  );

  const removedResponseHeader = clone(openApi);
  delete removedResponseHeader.paths["/api/v1/me/context"].get.responses["200"]
    .headers["X-Trace-Id"];
  assertRejected(
    "removed-response-header",
    removedResponseHeader,
    asyncApi,
    registry,
    "header X-Trace-Id was removed",
  );

  const narrowedEvent = clone(asyncApi);
  const firstEnvelope = Object.values(narrowedEvent.components.schemas)[0];
  const payloadProperties = firstEnvelope.properties.payload.properties;
  const eventField = Object.keys(payloadProperties)[0];
  delete payloadProperties[eventField];
  assertRejected("removed-event-field", openApi, narrowedEvent, registry, "property");

  const widenedEventUnion = clone(asyncApi);
  const envelopeWithUnion = Object.values(widenedEventUnion.components.schemas).find(
    (schema) =>
      Object.values(schema.properties?.payload?.properties ?? {}).some(
        (property) => Array.isArray(property.anyOf),
      ),
  );
  const unionProperty = Object.values(
    envelopeWithUnion.properties.payload.properties,
  ).find((property) => Array.isArray(property.anyOf));
  unionProperty.anyOf.push({ type: "integer" });
  assertRejected(
    "widened-event-union",
    openApi,
    widenedEventUnion,
    registry,
    "alternatives were added to an output",
  );

  const narrowedChannelEnvironment = clone(asyncApi);
  const firstChannel = Object.values(narrowedChannelEnvironment.channels)[0];
  firstChannel.parameters.environment.enum = firstChannel.parameters.environment.enum.filter(
    (environment) => environment !== "prod",
  );
  assertRejected(
    "narrowed-channel-environment",
    openApi,
    narrowedChannelEnvironment,
    registry,
    'enum value "prod" was removed',
  );

  const changedBrokerProtocol = clone(asyncApi);
  changedBrokerProtocol.servers.development.protocol = "amqp";
  assertRejected(
    "changed-broker-protocol",
    openApi,
    changedBrokerProtocol,
    registry,
    "server development: protocol changed",
  );

  const changedHttpIdempotency = clone(openApi);
  const idempotentOperation = Object.values(changedHttpIdempotency.paths)
    .flatMap((pathItem) => Object.values(pathItem))
    .find((operation) => operation["x-idempotency"]?.required === true);
  idempotentOperation["x-idempotency"].replayBehavior =
    "All retries now fail with an unrelated result.";
  assertRejected(
    "changed-http-idempotency",
    changedHttpIdempotency,
    asyncApi,
    registry,
    "idempotency contract changed",
  );

  const changedEventIdempotency = clone(asyncApi);
  const firstMessage = Object.values(changedEventIdempotency.components.messages)[0];
  firstMessage["x-idempotency-key-format"] = "INCOMPATIBLE:{otherId}";
  assertRejected(
    "changed-event-idempotency",
    openApi,
    changedEventIdempotency,
    registry,
    "idempotency key format changed",
  );

  const changedEventContentType = clone(asyncApi);
  const contentTypeMessage = Object.values(
    changedEventContentType.components.messages,
  )[0];
  contentTypeMessage.contentType = "application/avro";
  assertRejected(
    "changed-event-content-type",
    openApi,
    changedEventContentType,
    registry,
    "contentType changed",
  );

  const changedErrorSemantics = clone(registry);
  const retryableError = Object.values(changedErrorSemantics.errors).find(
    (error) => error.retryable === true,
  );
  retryableError.retryable = false;
  assertRejected(
    "changed-error-retryability",
    openApi,
    asyncApi,
    changedErrorSemantics,
    "retryable changed",
  );

  console.log(
    "Breaking-change gate rejected path, ownership, security, query encoding, response header/schema/enum, event channel/encoding/union, error and idempotency mutations.",
  );
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true });
}
