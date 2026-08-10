import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const HTTP_METHODS = new Set([
  "get",
  "post",
  "put",
  "patch",
  "delete",
  "head",
  "options",
]);

function parseArgs(argv) {
  const args = {
    baseRef: null,
    allowBootstrap: false,
    currentOpenApi: "packages/contracts/platform/openapi.json",
    currentAsyncApi: "packages/contracts/platform/asyncapi.json",
    currentRegistry: "packages/contracts/platform/registry.json",
    baselineOpenApi: null,
    baselineAsyncApi: null,
    baselineRegistry: null,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--base-ref") {
      const next = argv[++index];
      if (!next || next.startsWith("--")) {
        throw new Error("--base-ref requires a non-empty trusted git ref");
      }
      args.baseRef = next;
    }
    else if (value === "--allow-bootstrap") args.allowBootstrap = true;
    else if (value === "--current-openapi")
      args.currentOpenApi = argv[++index] ?? args.currentOpenApi;
    else if (value === "--current-asyncapi")
      args.currentAsyncApi = argv[++index] ?? args.currentAsyncApi;
    else if (value === "--current-registry")
      args.currentRegistry = argv[++index] ?? args.currentRegistry;
    else if (value === "--baseline-openapi")
      args.baselineOpenApi = argv[++index] ?? args.baselineOpenApi;
    else if (value === "--baseline-asyncapi")
      args.baselineAsyncApi = argv[++index] ?? args.baselineAsyncApi;
    else if (value === "--baseline-registry")
      args.baselineRegistry = argv[++index] ?? args.baselineRegistry;
    else throw new Error(`Unknown argument: ${value}`);
  }
  return args;
}

function readJsonFile(path) {
  return JSON.parse(readFileSync(resolve(path), "utf8"));
}

function readJsonAtRef(ref, path) {
  const exists = spawnSync("git", ["cat-file", "-e", `${ref}:${path}`], {
    stdio: "ignore",
  });
  if (exists.status !== 0) return null;

  let content;
  try {
    content = execFileSync("git", ["show", `${ref}:${path}`], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    throw new Error(`Could not read ${ref}:${path}: ${error.message}`);
  }
  try {
    return JSON.parse(content);
  } catch (error) {
    throw new Error(`Invalid JSON at ${ref}:${path}: ${error.message}`);
  }
}

function verifyBaseRef(ref) {
  try {
    execFileSync("git", ["rev-parse", "--verify", `${ref}^{commit}`], {
      stdio: "ignore",
    });
  } catch {
    throw new Error(`Base ref does not resolve to a commit: ${ref}`);
  }
}

function loadBaseline(args, path, baselinePath) {
  if (args.baseRef) {
    const fromGit = readJsonAtRef(args.baseRef, path);
    if (fromGit) return { document: fromGit, source: `${args.baseRef}:${path}` };
    if (!args.allowBootstrap) {
      throw new Error(
        `Baseline contract ${args.baseRef}:${path} does not exist. ` +
          "Use --allow-bootstrap only for the first introduction of a contract family.",
      );
    }
  }

  if (existsSync(resolve(baselinePath))) {
    return { document: readJsonFile(baselinePath), source: baselinePath };
  }

  if (args.allowBootstrap) return { document: null, source: "bootstrap" };
  throw new Error(`Baseline contract not found: ${baselinePath}`);
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function authSignature(auth) {
  const value = asRecord(auth);
  return {
    mode: value.mode ?? null,
    roles: asArray(value.roles),
    scopes: asArray(value.scopes),
    servicePrincipals: asArray(value.servicePrincipals),
  };
}

function idempotencySignature(idempotency) {
  const value = asRecord(idempotency);
  return {
    required: value.required ?? null,
    source: value.source ?? null,
    headerName: value.headerName ?? null,
    keyFormat: value.keyFormat ?? null,
    replayBehavior: value.replayBehavior ?? null,
    payloadConflictHttpStatus: value.payloadConflictHttpStatus ?? null,
  };
}

function schemaSignature(schema) {
  if (!schema || typeof schema !== "object") return null;
  return {
    type: schema.type ?? null,
    ref: schema.$ref ?? null,
    format: schema.format ?? null,
    nullable: schema.nullable ?? null,
    pattern: schema.pattern ?? null,
    minimum: schema.minimum ?? null,
    maximum: schema.maximum ?? null,
    minLength: schema.minLength ?? null,
    maxLength: schema.maxLength ?? null,
    minItems: schema.minItems ?? null,
    maxItems: schema.maxItems ?? null,
    uniqueItems: schema.uniqueItems ?? null,
    const: schema.const ?? null,
    default: schema.default ?? null,
    additionalProperties:
      typeof schema.additionalProperties === "boolean"
        ? schema.additionalProperties
        : null,
  };
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function compareSchema(
  oldSchema,
  newSchema,
  location,
  changes,
  visited,
  direction = "invariant",
) {
  if (!oldSchema || typeof oldSchema !== "object") return;
  if (!newSchema || typeof newSchema !== "object") {
    changes.push(`${location}: schema was removed`);
    return;
  }

  const visitKey = `${location}:${JSON.stringify(schemaSignature(oldSchema))}`;
  if (visited.has(visitKey)) return;
  visited.add(visitKey);

  const oldSignature = schemaSignature(oldSchema);
  const newSignature = schemaSignature(newSchema);
  for (const field of [
    "type",
    "ref",
    "format",
    "nullable",
    "pattern",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "uniqueItems",
    "const",
    "default",
    "additionalProperties",
  ]) {
    const oldValue = JSON.stringify(oldSignature[field]);
    const newValue = JSON.stringify(newSignature[field]);
    if (oldValue !== newValue) {
      changes.push(
        `${location}: ${field} changed from ${oldValue} to ${newValue}`,
      );
    }
  }

  const oldEnum = asArray(oldSchema.enum);
  const newEnumItems = asArray(newSchema.enum);
  const newEnum = new Set(newEnumItems);
  for (const value of oldEnum) {
    if (!newEnum.has(value)) {
      changes.push(`${location}: enum value ${JSON.stringify(value)} was removed`);
    }
  }
  if (oldEnum.length === 0 && newEnumItems.length > 0) {
    changes.push(`${location}: enum constraint was added`);
  } else if (direction !== "input" && direction !== "open-enum-output") {
    const oldEnumSet = new Set(oldEnum);
    for (const value of newEnumItems) {
      if (!oldEnumSet.has(value)) {
        changes.push(
          `${location}: enum value ${JSON.stringify(value)} was added to an output`,
        );
      }
    }
  }

  const oldRequired = new Set(asArray(oldSchema.required));
  const newRequired = new Set(asArray(newSchema.required));
  for (const name of oldRequired) {
    if (!newRequired.has(name)) {
      changes.push(`${location}: required field ${name} is no longer guaranteed`);
    }
  }
  for (const name of newRequired) {
    if (!oldRequired.has(name)) {
      changes.push(`${location}: field ${name} became required`);
    }
  }

  const oldProperties = asRecord(oldSchema.properties);
  const newProperties = asRecord(newSchema.properties);
  for (const [name, child] of Object.entries(oldProperties)) {
    if (!(name in newProperties)) {
      changes.push(`${location}: property ${name} was removed`);
      continue;
    }
    const childDirection =
      direction === "error-output"
        ? name === "code"
          ? "open-enum-output"
          : "output"
        : direction;
    compareSchema(
      child,
      newProperties[name],
      `${location}.properties.${name}`,
      changes,
      visited,
      childDirection,
    );
  }

  if (oldSchema.items) {
    compareSchema(
      oldSchema.items,
      newSchema.items,
      `${location}.items`,
      changes,
      visited,
      direction,
    );
  }

  if (
    oldSchema.additionalProperties &&
    typeof oldSchema.additionalProperties === "object"
  ) {
    compareSchema(
      oldSchema.additionalProperties,
      newSchema.additionalProperties,
      `${location}.additionalProperties`,
      changes,
      visited,
      direction,
    );
  }

  for (const keyword of ["oneOf", "anyOf", "allOf"]) {
    const oldItems = asArray(oldSchema[keyword]);
    const newItems = asArray(newSchema[keyword]);
    if (newItems.length < oldItems.length) {
      changes.push(`${location}: ${keyword} alternatives were removed`);
    }
    const inputUnionWasExpanded =
      direction === "input" && keyword !== "allOf" && newItems.length > oldItems.length;
    if (newItems.length > oldItems.length && !inputUnionWasExpanded) {
      changes.push(`${location}: ${keyword} alternatives were added to an output`);
    }

    const unmatchedNew = new Set(newItems.map((_, index) => index));
    const pairs = [];
    for (let oldIndex = 0; oldIndex < oldItems.length; oldIndex += 1) {
      const exactIndex = newItems.findIndex(
        (item, newIndex) =>
          unmatchedNew.has(newIndex) && stableJson(item) === stableJson(oldItems[oldIndex]),
      );
      if (exactIndex >= 0) {
        unmatchedNew.delete(exactIndex);
        continue;
      }
      const fallbackIndex = unmatchedNew.values().next().value;
      if (fallbackIndex !== undefined) {
        unmatchedNew.delete(fallbackIndex);
        pairs.push([oldIndex, fallbackIndex]);
      }
    }
    for (const [oldIndex, newIndex] of pairs) {
      if (newItems[newIndex]) {
        compareSchema(
          oldItems[oldIndex],
          newItems[newIndex],
          `${location}.${keyword}[${oldIndex}]`,
          changes,
          visited,
          direction,
        );
      }
    }
  }
}

function compareParameters(oldOperation, newOperation, location, changes) {
  const key = (parameter) => `${parameter.in}:${parameter.name}`;
  const oldParameters = new Map(
    asArray(oldOperation.parameters).map((parameter) => [key(parameter), parameter]),
  );
  const newParameters = new Map(
    asArray(newOperation.parameters).map((parameter) => [key(parameter), parameter]),
  );

  for (const [name, parameter] of oldParameters) {
    const next = newParameters.get(name);
    if (!next) {
      changes.push(`${location}: parameter ${name} was removed`);
      continue;
    }
    if (!parameter.required && next.required) {
      changes.push(`${location}: parameter ${name} became required`);
    }
    for (const field of ["style", "explode", "allowReserved", "allowEmptyValue"]) {
      if (parameter[field] !== next[field]) {
        changes.push(`${location}: parameter ${name} ${field} changed`);
      }
    }
    if (stableJson(parameter.content) !== stableJson(next.content)) {
      changes.push(`${location}: parameter ${name} content encoding changed`);
    }
    compareSchema(
      parameter.schema,
      next.schema,
      `${location}.parameters.${name}`,
      changes,
      new Set(),
      "input",
    );
  }

  for (const [name, parameter] of newParameters) {
    if (!oldParameters.has(name) && parameter.required) {
      changes.push(`${location}: new required parameter ${name} was added`);
    }
  }
}

function compareOpenApi(oldDocument, newDocument) {
  const changes = [];
  const oldPaths = asRecord(oldDocument.paths);
  const newPaths = asRecord(newDocument.paths);

  for (const [path, oldPathItem] of Object.entries(oldPaths)) {
    const newPathItem = newPaths[path];
    if (!newPathItem) {
      changes.push(`OpenAPI path removed: ${path}`);
      continue;
    }
    for (const [method, oldOperation] of Object.entries(oldPathItem)) {
      if (!HTTP_METHODS.has(method)) continue;
      const newOperation = newPathItem[method];
      const location = `${method.toUpperCase()} ${path}`;
      if (!newOperation) {
        changes.push(`OpenAPI operation removed: ${location}`);
        continue;
      }
      if (oldOperation.operationId !== newOperation.operationId) {
        changes.push(
          `${location}: operationId changed from ${oldOperation.operationId} to ${newOperation.operationId}`,
        );
      }
      if (
        JSON.stringify(oldOperation.security ?? []) !==
        JSON.stringify(newOperation.security ?? [])
      ) {
        changes.push(`${location}: security requirements changed`);
      }
      if (
        JSON.stringify(authSignature(oldOperation["x-auth"])) !==
        JSON.stringify(authSignature(newOperation["x-auth"]))
      ) {
        changes.push(`${location}: authorization contract changed`);
      }
      if (
        JSON.stringify(idempotencySignature(oldOperation["x-idempotency"])) !==
        JSON.stringify(idempotencySignature(newOperation["x-idempotency"]))
      ) {
        changes.push(`${location}: idempotency contract changed`);
      }
      for (const field of ["x-system", "x-visibility", "x-owner", "x-producer"]) {
        if (oldOperation[field] !== newOperation[field]) {
          changes.push(`${location}: ${field} ownership metadata changed`);
        }
      }
      for (const field of ["x-consumers", "x-audience"]) {
        for (const participant of asArray(oldOperation[field])) {
          if (!asArray(newOperation[field]).includes(participant)) {
            changes.push(`${location}: ${field} entry ${participant} was removed`);
          }
        }
      }
      compareParameters(oldOperation, newOperation, location, changes);
      if (!oldOperation.requestBody?.required && newOperation.requestBody?.required) {
        changes.push(`${location}: request body became required`);
      }
      compareSchema(
        oldOperation.requestBody?.content?.["application/json"]?.schema,
        newOperation.requestBody?.content?.["application/json"]?.schema,
        `${location}.requestBody`,
        changes,
        new Set(),
        "input",
      );
      for (const status of Object.keys(asRecord(oldOperation.responses))) {
        if (!(status in asRecord(newOperation.responses))) {
          changes.push(`${location}: response ${status} was removed`);
          continue;
        }
        compareSchema(
          oldOperation.responses?.[status]?.content?.["application/json"]?.schema,
          newOperation.responses?.[status]?.content?.["application/json"]?.schema,
          `${location}.responses.${status}`,
          changes,
          new Set(),
          Array.isArray(oldOperation.responses?.[status]?.["x-error-codes"])
            ? "error-output"
            : "output",
        );
        const oldHeaders = asRecord(oldOperation.responses?.[status]?.headers);
        const nextHeaders = asRecord(newOperation.responses?.[status]?.headers);
        const nextHeadersByName = new Map(
          Object.entries(nextHeaders).map(([name, header]) => [
            name.toLowerCase(),
            header,
          ]),
        );
        for (const [headerName, header] of Object.entries(oldHeaders)) {
          const nextHeader = nextHeadersByName.get(headerName.toLowerCase());
          if (!nextHeader) {
            changes.push(`${location}: response ${status} header ${headerName} was removed`);
            continue;
          }
          for (const field of ["$ref", "required", "style", "explode"]) {
            if (header[field] !== nextHeader[field]) {
              changes.push(
                `${location}: response ${status} header ${headerName} ${field} changed`,
              );
            }
          }
          compareSchema(
            header.schema,
            nextHeader.schema,
            `${location}.responses.${status}.headers.${headerName}`,
            changes,
            new Set(),
            "output",
          );
        }
      }
    }
  }

  const oldSchemas = asRecord(oldDocument.components?.schemas);
  const newSchemas = asRecord(newDocument.components?.schemas);
  for (const [name, schema] of Object.entries(oldSchemas)) {
    if (!(name in newSchemas)) {
      changes.push(`OpenAPI component schema removed: ${name}`);
      continue;
    }
    compareSchema(
      schema,
      newSchemas[name],
      `components.schemas.${name}`,
      changes,
      new Set(),
      "invariant",
    );
  }

  const oldSecuritySchemes = asRecord(oldDocument.components?.securitySchemes);
  const newSecuritySchemes = asRecord(newDocument.components?.securitySchemes);
  for (const [name, scheme] of Object.entries(oldSecuritySchemes)) {
    const next = newSecuritySchemes[name];
    if (!next) {
      changes.push(`OpenAPI security scheme removed: ${name}`);
      continue;
    }
    for (const field of ["type", "scheme", "in", "name", "bearerFormat", "openIdConnectUrl"]) {
      if (scheme[field] !== next[field]) {
        changes.push(`OpenAPI security scheme ${name}: ${field} changed`);
      }
    }
    if (stableJson(scheme.flows) !== stableJson(next.flows)) {
      changes.push(`OpenAPI security scheme ${name}: OAuth flows changed`);
    }
  }
  return changes;
}

function compareAsyncApi(oldDocument, newDocument) {
  const changes = [];
  const oldChannels = asRecord(oldDocument.channels);
  const newChannels = asRecord(newDocument.channels);
  for (const [name, channel] of Object.entries(oldChannels)) {
    const next = newChannels[name];
    if (!next) {
      changes.push(`AsyncAPI channel removed: ${name}`);
      continue;
    }
    if (channel.address !== next.address) {
      changes.push(
        `AsyncAPI channel ${name}: address changed from ${channel.address} to ${next.address}`,
      );
    }
    if (channel["x-producer"] !== next["x-producer"]) {
      changes.push(`AsyncAPI channel ${name}: producer changed`);
    }
    if (channel["x-logical-topic"] !== next["x-logical-topic"]) {
      changes.push(`AsyncAPI channel ${name}: logical topic metadata changed`);
    }
    if (stableJson(channel.bindings) !== stableJson(next.bindings)) {
      changes.push(`AsyncAPI channel ${name}: bindings changed`);
    }
    for (const consumer of asArray(channel["x-consumers"])) {
      if (!asArray(next["x-consumers"]).includes(consumer)) {
        changes.push(`AsyncAPI channel ${name}: consumer ${consumer} was removed`);
      }
    }
    for (const audience of asArray(channel["x-audience"])) {
      if (!asArray(next["x-audience"]).includes(audience)) {
        changes.push(`AsyncAPI channel ${name}: audience ${audience} was removed`);
      }
    }
    const oldMessages = Object.keys(asRecord(channel.messages));
    const newMessages = asRecord(next.messages);
    for (const message of oldMessages) {
      if (!(message in newMessages)) {
        changes.push(`AsyncAPI channel ${name}: message ${message} was removed`);
      } else if (
        stableJson(channel.messages[message]) !== stableJson(newMessages[message])
      ) {
        changes.push(`AsyncAPI channel ${name}: message ${message} binding changed`);
      }
    }
    const oldParameters = asRecord(channel.parameters);
    const newParameters = asRecord(next.parameters);
    for (const [parameterName, parameter] of Object.entries(oldParameters)) {
      const nextParameter = newParameters[parameterName];
      if (!nextParameter) {
        changes.push(
          `AsyncAPI channel ${name}: parameter ${parameterName} was removed`,
        );
        continue;
      }
      if (parameter.required !== nextParameter.required) {
        changes.push(
          `AsyncAPI channel ${name}: parameter ${parameterName} required changed`,
        );
      }
      compareSchema(
        parameter,
        nextParameter,
        `asyncapi.channels.${name}.parameters.${parameterName}`,
        changes,
        new Set(),
        "input",
      );
    }
  }

  const oldOperations = asRecord(oldDocument.operations);
  const newOperations = asRecord(newDocument.operations);
  for (const [name, operation] of Object.entries(oldOperations)) {
    const next = newOperations[name];
    if (!next) {
      changes.push(`AsyncAPI operation removed: ${name}`);
      continue;
    }
    for (const field of [
      "action",
      "channel",
      "messages",
      "reply",
      "security",
      "bindings",
      "traits",
      "x-owner",
    ]) {
      if (stableJson(operation[field]) !== stableJson(next[field])) {
        changes.push(`AsyncAPI operation ${name}: ${field} changed`);
      }
    }
    for (const consumer of asArray(operation["x-consumers"])) {
      if (!asArray(next["x-consumers"]).includes(consumer)) {
        changes.push(`AsyncAPI operation ${name}: consumer ${consumer} was removed`);
      }
    }
  }

  const oldServers = asRecord(oldDocument.servers);
  const newServers = asRecord(newDocument.servers);
  for (const [name, server] of Object.entries(oldServers)) {
    const next = newServers[name];
    if (!next) {
      changes.push(`AsyncAPI server removed: ${name}`);
      continue;
    }
    for (const field of ["protocol", "protocolVersion", "pathname"]) {
      if (server[field] !== next[field]) {
        changes.push(`AsyncAPI server ${name}: ${field} changed`);
      }
    }
    for (const field of ["security", "bindings", "variables"]) {
      if (stableJson(server[field]) !== stableJson(next[field])) {
        changes.push(`AsyncAPI server ${name}: ${field} changed`);
      }
    }
  }

  const oldMessages = asRecord(oldDocument.components?.messages);
  const newMessages = asRecord(newDocument.components?.messages);
  for (const [name, message] of Object.entries(oldMessages)) {
    const next = newMessages[name];
    if (!next) {
      changes.push(`AsyncAPI component message removed: ${name}`);
      continue;
    }
    for (const field of [
      "name",
      "contentType",
      "headers",
      "correlationId",
      "bindings",
      "traits",
      "x-pii-policy",
    ]) {
      if (stableJson(message[field]) !== stableJson(next[field])) {
        changes.push(`AsyncAPI component message ${name}: ${field} changed`);
      }
    }
    compareSchema(
      message.payload,
      next.payload,
      `asyncapi.components.messages.${name}.payload`,
      changes,
      new Set(),
      "output",
    );
    if (
      message["x-schema-version"] !== undefined &&
      message["x-schema-version"] !== next["x-schema-version"]
    ) {
      changes.push(`AsyncAPI component message ${name}: schema version changed`);
    }
    if (
      message["x-idempotency-key-format"] !== undefined &&
      message["x-idempotency-key-format"] !==
      next["x-idempotency-key-format"]
    ) {
      changes.push(
        `AsyncAPI component message ${name}: idempotency key format changed`,
      );
    }
    if (
      message["x-idempotency-conflict-policy"] !== undefined &&
      message["x-idempotency-conflict-policy"] !==
      next["x-idempotency-conflict-policy"]
    ) {
      changes.push(
        `AsyncAPI component message ${name}: idempotency conflict policy changed`,
      );
    }
  }

  const oldSchemas = asRecord(oldDocument.components?.schemas);
  const newSchemas = asRecord(newDocument.components?.schemas);
  for (const [name, schema] of Object.entries(oldSchemas)) {
    if (!(name in newSchemas)) {
      changes.push(`AsyncAPI component schema removed: ${name}`);
      continue;
    }
    compareSchema(
      schema,
      newSchemas[name],
      `asyncapi.components.schemas.${name}`,
      changes,
      new Set(),
      "output",
    );
  }
  return changes;
}

function compareRegistry(oldRegistry, newRegistry) {
  const changes = [];
  if (oldRegistry.topicAddressRule !== newRegistry.topicAddressRule) {
    changes.push("Registry topic address rule changed");
  }

  const oldErrors = asRecord(oldRegistry.errors);
  const newErrors = asRecord(newRegistry.errors);
  for (const [code, error] of Object.entries(oldErrors)) {
    const next = newErrors[code];
    if (!next) {
      changes.push(`Registry error code removed: ${code}`);
      continue;
    }
    for (const field of ["code", "httpStatus", "retryable"]) {
      if (error[field] !== next[field]) {
        changes.push(
          `Registry error ${code}: ${field} changed from ${JSON.stringify(error[field])} to ${JSON.stringify(next[field])}`,
        );
      }
    }
  }

  const oldTopics = new Map(
    asArray(oldRegistry.topics).map((topic) => [topic.eventType, topic]),
  );
  const newTopics = new Map(
    asArray(newRegistry.topics).map((topic) => [topic.eventType, topic]),
  );
  for (const [eventType, topic] of oldTopics) {
    const next = newTopics.get(eventType);
    if (!next) {
      changes.push(`Registry topic removed for event: ${eventType}`);
      continue;
    }
    for (const field of [
      "messageKind",
      "logicalTopic",
      "physicalTopicTemplate",
      "schemaVersion",
      "producer",
      "schema",
      "idempotencyKeyFormat",
      "conflictPolicy",
    ]) {
      if (topic[field] !== next[field]) {
        changes.push(`Registry topic ${eventType}: ${field} changed`);
      }
    }
    for (const field of ["consumers", "audience"]) {
      for (const participant of asArray(topic[field])) {
        if (!asArray(next[field]).includes(participant)) {
          changes.push(
            `Registry topic ${eventType}: ${field} entry ${participant} was removed`,
          );
        }
      }
    }
    if (stableJson(topic.compatibility) !== stableJson(next.compatibility)) {
      changes.push(`Registry topic ${eventType}: compatibility policy changed`);
    }
  }

  function compareIdempotencyEntries(oldEntries, newEntries, keyField, family) {
    const nextByKey = new Map(
      asArray(newEntries).map((entry) => [entry[keyField], entry]),
    );
    for (const entry of asArray(oldEntries)) {
      const key = entry[keyField];
      const next = nextByKey.get(key);
      if (!next) {
        changes.push(`Registry ${family} idempotency entry removed: ${key}`);
        continue;
      }
      for (const field of Object.keys(entry)) {
        if (stableJson(entry[field]) !== stableJson(next[field])) {
          changes.push(`Registry ${family} idempotency ${key}: ${field} changed`);
        }
      }
    }
  }

  compareIdempotencyEntries(
    oldRegistry.idempotency?.http,
    newRegistry.idempotency?.http,
    "operationId",
    "HTTP",
  );
  compareIdempotencyEntries(
    oldRegistry.idempotency?.events,
    newRegistry.idempotency?.events,
    "eventType",
    "event",
  );
  return changes;
}

function parseSemver(value, label) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(String(value));
  if (!match) throw new Error(`${label} must be a major.minor.patch SemVer: ${value}`);
  return match.slice(1).map(Number);
}

function compareSemver(left, right) {
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) return left[index] - right[index];
  }
  return 0;
}

const args = parseArgs(process.argv.slice(2));
if (args.baseRef) verifyBaseRef(args.baseRef);
const currentOpenApi = readJsonFile(args.currentOpenApi);
const currentAsyncApi = readJsonFile(args.currentAsyncApi);
const currentRegistry = readJsonFile(args.currentRegistry);
const openApiVersion = currentOpenApi.info?.version;
const asyncApiVersion = currentAsyncApi.info?.version;
const registryVersion = currentRegistry.contractVersion;
if (
  !openApiVersion ||
  openApiVersion !== asyncApiVersion ||
  openApiVersion !== registryVersion
) {
  throw new Error(
    `OpenAPI/AsyncAPI/registry versions must match; received ${openApiVersion}, ${asyncApiVersion} and ${registryVersion}.`,
  );
}
args.baselineOpenApi ??=
  `packages/contracts/platform/baseline/${openApiVersion}/openapi.json`;
args.baselineAsyncApi ??=
  `packages/contracts/platform/baseline/${openApiVersion}/asyncapi.json`;
args.baselineRegistry ??=
  `packages/contracts/platform/baseline/${openApiVersion}/registry.json`;
const baselineOpenApi = loadBaseline(
  args,
  args.currentOpenApi,
  args.baselineOpenApi,
);
const baselineAsyncApi = loadBaseline(
  args,
  args.currentAsyncApi,
  args.baselineAsyncApi,
);
const baselineRegistry = loadBaseline(
  args,
  args.currentRegistry,
  args.baselineRegistry,
);

if (
  !baselineOpenApi.document ||
  !baselineAsyncApi.document ||
  !baselineRegistry.document
) {
  console.log("Contract compatibility bootstrap: no previous full-platform contract exists.");
  process.exit(0);
}

const changes = [
  ...compareOpenApi(baselineOpenApi.document, currentOpenApi),
  ...compareAsyncApi(baselineAsyncApi.document, currentAsyncApi),
  ...compareRegistry(baselineRegistry.document, currentRegistry),
];
const baselineVersions = [
  baselineOpenApi.document.info?.version,
  baselineAsyncApi.document.info?.version,
  baselineRegistry.document.contractVersion,
];
if (new Set(baselineVersions).size !== 1) {
  throw new Error(
    `Baseline OpenAPI/AsyncAPI/registry versions do not match: ${baselineVersions.join(", ")}`,
  );
}
const baselineVersion = baselineVersions[0];
const versionOrder = compareSemver(
  parseSemver(openApiVersion, "Current contract version"),
  parseSemver(baselineVersion, "Baseline contract version"),
);
const documentsChanged =
  stableJson(baselineOpenApi.document) !== stableJson(currentOpenApi) ||
  stableJson(baselineAsyncApi.document) !== stableJson(currentAsyncApi) ||
  stableJson(baselineRegistry.document) !== stableJson(currentRegistry);
if (versionOrder < 0) {
  changes.push(
    `Contract version regressed from ${baselineVersion} to ${openApiVersion}`,
  );
} else if (documentsChanged && versionOrder === 0) {
  changes.push(
    `Contract artifacts changed without a version advance from ${baselineVersion}`,
  );
}

if (changes.length > 0) {
  console.error(
    `Breaking contract changes detected against ${baselineOpenApi.source}, ${baselineAsyncApi.source} and ${baselineRegistry.source}:`,
  );
  for (const change of changes) console.error(`- ${change}`);
  process.exit(1);
}

console.log(
  `No breaking contract changes detected against ${baselineOpenApi.source}, ${baselineAsyncApi.source} and ${baselineRegistry.source}.`,
);
