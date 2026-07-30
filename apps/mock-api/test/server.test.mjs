import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { once } from "node:events";
import { createMockServer } from "../src/server.mjs";

let server;
let state;
let baseUrl;

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
  const json = await response.json();
  return { response, json };
}

test("成功和失败响应都带 requestId", async () => {
  const ok = await request("/feed");
  assert.equal(ok.response.status, 200);
  assert.equal(typeof ok.json.requestId, "string");
  assert.equal(ok.response.headers.get("x-request-id"), ok.json.requestId);

  const error = await request("/not-found");
  assert.equal(error.response.status, 404);
  assert.equal(error.json.errorCode, "ROUTE_NOT_FOUND");
  assert.equal(typeof error.json.requestId, "string");
  assert.deepEqual(error.json.details, { method: "GET", path: "/not-found" });
});

test("商家不能读取其他商家的商品", async () => {
  const result = await request("/products/product_other_001", {
    headers: {
      "x-role": "MERCHANT",
      "x-merchant-id": "merchant_demo",
    },
  });
  assert.equal(result.response.status, 403);
  assert.equal(result.json.errorCode, "MERCHANT_DATA_FORBIDDEN");
});

test("授权账号仅运营可见且不返回秘密字段", async () => {
  const forbidden = await request("/authorized-accounts", {
    headers: { "x-role": "MERCHANT", "x-merchant-id": "merchant_demo" },
  });
  assert.equal(forbidden.response.status, 403);

  const allowed = await request("/authorized-accounts", {
    headers: { "x-role": "OPERATOR" },
  });
  assert.equal(allowed.response.status, 200);
  assert.ok(allowed.json.data.length >= 2);
  const serialized = JSON.stringify(allowed.json.data).toLowerCase();
  assert.equal(serialized.includes("token"), false);
  assert.equal(serialized.includes("cookie"), false);
  assert.equal(serialized.includes("password"), false);
});

test("审核必须由运营执行并按状态流转", async () => {
  const merchantAttempt = await request("/reviews/content_demo_pending/approve", {
    method: "POST",
    headers: { "x-role": "MERCHANT", "x-merchant-id": "merchant_demo" },
    body: { contentVersion: 1 },
  });
  assert.equal(merchantAttempt.response.status, 403);

  const approved = await request("/reviews/content_demo_pending/approve", {
    method: "POST",
    headers: { "x-role": "OPERATOR", "x-actor-id": "operator_demo" },
    body: { contentVersion: 1 },
  });
  assert.equal(approved.response.status, 200);
  assert.equal(approved.json.data.content.status, "APPROVED");
  assert.equal(approved.json.data.review.reviewerId, "operator_demo");
  assert.ok(
    state.auditLog.some(
      (entry) =>
        entry.resourceId === "content_demo_pending" && entry.action === "APPROVE",
    ),
  );

  const repeated = await request("/reviews/content_demo_pending/approve", {
    method: "POST",
    headers: { "x-role": "OPERATOR" },
    body: { contentVersion: 1 },
  });
  assert.equal(repeated.response.status, 409);
  assert.equal(repeated.json.errorCode, "INVALID_STATE_TRANSITION");
});

test("未审核内容不能创建发布任务", async () => {
  const result = await request("/publications", {
    method: "POST",
    headers: {
      "x-role": "OPERATOR",
      "idempotency-key": "test-not-approved-001",
    },
    body: {
      contentId: "content_demo_generated",
      accountId: "account_douyin_demo",
      channel: "DOUYIN",
      scenario: "SUCCESS",
    },
  });
  assert.equal(result.response.status, 409);
  assert.equal(result.json.errorCode, "CONTENT_NOT_APPROVED");
});

test("发布幂等键阻止重复发布并检测载荷冲突", async () => {
  const options = {
    method: "POST",
    headers: {
      "x-role": "OPERATOR",
      "idempotency-key": "test-idempotency-001",
    },
    body: {
      contentId: "content_demo_approved",
      accountId: "account_douyin_demo",
      channel: "DOUYIN",
      scenario: "SUCCESS",
    },
  };
  const first = await request("/publications", options);
  const second = await request("/publications", options);
  assert.equal(first.response.status, 201);
  assert.equal(second.response.status, 200);
  assert.equal(first.json.data.publicationId, second.json.data.publicationId);

  const conflict = await request("/publications", {
    ...options,
    body: { ...options.body, scenario: "FAILURE" },
  });
  assert.equal(conflict.response.status, 409);
  assert.equal(conflict.json.errorCode, "IDEMPOTENCY_KEY_CONFLICT");
});

test("发布模拟覆盖处理中、回调成功、重复回调、失败和重试", async () => {
  const processing = await request("/publications", {
    method: "POST",
    headers: {
      "x-role": "OPERATOR",
      "idempotency-key": "test-processing-001",
    },
    body: {
      contentId: "content_demo_approved",
      accountId: "account_xhs_demo",
      channel: "XIAOHONGSHU",
      scenario: "PROCESSING",
    },
  });
  assert.equal(processing.json.data.status, "PUBLISHING");

  const invalidSignature = await request("/publications/callback", {
    method: "POST",
    headers: { "x-callback-signature": "invalid" },
    body: {
      callbackEventId: "callback_test_001",
      publicationId: processing.json.data.publicationId,
      status: "SUCCEEDED",
      externalWorkId: "xhs_work_test_001",
      externalWorkUrl: "https://example.test/xhs/work/test-001",
    },
  });
  assert.equal(invalidSignature.response.status, 401);

  const callbackOptions = {
    method: "POST",
    headers: { "x-callback-signature": "mock-valid-signature" },
    body: {
      callbackEventId: "callback_test_001",
      publicationId: processing.json.data.publicationId,
      status: "SUCCEEDED",
      externalWorkId: "xhs_work_test_001",
      externalWorkUrl: "https://example.test/xhs/work/test-001",
    },
  };
  const callback = await request("/publications/callback", callbackOptions);
  const duplicate = await request("/publications/callback", callbackOptions);
  assert.equal(callback.response.status, 200);
  assert.equal(callback.json.data.status, "SUCCEEDED");
  assert.equal(duplicate.json.data.publicationId, callback.json.data.publicationId);

  const failed = await request("/publications", {
    method: "POST",
    headers: {
      "x-role": "OPERATOR",
      "idempotency-key": "test-failure-001",
    },
    body: {
      contentId: "content_demo_approved",
      accountId: "account_xhs_demo",
      channel: "XIAOHONGSHU",
      scenario: "FAILURE",
    },
  });
  assert.equal(failed.json.data.status, "FAILED");

  const retried = await request(`/publications/${failed.json.data.publicationId}/retry`, {
    method: "POST",
    headers: { "x-role": "OPERATOR", "x-actor-id": "operator_demo" },
  });
  assert.equal(retried.response.status, 200);
  assert.equal(retried.json.data.status, "QUEUED");
});

test("公开浏览和询盘保存完整来源链路", async () => {
  const feed = await request("/feed?page=1&pageSize=10");
  assert.equal(feed.response.status, 200);
  assert.ok(feed.json.data.items.length >= 1);

  const storefront = await request("/storefront/products/product_demo_001");
  assert.equal(storefront.response.status, 200);
  assert.equal(storefront.json.data.product.merchantId, "merchant_demo");

  const created = await request("/inquiries", {
    method: "POST",
    headers: { "x-role": "BUYER" },
    body: {
      publicationId: "publication_demo_success",
      buyerName: "测试采购商",
      contact: "buyer@example.test",
      message: "需要批量报价",
    },
  });
  assert.equal(created.response.status, 201);
  assert.deepEqual(
    {
      merchantId: created.json.data.merchantId,
      productId: created.json.data.productId,
      contentId: created.json.data.contentId,
      publicationId: created.json.data.publicationId,
      channel: created.json.data.channel,
      accountId: created.json.data.accountId,
    },
    {
      merchantId: "merchant_demo",
      productId: "product_demo_001",
      contentId: "content_demo_approved",
      publicationId: "publication_demo_success",
      channel: "DOUYIN",
      accountId: "account_douyin_demo",
    },
  );
});

test("询盘列表按商家隔离且状态机由后端校验", async () => {
  const otherMerchant = await request("/merchant/inquiries", {
    headers: {
      "x-role": "MERCHANT",
      "x-merchant-id": "merchant_other",
    },
  });
  assert.equal(otherMerchant.response.status, 200);
  assert.equal(otherMerchant.json.data.total, 0);

  const updated = await request("/inquiries/inquiry_demo_001/status", {
    method: "PATCH",
    headers: {
      "x-role": "MERCHANT",
      "x-merchant-id": "merchant_demo",
      "x-actor-id": "merchant_user_demo",
    },
    body: { status: "CONTACTED" },
  });
  assert.equal(updated.response.status, 200);
  assert.equal(updated.json.data.status, "CONTACTED");

  const invalid = await request("/inquiries/inquiry_demo_001/status", {
    method: "PATCH",
    headers: {
      "x-role": "MERCHANT",
      "x-merchant-id": "merchant_demo",
    },
    body: { status: "WON" },
  });
  assert.equal(invalid.response.status, 409);
  assert.equal(invalid.json.errorCode, "INVALID_STATE_TRANSITION");
});
