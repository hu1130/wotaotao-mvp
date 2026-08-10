import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { once } from "node:events";
import { mockOperations, openApi } from "../src/contract.mjs";
import { createMockServer } from "../src/server.mjs";

let server;
let state;
let baseUrl;

const merchantHeaders = {
  "x-role": "MERCHANT",
  "x-user-id": "merchant_user_001",
  "x-merchant-id": "mer_demo_001",
};
const operatorHeaders = {
  "x-role": "OPERATOR",
  "x-user-id": "op_demo_001",
};

before(async () => {
  ({ server, state } = createMockServer());
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  baseUrl = `http://127.0.0.1:${address.port}`;
});

after(async () => {
  server.close();
  await once(server, "close");
});

async function request(path, options = {}) {
  const headers = {
    ...(options.body ? { "content-type": "application/json" } : {}),
    ...(options.headers ?? {}),
  };
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  return { response, json: await response.json() };
}

test("mock routes are loaded from the generated OpenAPI document", () => {
  const openApiCount = Object.values(openApi.paths).reduce(
    (total, pathItem) => total + Object.keys(pathItem).length,
    0,
  );
  assert.equal(mockOperations.length, openApiCount);
  assert.equal(
    new Set(mockOperations.map((operation) => operation.operationId)).size,
    mockOperations.length,
  );
  assert.ok(
    mockOperations.some(
      (operation) =>
        operation.method === "GET" &&
        operation.path === "/products/{productId}",
    ),
  );
});

test("success and error responses use the common envelopes", async () => {
  const ok = await request("/health");
  assert.equal(ok.response.status, 200);
  assert.deepEqual(ok.json.data, { status: "ok" });
  assert.equal(ok.response.headers.get("x-request-id"), ok.json.requestId);

  const error = await request("/not-found");
  assert.equal(error.response.status, 404);
  assert.equal(error.json.errorCode, "VALIDATION_ERROR");
  assert.equal(typeof error.json.requestId, "string");
  assert.deepEqual(error.json.details, {
    method: "GET",
    path: "/not-found",
  });
});

test("actor auth and merchant isolation match the integration contract", async () => {
  const unauthenticated = await request("/products/prd_demo_001", {
    headers: { "x-role": "MERCHANT", "x-merchant-id": "mer_demo_001" },
  });
  assert.equal(unauthenticated.response.status, 401);
  assert.equal(unauthenticated.json.errorCode, "UNAUTHENTICATED");

  const forbidden = await request("/products/prd_other_001", {
    headers: merchantHeaders,
  });
  assert.equal(forbidden.response.status, 403);
  assert.equal(forbidden.json.errorCode, "FORBIDDEN");
});

test("authorized account fields use the shared channel and field names", async () => {
  const result = await request("/authorized-accounts?channel=DOUYIN", {
    headers: operatorHeaders,
  });
  assert.equal(result.response.status, 200);
  assert.equal(result.json.data.length, 1);
  assert.deepEqual(Object.keys(result.json.data[0]).sort(), [
    "accountId",
    "available",
    "channel",
    "displayLabel",
  ]);
  assert.match(result.json.data[0].accountId, /^acc_/);
});

test("review decisions use contentId, version and shared response types", async () => {
  const approved = await request("/reviews/cnt_demo_pending/approve", {
    method: "POST",
    headers: operatorHeaders,
    body: { contentVersion: 1, comment: "Approved in mock review" },
  });
  assert.equal(approved.response.status, 200);
  assert.equal(approved.json.data.content.status, "APPROVED");
  assert.match(approved.json.data.review.reviewId, /^rev_/);
  assert.equal(approved.json.data.review.reviewerId, "op_demo_001");

  const repeated = await request("/reviews/cnt_demo_pending/reject", {
    method: "POST",
    headers: operatorHeaders,
    body: { contentVersion: 1, comment: "Cannot overwrite" },
  });
  assert.equal(repeated.response.status, 409);
  assert.equal(repeated.json.errorCode, "REVIEW_STATUS_CHANGED");
});

test("publication idempotency is carried in the shared request body", async () => {
  const options = {
    method: "POST",
    headers: {
      ...operatorHeaders,
      "x-mock-publication-result": "SUCCESS",
    },
    body: {
      contentId: "cnt_demo_approved",
      accountId: "acc_douyin_001",
      channel: "DOUYIN",
      idempotencyKey: "publication-test-001",
    },
  };
  const first = await request("/publications", options);
  const duplicate = await request("/publications", options);
  assert.equal(first.response.status, 201);
  assert.equal(duplicate.response.status, 200);
  assert.equal(first.json.data.publicationId, duplicate.json.data.publicationId);
  assert.match(first.json.data.publicationId, /^pub_/);
  assert.equal(first.json.data.externalUrl.includes("example.test"), true);
  assert.equal("externalWorkUrl" in first.json.data, false);
  assert.equal("failureReason" in first.json.data, false);

  const conflict = await request("/publications", {
    ...options,
    body: { ...options.body, accountId: "acc_xhs_001", channel: "XIAOHONGSHU" },
  });
  assert.equal(conflict.response.status, 409);
  assert.equal(conflict.json.errorCode, "IDEMPOTENCY_CONFLICT");
});

test("provider callback returns the shared acknowledgement structure", async () => {
  const callback = await request("/publications/callback", {
    method: "POST",
    headers: { "x-callback-signature": "mock-valid-signature" },
    body: {
      eventId: "event_demo_001",
      externalTaskId: "task_demo_processing",
      status: "SUCCEEDED",
      externalWorkId: "work_callback_001",
      externalUrl: "https://example.test/xhs/work/callback-001",
      occurredAt: "2026-07-30T05:00:00Z",
    },
  });
  const duplicate = await request("/publications/callback", {
    method: "POST",
    headers: { "x-callback-signature": "mock-valid-signature" },
    body: {
      eventId: "event_demo_001",
      externalTaskId: "task_demo_processing",
      status: "SUCCEEDED",
    },
  });
  assert.deepEqual(callback.json.data, { accepted: true, duplicate: false });
  assert.deepEqual(duplicate.json.data, { accepted: true, duplicate: true });
});

test("storefront and inquiry preserve server-derived attribution", async () => {
  const feed = await request("/feed?page=1&pageSize=10");
  assert.equal(feed.response.status, 200);
  assert.ok(feed.json.data.items.length >= 1);
  assert.match(feed.json.data.items[0].productId, /^prd_/);

  const storefront = await request(
    "/storefront/products/prd_demo_001?publicationId=pub_demo_success",
  );
  assert.equal(storefront.response.status, 200);
  assert.equal(storefront.json.data.productId, "prd_demo_001");
  assert.equal(storefront.json.data.attribution.publicationId, "pub_demo_success");
  assert.equal("product" in storefront.json.data, false);

  const created = await request("/inquiries", {
    method: "POST",
    body: {
      productId: "prd_demo_001",
      publicationId: "pub_demo_success",
      buyerName: "Integration buyer",
      contact: "buyer@example.test",
      quantity: "200 units",
      message: "Please quote",
      referrer: "https://example.test/feed",
    },
  });
  assert.equal(created.response.status, 201);
  assert.deepEqual(Object.keys(created.json.data).sort(), [
    "createdAt",
    "inquiryId",
    "status",
  ]);
  assert.match(created.json.data.inquiryId, /^inq_/);

  const detail = await request(
    `/merchant/inquiries/${created.json.data.inquiryId}`,
    { headers: merchantHeaders },
  );
  assert.equal(detail.response.status, 200);
  assert.deepEqual(detail.json.data.attribution, {
    merchantId: "mer_demo_001",
    productId: "prd_demo_001",
    contentId: "cnt_demo_approved",
    publicationId: "pub_demo_success",
    channel: "DOUYIN",
    accountId: "acc_douyin_001",
    externalWorkId: "work_demo_success",
    referrer: "https://example.test/feed",
  });
});

test("inquiry status transition returns detail and append-only history", async () => {
  const updated = await request("/inquiries/inq_demo_001/status", {
    method: "PATCH",
    headers: merchantHeaders,
    body: { status: "CONTACTED", comment: "Called buyer" },
  });
  assert.equal(updated.response.status, 200);
  assert.equal(updated.json.data.status, "CONTACTED");
  assert.deepEqual(updated.json.data.statusHistory[0], {
    fromStatus: "NEW",
    toStatus: "CONTACTED",
    changedBy: "merchant_user_001",
    changedAt: updated.json.data.updatedAt,
    comment: "Called buyer",
  });

  assert.ok(
    state.inquiryHistory.get("inq_demo_001").some(
      (item) => item.toStatus === "CONTACTED",
    ),
  );
});
