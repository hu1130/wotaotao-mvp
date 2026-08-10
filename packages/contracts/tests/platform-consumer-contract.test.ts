import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  PLATFORM_ERROR_REGISTRY,
  PLATFORM_HTTP_CONTRACTS,
} from "../src/platform/http-contracts.js";
import { PLATFORM_EVENT_CONTRACTS } from "../src/platform/event-contracts.js";

type JsonObject = Record<string, unknown>;

function readJson(path: string): JsonObject {
  return JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8")) as JsonObject;
}

function allOpenApiOperations(openApi: JsonObject): JsonObject[] {
  const methods = new Set(["get", "post", "put", "patch", "delete"]);
  return Object.values(openApi.paths as Record<string, Record<string, JsonObject>>)
    .flatMap((path) => Object.entries(path)
      .filter(([method]) => methods.has(method))
      .map(([, operation]) => operation));
}

describe("full-platform consumer contracts", () => {
  it("exposes every operation to generated SDK consumers without trusting tenant headers", () => {
    const openApi = readJson("../platform/openapi.json");
    const operations = allOpenApiOperations(openApi);
    const operationIds = new Set(operations.map((operation) => operation.operationId));

    for (const contract of PLATFORM_HTTP_CONTRACTS) {
      expect(operationIds.has(contract.operationId)).toBe(true);
      expect(contract.consumer.length, contract.operationId).toBeGreaterThan(0);
    }

    const forbiddenHeaders = new Set([
      "x-enterprise-id",
      "x-merchant-id",
      "x-provider-id",
      "x-role",
      "x-user-id",
    ]);
    for (const operation of operations) {
      for (const parameter of (operation.parameters ?? []) as JsonObject[]) {
        if (parameter.in === "header") {
          expect(forbiddenHeaders.has(String(parameter.name).toLowerCase())).toBe(false);
        }
        if (parameter.in === "query" && parameter.required === true) {
          const parameterSchema = parameter.schema as JsonObject;
          const types = Array.isArray(parameterSchema.type)
            ? parameterSchema.type
            : [parameterSchema.type];
          const alternatives = (parameterSchema.anyOf ?? []) as JsonObject[];
          const acceptsNull =
            types.includes("null") ||
            alternatives.some((alternative) => alternative.type === "null");
          expect(
            acceptsNull,
            `${String(operation.operationId)} query ${String(parameter.name)} cannot be required and nullable`,
          ).toBe(false);
        }
      }
    }
  });

  it("publishes a complete provider/consumer ownership matrix", () => {
    const matrix = readJson("../platform/provider-consumer-matrix.json");
    const http = matrix.http as JsonObject[];
    const events = matrix.events as JsonObject[];
    expect(http).toHaveLength(PLATFORM_HTTP_CONTRACTS.length);
    expect(events).toHaveLength(PLATFORM_EVENT_CONTRACTS.length);
    expect(http.every((entry) =>
      typeof entry.provider === "string" &&
      Array.isArray(entry.consumers) &&
      entry.consumers.length > 0,
    )).toBe(true);
    expect(events.every((entry) =>
      typeof entry.provider === "string" &&
      Array.isArray(entry.consumers) &&
      entry.consumers.length > 0,
    )).toBe(true);
  });

  it("keeps Topic, error and idempotency registries consumable", () => {
    const registry = readJson("../platform/registry.json");
    const topics = registry.topics as JsonObject[];
    const errors = registry.errors as Record<string, JsonObject>;
    const idempotency = registry.idempotency as {
      http: JsonObject[];
      events: JsonObject[];
    };

    expect(topics).toHaveLength(PLATFORM_EVENT_CONTRACTS.length);
    expect(new Set(topics.map((topic) => topic.logicalTopic)).size).toBe(topics.length);
    expect(topics.every((topic) =>
      topic.physicalTopicTemplate === `wotao.{environment}.${String(topic.logicalTopic)}`,
    )).toBe(true);
    expect(Object.keys(errors).sort()).toEqual(Object.keys(PLATFORM_ERROR_REGISTRY).sort());
    expect(idempotency.http.every((item) => item.keyFormat && item.operationId)).toBe(true);
    expect(idempotency.events.every((item) => item.keyFormat && item.eventType)).toBe(true);
  });

  it("keeps contract, fixture, SDK and Mock package versions aligned", () => {
    const openApi = readJson("../platform/openapi.json");
    const asyncApi = readJson("../platform/asyncapi.json");
    const registry = readJson("../platform/registry.json");
    const fixtures = readJson("../platform/fixtures/http/index.json");
    const sdkPackage = readJson("../../platform-sdk/package.json");
    const mockPackage = readJson("../../../apps/platform-contract-mock/package.json");
    const versions = [
      (openApi.info as JsonObject).version,
      (asyncApi.info as JsonObject).version,
      registry.contractVersion,
      fixtures.contractVersion,
      sdkPackage.version,
      mockPackage.version,
    ];
    expect(new Set(versions).size).toBe(1);
    expect(versions[0]).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it("freezes the cross-document normalization decisions", () => {
    const serializedHttp = JSON.stringify(PLATFORM_HTTP_CONTRACTS);
    const serializedEvents = JSON.stringify(PLATFORM_EVENT_CONTRACTS);

    expect(serializedHttp).toContain("assignmentSnapshotVersion");
    expect(serializedEvents).toContain("WithdrawalStatusChanged");
    expect(serializedEvents).toContain("ownerType");
    expect(serializedEvents).toContain("ownerId");

    const publicationChargeFormats = new Set(
      [
        ...PLATFORM_HTTP_CONTRACTS
          .map((contract) => contract.idempotency.keyFormat)
          .filter((value): value is string => value?.startsWith("PUBLICATION_CHARGE:") === true),
        ...PLATFORM_EVENT_CONTRACTS
          .map((contract) => contract.idempotencyKey)
          .filter((value) => value.startsWith("PUBLICATION_CHARGE:")),
      ],
    );
    expect(publicationChargeFormats).toEqual(
      new Set(["PUBLICATION_CHARGE:{channelPublicationId}"]),
    );
    expect(serializedHttp).not.toContain("PUB_CHARGE_RESERVE:");
    expect(serializedEvents).not.toContain("PUB_CHARGE_RESERVE:");
  });

  it("contains deterministic synthetic fixtures rather than credentials", () => {
    const httpFixtures = JSON.stringify(readJson("../platform/fixtures/http/index.json"));
    const eventFixtures = JSON.stringify(readJson("../platform/fixtures/events/index.json"));
    for (const content of [httpFixtures, eventFixtures]) {
      expect(content).not.toMatch(/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/);
      expect(content).not.toMatch(/\bsk-[A-Za-z0-9_-]{20,}\b/);
      expect(content).not.toMatch(/\bAKIA[0-9A-Z]{16}\b/);
    }
  });
});
