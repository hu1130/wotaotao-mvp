import { describe, expect, it } from "vitest";
import {
  API_OPERATION_MAP_IS_COMPLETE,
  BUSINESS_ID_PREFIXES,
  CONTENT_GENERATION_STATUS_TRANSITIONS,
  CONTENT_STATUS_TRANSITIONS,
  INQUIRY_STATUS_TRANSITIONS,
  MVP_API_CONTRACTS,
  MVP_MODULES,
  PUBLICATION_STATUS_TRANSITIONS,
  hasBusinessIdPrefix,
  isErrorResponse,
  isIsoUtcDateTime,
  isPage,
  isSuccessResponse,
  validateMvpApiContracts,
  type CreatePublicationInput,
  type ErrorResponse,
  type SuccessResponse,
} from "../src/index.js";

describe("MVP API manifest", () => {
  it("has unique, internally consistent operations", () => {
    expect(API_OPERATION_MAP_IS_COMPLETE).toBe(true);
    expect(validateMvpApiContracts()).toEqual([]);
  });

  it("covers every API-owning module and keeps integration API-free", () => {
    const modulesWithOperations = new Set<string>(
      MVP_API_CONTRACTS.map((contract) => contract.module),
    );

    for (const module of MVP_MODULES) {
      if (module.module === "08_INTEGRATION") {
        expect(modulesWithOperations.has(module.module)).toBe(false);
      } else {
        expect(modulesWithOperations.has(module.module)).toBe(true);
      }
    }
  });

  it("requires idempotency for publication creation and retry", () => {
    const idempotentOperations = MVP_API_CONTRACTS.filter(
      (contract) => contract.idempotency === "BODY_REQUIRED",
    ).map((contract) => contract.operationId);

    expect(idempotentOperations).toEqual([
      "publishing.create",
      "publishing.retry",
    ]);

    const input = {
      contentId: "cnt_contract_001",
      accountId: "acc_contract_001",
      channel: "DOUYIN",
      idempotencyKey: "publish-contract-001",
    } satisfies CreatePublicationInput;
    expect(input.idempotencyKey).toBeTruthy();
  });
});

describe("shared state and ID conventions", () => {
  it("freezes the allowed state transitions", () => {
    expect(CONTENT_STATUS_TRANSITIONS.PENDING_REVIEW).toEqual([
      "APPROVED",
      "REJECTED",
    ]);
    expect(CONTENT_GENERATION_STATUS_TRANSITIONS.FAILED).toEqual([]);
    expect(PUBLICATION_STATUS_TRANSITIONS.SUCCEEDED).toEqual([]);
    expect(PUBLICATION_STATUS_TRANSITIONS.FAILED).toEqual(["QUEUED"]);
    expect(INQUIRY_STATUS_TRANSITIONS.WON).toEqual([]);
    expect(INQUIRY_STATUS_TRANSITIONS.LOST).toEqual([]);
  });

  it("recognizes every documented business ID prefix", () => {
    for (const [kind, prefix] of Object.entries(BUSINESS_ID_PREFIXES)) {
      expect(
        hasBusinessIdPrefix(
          kind as keyof typeof BUSINESS_ID_PREFIXES,
          `${prefix}contract_001`,
        ),
      ).toBe(true);
      expect(
        hasBusinessIdPrefix(
          kind as keyof typeof BUSINESS_ID_PREFIXES,
          "wrong_contract_001",
        ),
      ).toBe(false);
    }
  });

  it("accepts only ISO 8601 UTC timestamps", () => {
    expect(isIsoUtcDateTime("2026-07-30T04:00:00Z")).toBe(true);
    expect(isIsoUtcDateTime("2026-07-30T04:00:00.000Z")).toBe(true);
    expect(isIsoUtcDateTime("2026-02-31T04:00:00Z")).toBe(false);
    expect(isIsoUtcDateTime("2026-07-30 12:00:00")).toBe(false);
    expect(isIsoUtcDateTime("2026-07-30T12:00:00+08:00")).toBe(false);
  });
});

describe("response envelope guards", () => {
  it("recognizes a paginated success response", () => {
    const response = {
      data: { items: [], page: 1, pageSize: 20, total: 0 },
      requestId: "req-contract-001",
    } satisfies SuccessResponse<{
      items: unknown[];
      page: number;
      pageSize: number;
      total: number;
    }>;

    expect(isSuccessResponse(response)).toBe(true);
    expect(isPage(response.data)).toBe(true);
  });

  it("recognizes a stable error response and rejects unknown codes", () => {
    const response = {
      errorCode: "CONTENT_NOT_APPROVED",
      message: "内容尚未审核通过",
      requestId: "req-contract-002",
    } satisfies ErrorResponse;

    expect(isErrorResponse(response)).toBe(true);
    expect(
      isErrorResponse({
        ...response,
        errorCode: "SOME_MODULE_LOCAL_ALIAS",
      }),
    ).toBe(false);
  });
});
