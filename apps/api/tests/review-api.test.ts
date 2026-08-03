import { PrismaClient } from "@prisma/client";
import {
  hasBusinessIdPrefix,
  isErrorResponse,
  isIsoUtcDateTime,
  isPage,
  isSuccessResponse,
} from "@wotao/contracts";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createApp } from "../src/app.js";
import { AppError } from "../src/domain/app-error.js";
import { requireApprovedContent } from "../src/modules/review/review-service.js";
import { seedDatabase } from "../prisma/seed-data.js";

const prisma = new PrismaClient();
const operatorHeaders = {
  "x-role": "OPERATOR",
  "x-user-id": "op_test_001",
  "x-user-name": encodeURIComponent("测试运营"),
};

const { app } = await createApp({ prisma });

beforeAll(async () => {
  await app.ready();
});

beforeEach(async () => {
  await seedDatabase(prisma);
});

afterAll(async () => {
  await app.close();
});

describe("review queue and detail", () => {
  it("returns a paginated pending queue in submission order", async () => {
    const response = await app.inject({
      method: "GET",
      url: "/reviews/pending?page=1&pageSize=2",
      headers: operatorHeaders,
    });

    expect(response.statusCode).toBe(200);
    const payload = response.json();
    expect(isSuccessResponse(payload)).toBe(true);
    expect(isPage(payload.data)).toBe(true);
    expect(payload.requestId).toBeTypeOf("string");
    expect(payload.data).toMatchObject({
      page: 1,
      pageSize: 2,
      total: 3,
    });
    expect(payload.data.items).toHaveLength(2);
    expect(payload.data.items[0].contentId).toBe("cnt_ceramic_001");
    expect(
      hasBusinessIdPrefix("contentId", payload.data.items[0].contentId),
    ).toBe(true);
    expect(isIsoUtcDateTime(payload.data.items[0].submittedAt)).toBe(true);
  });

  it("filters the queue by merchant and submission time", async () => {
    const response = await app.inject({
      method: "GET",
      url:
        "/reviews/pending?merchantId=mer_jiangnan_001" +
        "&submittedFrom=2026-07-30T00%3A00%3A00.000Z",
      headers: operatorHeaders,
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().data.items).toHaveLength(1);
    expect(response.json().data.items[0].merchantId).toBe(
      "mer_jiangnan_001",
    );
  });

  it("blocks non-operators from the review queue", async () => {
    const response = await app.inject({
      method: "GET",
      url: "/reviews/pending",
      headers: {
        "x-role": "MERCHANT",
        "x-user-id": "merchant_user",
        "x-merchant-id": "mer_jiangnan_001",
      },
    });

    expect(response.statusCode).toBe(403);
    expect(isErrorResponse(response.json())).toBe(true);
    expect(response.json().errorCode).toBe("FORBIDDEN");
  });

  it("returns preview data and append-only history for a content version", async () => {
    const response = await app.inject({
      method: "GET",
      url: "/reviews/cnt_bag_003",
      headers: operatorHeaders,
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().data).toMatchObject({
      contentId: "cnt_bag_003",
      contentVersion: 2,
      status: "PENDING_REVIEW",
    });
    expect(response.json().data.sellingPoints).toHaveLength(3);
    expect(response.json().data.reviewHistory[0]).toMatchObject({
      decision: "REJECTED",
      contentVersion: 1,
    });
  });
});

describe("review decisions", () => {
  it("approves a pending version and records the reviewer", async () => {
    const response = await app.inject({
      method: "POST",
      url: "/reviews/cnt_lamp_002/approve",
      headers: operatorHeaders,
      payload: {
        contentVersion: 1,
        comment: "素材和表述符合要求。",
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().data.content.status).toBe("APPROVED");
    expect(response.json().data.review).toMatchObject({
      decision: "APPROVED",
      reviewerId: "op_test_001",
      reviewerName: "测试运营",
      contentVersion: 1,
      previousStatus: "PENDING_REVIEW",
      nextStatus: "APPROVED",
    });
    expect(
      hasBusinessIdPrefix("reviewId", response.json().data.review.reviewId),
    ).toBe(true);
    expect(isIsoUtcDateTime(response.json().data.review.reviewedAt)).toBe(true);

    const storedReviews = await prisma.review.findMany({
      where: { contentId: "cnt_lamp_002" },
    });
    expect(storedReviews).toHaveLength(1);
  });

  it("requires a merchant-visible comment when rejecting", async () => {
    const response = await app.inject({
      method: "POST",
      url: "/reviews/cnt_lamp_002/reject",
      headers: operatorHeaders,
      payload: { contentVersion: 1, comment: "   " },
    });

    expect(response.statusCode).toBe(400);
    expect(response.json().errorCode).toBe("REJECTION_REASON_REQUIRED");
  });

  it("rejects a pending version with a structured reason", async () => {
    const response = await app.inject({
      method: "POST",
      url: "/reviews/cnt_lamp_002/reject",
      headers: operatorHeaders,
      payload: {
        contentVersion: 1,
        reasonCode: "MEDIA_QUALITY",
        comment: "第 8 秒画面模糊，请替换该片段。",
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().data.content.status).toBe("REJECTED");
    expect(response.json().data.review.reasonCode).toBe("MEDIA_QUALITY");
  });

  it("rejects a stale content version", async () => {
    const response = await app.inject({
      method: "POST",
      url: "/reviews/cnt_ceramic_001/approve",
      headers: operatorHeaders,
      payload: { contentVersion: 2 },
    });

    expect(response.statusCode).toBe(409);
    expect(response.json().errorCode).toBe("CONTENT_VERSION_CONFLICT");
  });

  it("does not allow the same version to be reviewed twice", async () => {
    const approved = await app.inject({
      method: "POST",
      url: "/reviews/cnt_lamp_002/approve",
      headers: operatorHeaders,
      payload: { contentVersion: 1 },
    });
    const rejected = await app.inject({
      method: "POST",
      url: "/reviews/cnt_lamp_002/reject",
      headers: operatorHeaders,
      payload: {
        contentVersion: 1,
        comment: "尝试覆盖先前结果。",
      },
    });

    expect(approved.statusCode).toBe(200);
    expect(rejected.statusCode).toBe(409);
    expect(rejected.json().errorCode).toBe("REVIEW_STATUS_CHANGED");
    expect(
      await prisma.review.count({ where: { contentId: "cnt_lamp_002" } }),
    ).toBe(1);
  });

  it("lets only one of two concurrent operators decide the same version", async () => {
    const [approval, rejection] = await Promise.all([
      app.inject({
        method: "POST",
        url: "/reviews/cnt_lamp_002/approve",
        headers: {
          ...operatorHeaders,
          "x-user-id": "op_concurrent_a",
        },
        payload: { contentVersion: 1 },
      }),
      app.inject({
        method: "POST",
        url: "/reviews/cnt_lamp_002/reject",
        headers: {
          ...operatorHeaders,
          "x-user-id": "op_concurrent_b",
        },
        payload: {
          contentVersion: 1,
          comment: "并发审核中的驳回决定。",
        },
      }),
    ]);

    expect([approval.statusCode, rejection.statusCode].sort()).toEqual([
      200, 409,
    ]);
    expect(
      await prisma.review.count({ where: { contentId: "cnt_lamp_002" } }),
    ).toBe(1);
  });
});

describe("review history visibility and publishing gate", () => {
  it("lets a merchant see its rejection reason", async () => {
    const response = await app.inject({
      method: "GET",
      url: "/contents/cnt_bag_003/review-history",
      headers: {
        "x-role": "MERCHANT",
        "x-user-id": "merchant_user",
        "x-merchant-id": "mer_linjiang_003",
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().data[0]).toMatchObject({
      decision: "REJECTED",
      reasonCode: "MISLEADING_CLAIM",
    });
    expect(response.json().data[0].comment).toContain("日常防泼水");
  });

  it("hides internal approval comments from merchants", async () => {
    const response = await app.inject({
      method: "GET",
      url: "/contents/cnt_approved_004/review-history",
      headers: {
        "x-role": "MERCHANT",
        "x-user-id": "merchant_user",
        "x-merchant-id": "mer_jiangnan_001",
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().data[0].decision).toBe("APPROVED");
    expect(response.json().data[0].comment).toBeNull();
  });

  it("blocks a merchant from another merchant's history", async () => {
    const response = await app.inject({
      method: "GET",
      url: "/contents/cnt_bag_003/review-history",
      headers: {
        "x-role": "MERCHANT",
        "x-user-id": "merchant_user",
        "x-merchant-id": "mer_jiangnan_001",
      },
    });

    expect(response.statusCode).toBe(403);
    expect(response.json().errorCode).toBe("FORBIDDEN");
  });

  it("allows only approved content through the publishing gate", async () => {
    await expect(
      requireApprovedContent(prisma, "cnt_approved_004"),
    ).resolves.toBeUndefined();

    await expect(
      requireApprovedContent(prisma, "cnt_ceramic_001"),
    ).rejects.toMatchObject({
      statusCode: 409,
      errorCode: "CONTENT_NOT_APPROVED",
    } satisfies Partial<AppError>);
  });
});
