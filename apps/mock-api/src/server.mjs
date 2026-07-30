import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import {
  CONTENT_TRANSITIONS,
  INQUIRY_TRANSITIONS,
  Role,
} from "../../../packages/contracts/src/runtime.mjs";
import { createSeedState } from "./data.mjs";

const ROLES = new Set(Object.values(Role));
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

class ApiError extends Error {
  constructor(status, errorCode, message, details = {}) {
    super(message);
    this.status = status;
    this.errorCode = errorCode;
    this.details = details;
  }
}

function send(res, status, payload) {
  res.writeHead(status, JSON_HEADERS);
  res.end(JSON.stringify(payload));
}

function success(res, requestId, data, status = 200) {
  send(res, status, { data, requestId });
}

function fail(res, requestId, error) {
  const status = error instanceof ApiError ? error.status : 500;
  const errorCode = error instanceof ApiError ? error.errorCode : "INTERNAL_ERROR";
  const message = error instanceof ApiError ? error.message : "服务内部错误";
  const details = error instanceof ApiError ? error.details : {};
  send(res, status, { errorCode, message, requestId, details });
}

async function readJson(req) {
  const declaredLength = Number(req.headers["content-length"] ?? 0);
  if (declaredLength > 1024 * 1024) {
    throw new ApiError(413, "PAYLOAD_TOO_LARGE", "请求体超过 1MB");
  }

  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 1024 * 1024) {
      throw new ApiError(413, "PAYLOAD_TOO_LARGE", "请求体超过 1MB");
    }
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ApiError(400, "INVALID_JSON", "请求体不是有效 JSON");
  }
}

function context(req) {
  const role = req.headers["x-role"];
  const merchantId = req.headers["x-merchant-id"];
  const actorId =
    req.headers["x-user-id"] ??
    req.headers["x-actor-id"] ??
    role?.toLowerCase() ??
    "anonymous";
  const rawActorName = req.headers["x-user-name"];
  let actorName = String(actorId);
  if (typeof rawActorName === "string") {
    try {
      actorName = decodeURIComponent(rawActorName);
    } catch {
      actorName = rawActorName;
    }
  }
  return { role, merchantId, actorId, actorName };
}

function requireRole(ctx, allowed) {
  if (!ROLES.has(ctx.role)) {
    throw new ApiError(401, "ROLE_REQUIRED", "缺少或无效的 x-role");
  }
  if (!allowed.includes(ctx.role)) {
    throw new ApiError(403, "FORBIDDEN", "无权执行此操作");
  }
}

function requireMerchant(ctx) {
  if (!ctx.merchantId) {
    throw new ApiError(400, "MERCHANT_CONTEXT_REQUIRED", "缺少 x-merchant-id");
  }
}

function requireOwned(resource, ctx) {
  requireMerchant(ctx);
  if (resource.merchantId !== ctx.merchantId) {
    throw new ApiError(403, "MERCHANT_DATA_FORBIDDEN", "不能访问其他商家的数据");
  }
}

function requireFields(body, fields) {
  const missing = fields.filter(
    (field) => body[field] === undefined || body[field] === null || body[field] === "",
  );
  if (missing.length > 0) {
    throw new ApiError(400, "VALIDATION_ERROR", "请求参数不完整", { missing });
  }
}

function getOr404(map, id, resourceName) {
  const value = map.get(id);
  if (!value) {
    throw new ApiError(404, "RESOURCE_NOT_FOUND", `${resourceName}不存在`, { id });
  }
  return value;
}

function now() {
  return new Date().toISOString();
}

function makeId(prefix) {
  return `${prefix}_${randomUUID().replaceAll("-", "")}`;
}

function pagination(url) {
  const page = Number(url.searchParams.get("page") ?? 1);
  const pageSize = Number(url.searchParams.get("pageSize") ?? 20);
  if (!Number.isInteger(page) || page < 1 || !Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
    throw new ApiError(400, "INVALID_PAGINATION", "page 或 pageSize 无效");
  }
  return { page, pageSize };
}

function pageItems(items, page, pageSize) {
  const start = (page - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page,
    pageSize,
    total: items.length,
  };
}

function audit(state, ctx, action, resourceType, resourceId, before, after) {
  state.auditLog.push({
    auditId: makeId("audit"),
    actorId: String(ctx.actorId),
    role: ctx.role,
    action,
    resourceType,
    resourceId,
    before,
    after,
    createdAt: now(),
  });
}

function reviewSummary(state, content) {
  const product = state.products.get(content.productId);
  return {
    contentId: content.contentId,
    merchantId: content.merchantId,
    merchantName:
      content.merchantId === "merchant_demo" ? "我淘淘演示商家" : "认证商家",
    productId: content.productId,
    productTitle: product?.name ?? "未知商品",
    title: content.caption,
    status: content.status,
    contentVersion: content.contentVersion ?? 1,
    submittedAt: content.submittedAt ?? content.updatedAt,
  };
}

function ensureTransition(transitions, current, next) {
  if (!(transitions[current] ?? []).includes(next)) {
    throw new ApiError(409, "INVALID_STATE_TRANSITION", "当前状态不允许执行此操作", {
      currentStatus: current,
      requestedStatus: next,
    });
  }
}

async function handle(req, res, state) {
  const requestId = `req_${randomUUID().replaceAll("-", "")}`;
  res.setHeader("x-request-id", requestId);

  try {
    const method = req.method ?? "GET";
    const url = new URL(req.url ?? "/", "http://mock.local");
    const ctx = context(req);
    let match;

    if (method === "POST" && url.pathname === "/products") {
      requireRole(ctx, [Role.MERCHANT]);
      requireMerchant(ctx);
      const body = await readJson(req);
      requireFields(body, ["name", "description", "imageUrls"]);
      if (!Array.isArray(body.imageUrls) || body.imageUrls.length === 0) {
        throw new ApiError(400, "VALIDATION_ERROR", "imageUrls 至少包含一项");
      }
      const timestamp = now();
      const product = {
        productId: makeId("product"),
        merchantId: ctx.merchantId,
        name: String(body.name),
        description: String(body.description),
        imageUrls: body.imageUrls.map(String),
        isPublic: false,
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      state.products.set(product.productId, product);
      return success(res, requestId, product, 201);
    }

    if (method === "GET" && (match = url.pathname.match(/^\/products\/([^/]+)$/))) {
      requireRole(ctx, [Role.MERCHANT, Role.OPERATOR, Role.BUYER]);
      const product = getOr404(state.products, decodeURIComponent(match[1]), "商品");
      if (ctx.role === Role.MERCHANT) requireOwned(product, ctx);
      if (ctx.role === Role.BUYER && !product.isPublic) {
        throw new ApiError(404, "RESOURCE_NOT_FOUND", "商品不存在");
      }
      return success(res, requestId, product);
    }

    if (method === "POST" && url.pathname === "/contents/generate") {
      requireRole(ctx, [Role.MERCHANT]);
      requireMerchant(ctx);
      const body = await readJson(req);
      requireFields(body, ["productId"]);
      const product = getOr404(state.products, body.productId, "商品");
      requireOwned(product, ctx);
      const timestamp = now();
      const content = {
        contentId: makeId("content"),
        merchantId: product.merchantId,
        productId: product.productId,
        caption: `${product.name}，让好产品被更多人看见。`,
        videoUrl: "https://example.test/content/generated-demo.mp4",
        status: "GENERATED",
        contentVersion: 1,
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      state.contents.set(content.contentId, content);
      return success(res, requestId, content, 201);
    }

    if (method === "PUT" && (match = url.pathname.match(/^\/contents\/([^/]+)$/))) {
      requireRole(ctx, [Role.MERCHANT]);
      const content = getOr404(state.contents, decodeURIComponent(match[1]), "内容");
      requireOwned(content, ctx);
      if (!["GENERATED", "REJECTED"].includes(content.status)) {
        throw new ApiError(409, "CONTENT_NOT_EDITABLE", "当前内容状态不可编辑", {
          currentStatus: content.status,
        });
      }
      const body = await readJson(req);
      if (body.caption === undefined && body.videoUrl === undefined) {
        throw new ApiError(400, "VALIDATION_ERROR", "caption 和 videoUrl 至少提供一项");
      }
      if (body.caption !== undefined) content.caption = String(body.caption);
      if (body.videoUrl !== undefined) content.videoUrl = String(body.videoUrl);
      content.contentVersion = (content.contentVersion ?? 1) + 1;
      content.updatedAt = now();
      content.updatedBy = String(ctx.actorId);
      return success(res, requestId, content);
    }

    if (
      method === "POST" &&
      (match = url.pathname.match(/^\/contents\/([^/]+)\/submit-review$/))
    ) {
      requireRole(ctx, [Role.MERCHANT]);
      const content = getOr404(state.contents, decodeURIComponent(match[1]), "内容");
      requireOwned(content, ctx);
      ensureTransition(CONTENT_TRANSITIONS, content.status, "PENDING_REVIEW");
      const before = content.status;
      content.status = "PENDING_REVIEW";
      content.updatedAt = now();
      content.submittedAt = content.updatedAt;
      content.updatedBy = String(ctx.actorId);
      audit(state, ctx, "SUBMIT_REVIEW", "CONTENT", content.contentId, before, content.status);
      return success(res, requestId, content);
    }

    if (method === "GET" && url.pathname === "/reviews/pending") {
      requireRole(ctx, [Role.OPERATOR]);
      const { page, pageSize } = pagination(url);
      const items = [...state.contents.values()].filter(
        (content) => content.status === "PENDING_REVIEW",
      ).map((content) => reviewSummary(state, content));
      return success(res, requestId, pageItems(items, page, pageSize));
    }

    if (
      method === "POST" &&
      (match = url.pathname.match(/^\/reviews\/([^/]+)\/(approve|reject)$/))
    ) {
      requireRole(ctx, [Role.OPERATOR]);
      const content = getOr404(state.contents, decodeURIComponent(match[1]), "内容");
      const action = match[2];
      const nextStatus = action === "approve" ? "APPROVED" : "REJECTED";
      ensureTransition(CONTENT_TRANSITIONS, content.status, nextStatus);
      const body = await readJson(req);
      if (!Number.isInteger(body.contentVersion) || body.contentVersion < 1) {
        throw new ApiError(400, "VALIDATION_ERROR", "contentVersion 必须是正整数", {
          field: "contentVersion",
        });
      }
      if (body.contentVersion !== (content.contentVersion ?? 1)) {
        throw new ApiError(409, "CONTENT_VERSION_CONFLICT", "内容版本已变化", {
          currentVersion: content.contentVersion ?? 1,
          requestedVersion: body.contentVersion,
        });
      }
      if (action === "reject") {
        requireFields(body, ["comment"]);
        const reasonCodes = [
          "MISLEADING_CLAIM",
          "INCOMPLETE_INFORMATION",
          "MEDIA_QUALITY",
          "PLATFORM_POLICY",
          "OTHER",
        ];
        if (body.reasonCode && !reasonCodes.includes(body.reasonCode)) {
          throw new ApiError(400, "VALIDATION_ERROR", "reasonCode 不受支持", {
            field: "reasonCode",
          });
        }
        content.rejectionReason = String(body.comment);
      } else {
        delete content.rejectionReason;
      }
      const before = content.status;
      content.status = nextStatus;
      content.updatedAt = now();
      content.updatedBy = String(ctx.actorId);
      const review = {
        reviewId: makeId("review"),
        contentId: content.contentId,
        decision: nextStatus,
        reasonCode: action === "reject" ? body.reasonCode ?? null : null,
        comment: body.comment ? String(body.comment) : null,
        reviewerId: String(ctx.actorId),
        reviewerName: String(ctx.actorName),
        reviewedAt: content.updatedAt,
        contentVersion: content.contentVersion ?? 1,
        previousStatus: before,
        nextStatus,
      };
      state.reviews.push(review);
      audit(state, ctx, action.toUpperCase(), "CONTENT", content.contentId, before, nextStatus);
      return success(res, requestId, {
        content: reviewSummary(state, content),
        review,
      });
    }

    if (method === "GET" && url.pathname === "/authorized-accounts") {
      requireRole(ctx, [Role.OPERATOR]);
      const channel = url.searchParams.get("channel");
      const accounts = [...state.accounts.values()].filter(
        (account) => !channel || account.channel === channel,
      );
      return success(res, requestId, accounts);
    }

    if (method === "POST" && url.pathname === "/publications") {
      requireRole(ctx, [Role.OPERATOR]);
      const idempotencyKey = req.headers["idempotency-key"];
      if (typeof idempotencyKey !== "string" || idempotencyKey.length < 8) {
        throw new ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "缺少有效的 idempotency-key");
      }
      const body = await readJson(req);
      requireFields(body, ["contentId", "accountId", "channel"]);
      const fingerprint = JSON.stringify({
        contentId: body.contentId,
        accountId: body.accountId,
        channel: body.channel,
        scenario: body.scenario ?? "PROCESSING",
      });
      const prior = state.idempotency.get(idempotencyKey);
      if (prior) {
        if (prior.fingerprint !== fingerprint) {
          throw new ApiError(409, "IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于不同请求");
        }
        return success(
          res,
          requestId,
          getOr404(state.publications, prior.publicationId, "发布记录"),
        );
      }

      const content = getOr404(state.contents, body.contentId, "内容");
      if (content.status !== "APPROVED") {
        throw new ApiError(409, "CONTENT_NOT_APPROVED", "内容尚未审核通过", {
          currentStatus: content.status,
        });
      }
      const account = getOr404(state.accounts, body.accountId, "授权账号");
      if (account.channel !== body.channel) {
        throw new ApiError(400, "ACCOUNT_CHANNEL_MISMATCH", "账号与渠道不匹配");
      }
      const scenario = body.scenario ?? "PROCESSING";
      if (!["SUCCESS", "PROCESSING", "FAILURE"].includes(scenario)) {
        throw new ApiError(400, "INVALID_MOCK_SCENARIO", "未知模拟发布场景");
      }
      const timestamp = now();
      const publication = {
        publicationId: makeId("publication"),
        merchantId: content.merchantId,
        productId: content.productId,
        contentId: content.contentId,
        accountId: account.accountId,
        channel: account.channel,
        status:
          scenario === "SUCCESS" ? "SUCCEEDED" : scenario === "FAILURE" ? "FAILED" : "PUBLISHING",
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      if (scenario === "SUCCESS") {
        publication.externalWorkId = makeId("work");
        publication.externalWorkUrl = `https://example.test/${account.channel.toLowerCase()}/work/${publication.externalWorkId}`;
        const product = state.products.get(content.productId);
        if (product) product.isPublic = true;
      }
      if (scenario === "FAILURE") publication.failureReason = "模拟发布失败";
      state.publications.set(publication.publicationId, publication);
      state.idempotency.set(idempotencyKey, {
        publicationId: publication.publicationId,
        fingerprint,
      });
      audit(state, ctx, "CREATE_PUBLICATION", "PUBLICATION", publication.publicationId, null, publication.status);
      return success(res, requestId, publication, 201);
    }

    if (method === "POST" && url.pathname === "/publications/callback") {
      if (req.headers["x-callback-signature"] !== "mock-valid-signature") {
        throw new ApiError(401, "INVALID_CALLBACK_SIGNATURE", "回调签名无效");
      }
      const body = await readJson(req);
      requireFields(body, ["callbackEventId", "publicationId", "status"]);
      const duplicateEvent = state.callbackEvents.get(body.callbackEventId);
      if (duplicateEvent) {
        return success(
          res,
          requestId,
          getOr404(state.publications, duplicateEvent.publicationId, "发布记录"),
        );
      }
      const publication = getOr404(state.publications, body.publicationId, "发布记录");
      if (publication.status !== "PUBLISHING") {
        throw new ApiError(409, "PUBLICATION_NOT_PROCESSING", "发布记录不在处理中", {
          currentStatus: publication.status,
        });
      }
      if (!["SUCCEEDED", "FAILED"].includes(body.status)) {
        throw new ApiError(400, "INVALID_CALLBACK_STATUS", "回调状态无效");
      }
      if (body.status === "SUCCEEDED") {
        requireFields(body, ["externalWorkId", "externalWorkUrl"]);
        publication.externalWorkId = String(body.externalWorkId);
        publication.externalWorkUrl = String(body.externalWorkUrl);
        delete publication.failureReason;
        const product = state.products.get(publication.productId);
        if (product) product.isPublic = true;
      } else {
        requireFields(body, ["failureReason"]);
        publication.failureReason = String(body.failureReason);
      }
      const before = publication.status;
      publication.status = body.status;
      publication.updatedAt = now();
      state.callbackEvents.set(body.callbackEventId, {
        callbackEventId: String(body.callbackEventId),
        publicationId: publication.publicationId,
        status: publication.status,
        receivedAt: now(),
      });
      audit(
        state,
        { role: "PUBLISHING_SERVICE", actorId: "callback" },
        "PUBLICATION_CALLBACK",
        "PUBLICATION",
        publication.publicationId,
        before,
        publication.status,
      );
      return success(res, requestId, publication);
    }

    if (
      method === "POST" &&
      (match = url.pathname.match(/^\/publications\/([^/]+)\/retry$/))
    ) {
      requireRole(ctx, [Role.OPERATOR]);
      const publication = getOr404(
        state.publications,
        decodeURIComponent(match[1]),
        "发布记录",
      );
      if (publication.status !== "FAILED") {
        throw new ApiError(409, "PUBLICATION_NOT_RETRYABLE", "只有失败发布可以重试", {
          currentStatus: publication.status,
        });
      }
      const before = publication.status;
      publication.status = "QUEUED";
      publication.updatedAt = now();
      delete publication.failureReason;
      audit(state, ctx, "RETRY_PUBLICATION", "PUBLICATION", publication.publicationId, before, "QUEUED");
      return success(res, requestId, publication);
    }

    if (method === "GET" && url.pathname === "/feed") {
      const { page, pageSize } = pagination(url);
      const items = [...state.publications.values()]
        .filter((publication) => publication.status === "SUCCEEDED")
        .map((publication) => {
          const product = state.products.get(publication.productId);
          const content = state.contents.get(publication.contentId);
          if (!product?.isPublic || !content || !publication.externalWorkUrl) return null;
          return {
            publicationId: publication.publicationId,
            productId: product.productId,
            contentId: content.contentId,
            merchantId: product.merchantId,
            channel: publication.channel,
            caption: content.caption,
            videoUrl: content.videoUrl,
            externalWorkUrl: publication.externalWorkUrl,
            productName: product.name,
          };
        })
        .filter(Boolean);
      return success(res, requestId, pageItems(items, page, pageSize));
    }

    if (
      method === "GET" &&
      (match = url.pathname.match(/^\/storefront\/products\/([^/]+)$/))
    ) {
      const product = getOr404(state.products, decodeURIComponent(match[1]), "商品");
      if (!product.isPublic) throw new ApiError(404, "RESOURCE_NOT_FOUND", "商品不存在");
      return success(res, requestId, {
        product,
        merchantName:
          product.merchantId === "merchant_demo" ? "我淘淘演示商家" : "认证商家",
      });
    }

    if (method === "POST" && url.pathname === "/inquiries") {
      requireRole(ctx, [Role.BUYER]);
      const body = await readJson(req);
      requireFields(body, ["publicationId", "buyerName", "contact", "message"]);
      const publication = getOr404(state.publications, body.publicationId, "发布记录");
      if (publication.status !== "SUCCEEDED") {
        throw new ApiError(400, "PUBLICATION_NOT_PUBLIC", "来源作品尚未公开");
      }
      const timestamp = now();
      const inquiry = {
        inquiryId: makeId("inquiry"),
        merchantId: publication.merchantId,
        productId: publication.productId,
        contentId: publication.contentId,
        publicationId: publication.publicationId,
        channel: publication.channel,
        accountId: publication.accountId,
        buyerName: String(body.buyerName),
        contact: String(body.contact),
        message: String(body.message),
        status: "NEW",
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      state.inquiries.set(inquiry.inquiryId, inquiry);
      return success(res, requestId, inquiry, 201);
    }

    if (method === "GET" && url.pathname === "/merchant/inquiries") {
      requireRole(ctx, [Role.MERCHANT, Role.OPERATOR]);
      requireMerchant(ctx);
      const { page, pageSize } = pagination(url);
      const items = [...state.inquiries.values()].filter(
        (inquiry) => inquiry.merchantId === ctx.merchantId,
      );
      return success(res, requestId, pageItems(items, page, pageSize));
    }

    if (
      method === "PATCH" &&
      (match = url.pathname.match(/^\/inquiries\/([^/]+)\/status$/))
    ) {
      requireRole(ctx, [Role.MERCHANT]);
      const inquiry = getOr404(state.inquiries, decodeURIComponent(match[1]), "询盘");
      requireOwned(inquiry, ctx);
      const body = await readJson(req);
      requireFields(body, ["status"]);
      ensureTransition(INQUIRY_TRANSITIONS, inquiry.status, body.status);
      const before = inquiry.status;
      inquiry.status = body.status;
      inquiry.updatedAt = now();
      inquiry.updatedBy = String(ctx.actorId);
      audit(state, ctx, "UPDATE_INQUIRY_STATUS", "INQUIRY", inquiry.inquiryId, before, inquiry.status);
      return success(res, requestId, inquiry);
    }

    throw new ApiError(404, "ROUTE_NOT_FOUND", "接口不存在", {
      method,
      path: url.pathname,
    });
  } catch (error) {
    fail(res, requestId, error);
  }
}

export function createMockServer(options = {}) {
  const state = options.state ?? createSeedState();
  const server = createServer((req, res) => handle(req, res, state));
  return { server, state };
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
}

if (isMainModule()) {
  const port = Number(process.env.PORT ?? 4010);
  const host = process.env.HOST ?? "127.0.0.1";
  const { server } = createMockServer();
  server.listen(port, host, () => {
    console.log(`我淘淘 MVP mock API: http://${host}:${port}`);
  });
}
