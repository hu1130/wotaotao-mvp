import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { pathToFileURL } from "node:url";
import {
  enumValues,
  idPrefix,
  matchOperation,
  transitionMap,
} from "./contract.mjs";
import { createSeedState } from "./data.mjs";

const ROLES = new Set(enumValues("Role"));
const ERROR_CODES = new Set(enumValues("ErrorCode"));
const CHANNELS = new Set(enumValues("Channel"));
const CONTENT_TRANSITIONS = transitionMap("ContentStatus");
const INQUIRY_TRANSITIONS = transitionMap("InquiryStatus");

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

class ApiError extends Error {
  constructor(status, errorCode, message, details) {
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
  const requestedCode =
    error instanceof ApiError ? error.errorCode : "INTERNAL_ERROR";
  const errorCode = ERROR_CODES.has(requestedCode)
    ? requestedCode
    : "INTERNAL_ERROR";
  const message =
    error instanceof ApiError ? error.message : "Internal server error";
  const payload = { errorCode, message, requestId };
  if (error instanceof ApiError && error.details !== undefined) {
    payload.details = error.details;
  }
  send(res, status, payload);
}

async function readJson(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 1024 * 1024) {
      throw new ApiError(413, "VALIDATION_ERROR", "Request body exceeds 1MB");
    }
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ApiError(400, "VALIDATION_ERROR", "Request body is not valid JSON");
  }
}

function actorContext(req) {
  const role = req.headers["x-role"];
  const userId = req.headers["x-user-id"];
  const merchantId = req.headers["x-merchant-id"] ?? null;
  const encodedName = req.headers["x-user-name"];
  let userName = typeof userId === "string" ? userId : "anonymous";
  if (typeof encodedName === "string") {
    try {
      userName = decodeURIComponent(encodedName);
    } catch {
      userName = encodedName;
    }
  }
  return { role, userId, userName, merchantId };
}

function authorize(operation, actor) {
  if (operation.auth === "PUBLIC") return;
  if (
    typeof actor.role !== "string" ||
    !ROLES.has(actor.role) ||
    typeof actor.userId !== "string" ||
    actor.userId.length === 0
  ) {
    throw new ApiError(
      401,
      "UNAUTHENTICATED",
      "A valid x-role and x-user-id are required",
    );
  }
  if (!operation.roles.includes(actor.role)) {
    throw new ApiError(403, "FORBIDDEN", "The actor cannot call this operation");
  }
}

function requireMerchant(actor) {
  if (typeof actor.merchantId !== "string" || actor.merchantId.length === 0) {
    throw new ApiError(403, "FORBIDDEN", "A merchant context is required");
  }
  return actor.merchantId;
}

function requireOwned(resource, actor) {
  const merchantId = requireMerchant(actor);
  if (resource.merchantId !== merchantId) {
    throw new ApiError(403, "FORBIDDEN", "Cross-merchant access is forbidden");
  }
}

function requireFields(body, fields) {
  const missing = fields.filter(
    (field) =>
      body[field] === undefined || body[field] === null || body[field] === "",
  );
  if (missing.length > 0) {
    throw new ApiError(400, "VALIDATION_ERROR", "Required fields are missing", {
      missing,
    });
  }
}

function getResource(map, id, errorCode, name) {
  const value = map.get(id);
  if (!value) {
    throw new ApiError(404, errorCode, `${name} not found`, { id });
  }
  return value;
}

function now() {
  return new Date().toISOString();
}

function makeId(schemaName) {
  return `${idPrefix(schemaName)}${randomUUID().replaceAll("-", "")}`;
}

function pagination(url) {
  const page = Number(url.searchParams.get("page") ?? 1);
  const pageSize = Number(url.searchParams.get("pageSize") ?? 20);
  if (
    !Number.isInteger(page) ||
    page < 1 ||
    !Number.isInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > 100
  ) {
    throw new ApiError(400, "VALIDATION_ERROR", "Invalid pagination");
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

function ensureTransition(transitions, current, next, errorCode) {
  if (!(transitions[current] ?? []).includes(next)) {
    throw new ApiError(409, errorCode, "Invalid state transition", {
      currentStatus: current,
      requestedStatus: next,
    });
  }
}

function assertVersion(content, value) {
  if (!Number.isInteger(value) || value < 1) {
    throw new ApiError(400, "VALIDATION_ERROR", "contentVersion must be positive");
  }
  if (value !== content.contentVersion) {
    throw new ApiError(409, "CONTENT_VERSION_CONFLICT", "Content version changed", {
      currentVersion: content.contentVersion,
      requestedVersion: value,
    });
  }
}

function reviewSummary(state, content) {
  const product = state.products.get(content.productId);
  const merchant = state.merchants.get(content.merchantId);
  return {
    contentId: content.contentId,
    merchantId: content.merchantId,
    merchantName: merchant?.name ?? "Unknown merchant",
    productId: content.productId,
    productTitle: product?.name ?? "Unknown product",
    title: content.title ?? "Untitled content",
    status: content.status,
    contentVersion: content.contentVersion,
    submittedAt: content.submittedAt ?? content.updatedAt,
  };
}

function reviewDetail(state, content) {
  const product = state.products.get(content.productId);
  return {
    ...reviewSummary(state, content),
    copy: content.copy ?? "",
    videoUrl: content.videoUrl ?? "",
    sellingPoints: product?.sellingPoints ?? [],
    targetAudience: content.targetAudience,
    reviewHistory: state.reviews.filter(
      (review) => review.contentId === content.contentId,
    ),
  };
}

function generationResult(content) {
  return {
    contentId: content.contentId,
    generationRequestId: content.generationRequestId,
    status: content.generationStatus,
    errorCode: content.generationErrorCode,
    errorMessage: null,
    updatedAt: content.updatedAt,
  };
}

function publicationScenario(req) {
  const value = req.headers["x-mock-publication-result"] ?? "PROCESSING";
  if (!["PROCESSING", "SUCCESS", "FAILURE"].includes(value)) {
    throw new ApiError(400, "VALIDATION_ERROR", "Invalid mock publication result");
  }
  return value;
}

async function handle(req, res, state) {
  const requestId = `req_${randomUUID().replaceAll("-", "")}`;
  res.setHeader("x-request-id", requestId);

  try {
    const method = req.method ?? "GET";
    const url = new URL(req.url ?? "/", "http://mock.local");
    const operation = matchOperation(method, url.pathname);
    if (!operation) {
      throw new ApiError(404, "VALIDATION_ERROR", "Route not found", {
        method,
        path: url.pathname,
      });
    }

    const actor = actorContext(req);
    authorize(operation, actor);

    switch (operation.operationId) {
      case "foundation.health":
        return success(res, requestId, { status: "ok" });

      case "product.create": {
        const merchantId = requireMerchant(actor);
        const body = await readJson(req);
        requireFields(body, ["name", "sellingPoints", "priceMode"]);
        if (!Array.isArray(body.sellingPoints)) {
          throw new ApiError(400, "PRODUCT_VALIDATION_FAILED", "sellingPoints must be an array");
        }
        if (!["FIXED", "INQUIRY"].includes(body.priceMode)) {
          throw new ApiError(400, "PRODUCT_VALIDATION_FAILED", "priceMode is invalid");
        }
        if (body.priceMode === "FIXED" && typeof body.price !== "number") {
          throw new ApiError(400, "PRODUCT_VALIDATION_FAILED", "FIXED price requires price");
        }
        const timestamp = now();
        const product = {
          productId: makeId("ProductId"),
          merchantId,
          name: String(body.name),
          summary: String(body.summary ?? ""),
          sellingPoints: body.sellingPoints.map(String),
          images: Array.isArray(body.images) ? body.images : [],
          parameters: Array.isArray(body.parameters) ? body.parameters : [],
          priceMode: body.priceMode,
          price: body.priceMode === "FIXED" ? body.price : null,
          status: "DRAFT",
          createdAt: timestamp,
          updatedAt: timestamp,
        };
        state.products.set(product.productId, product);
        return success(res, requestId, product, 201);
      }

      case "product.list": {
        const merchantId = requireMerchant(actor);
        const { page, pageSize } = pagination(url);
        const status = url.searchParams.get("status");
        const items = [...state.products.values()]
          .filter((item) => item.merchantId === merchantId)
          .filter((item) => !status || item.status === status)
          .map((item) => ({
            productId: item.productId,
            merchantId: item.merchantId,
            name: item.name,
            primaryImageUrl: item.images[0]?.url ?? null,
            sellingPoints: item.sellingPoints,
            priceMode: item.priceMode,
            price: item.price,
            status: item.status,
            updatedAt: item.updatedAt,
          }));
        return success(res, requestId, pageItems(items, page, pageSize));
      }

      case "product.get": {
        const product = getResource(
          state.products,
          operation.params.productId,
          "PRODUCT_NOT_FOUND",
          "Product",
        );
        if (actor.role === "MERCHANT") requireOwned(product, actor);
        return success(res, requestId, product);
      }

      case "product.update": {
        const product = getResource(
          state.products,
          operation.params.productId,
          "PRODUCT_NOT_FOUND",
          "Product",
        );
        requireOwned(product, actor);
        const body = await readJson(req);
        for (const field of [
          "name",
          "summary",
          "sellingPoints",
          "images",
          "parameters",
          "priceMode",
          "price",
        ]) {
          if (body[field] !== undefined) product[field] = body[field];
        }
        product.updatedAt = now();
        return success(res, requestId, product);
      }

      case "product.activate":
      case "product.deactivate": {
        const product = getResource(
          state.products,
          operation.params.productId,
          "PRODUCT_NOT_FOUND",
          "Product",
        );
        requireOwned(product, actor);
        product.status =
          operation.operationId === "product.activate" ? "ACTIVE" : "INACTIVE";
        product.updatedAt = now();
        return success(res, requestId, product);
      }

      case "product.uploadImage":
        return success(
          res,
          requestId,
          {
            url: "https://example.test/uploads/product-image.jpg",
            contentType: "image/jpeg",
            size: 1024,
          },
          201,
        );

      case "content.generate": {
        const body = await readJson(req);
        requireFields(body, [
          "productId",
          "targetAudience",
          "sellingPoints",
          "style",
          "duration",
        ]);
        const product = getResource(
          state.products,
          body.productId,
          "PRODUCT_NOT_FOUND",
          "Product",
        );
        requireOwned(product, actor);
        if (product.status !== "ACTIVE") {
          throw new ApiError(409, "PRODUCT_INACTIVE", "Product is not active");
        }
        const timestamp = now();
        const content = {
          contentId: makeId("ContentId"),
          merchantId: product.merchantId,
          productId: product.productId,
          title: `${product.name} demo`,
          copy: product.summary,
          videoUrl: "https://example.test/content/generated.mp4",
          targetAudience: String(body.targetAudience),
          style: String(body.style),
          duration: Number(body.duration),
          status: "GENERATED",
          generationRequestId: makeId("GenerationRequestId"),
          generationStatus: "SUCCEEDED",
          generationErrorCode: null,
          contentVersion: 1,
          submittedAt: null,
          createdAt: timestamp,
          updatedAt: timestamp,
        };
        state.contents.set(content.contentId, content);
        return success(res, requestId, generationResult(content), 201);
      }

      case "content.get": {
        const content = getResource(
          state.contents,
          operation.params.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        if (actor.role === "MERCHANT") requireOwned(content, actor);
        return success(res, requestId, content);
      }

      case "content.generationStatus": {
        const content = getResource(
          state.contents,
          operation.params.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        requireOwned(content, actor);
        return success(res, requestId, generationResult(content));
      }

      case "content.update": {
        const content = getResource(
          state.contents,
          operation.params.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        requireOwned(content, actor);
        if (!["GENERATED", "REJECTED"].includes(content.status)) {
          throw new ApiError(409, "CONTENT_NOT_EDITABLE", "Content is not editable");
        }
        const body = await readJson(req);
        assertVersion(content, body.contentVersion);
        for (const field of [
          "title",
          "copy",
          "videoUrl",
          "targetAudience",
          "style",
          "duration",
        ]) {
          if (body[field] !== undefined) content[field] = body[field];
        }
        content.contentVersion += 1;
        content.updatedAt = now();
        return success(res, requestId, content);
      }

      case "content.regenerate": {
        const content = getResource(
          state.contents,
          operation.params.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        requireOwned(content, actor);
        const body = await readJson(req);
        assertVersion(content, body.contentVersion);
        if (!["GENERATED", "REJECTED"].includes(content.status)) {
          throw new ApiError(409, "CONTENT_NOT_EDITABLE", "Content is not editable");
        }
        content.generationRequestId = makeId("GenerationRequestId");
        content.generationStatus = "SUCCEEDED";
        content.generationErrorCode = null;
        content.contentVersion += 1;
        content.updatedAt = now();
        return success(res, requestId, generationResult(content));
      }

      case "content.submitReview": {
        const content = getResource(
          state.contents,
          operation.params.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        requireOwned(content, actor);
        const body = await readJson(req);
        assertVersion(content, body.contentVersion);
        ensureTransition(
          CONTENT_TRANSITIONS,
          content.status,
          "PENDING_REVIEW",
          "CONTENT_NOT_EDITABLE",
        );
        content.status = "PENDING_REVIEW";
        content.submittedAt = now();
        content.updatedAt = content.submittedAt;
        return success(res, requestId, content);
      }

      case "review.pending": {
        const { page, pageSize } = pagination(url);
        const merchantId = url.searchParams.get("merchantId");
        const from = url.searchParams.get("submittedFrom");
        const to = url.searchParams.get("submittedTo");
        const items = [...state.contents.values()]
          .filter((item) => item.status === "PENDING_REVIEW")
          .filter((item) => !merchantId || item.merchantId === merchantId)
          .filter((item) => !from || item.submittedAt >= from)
          .filter((item) => !to || item.submittedAt <= to)
          .map((item) => reviewSummary(state, item));
        return success(res, requestId, pageItems(items, page, pageSize));
      }

      case "review.get": {
        const content = getResource(
          state.contents,
          operation.params.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        return success(res, requestId, reviewDetail(state, content));
      }

      case "review.approve":
      case "review.reject": {
        const content = getResource(
          state.contents,
          operation.params.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        if (content.status !== "PENDING_REVIEW") {
          throw new ApiError(409, "REVIEW_STATUS_CHANGED", "Content is no longer pending");
        }
        const body = await readJson(req);
        assertVersion(content, body.contentVersion);
        const rejected = operation.operationId === "review.reject";
        if (rejected && (!body.comment || String(body.comment).trim().length === 0)) {
          throw new ApiError(
            400,
            "REJECTION_REASON_REQUIRED",
            "A rejection comment is required",
          );
        }
        const previousStatus = content.status;
        const nextStatus = rejected ? "REJECTED" : "APPROVED";
        content.status = nextStatus;
        content.updatedAt = now();
        const review = {
          reviewId: makeId("ReviewId"),
          contentId: content.contentId,
          decision: nextStatus,
          reasonCode: rejected ? body.reasonCode ?? null : null,
          comment: body.comment ? String(body.comment) : null,
          reviewerId: actor.userId,
          reviewerName: actor.userName,
          reviewedAt: content.updatedAt,
          contentVersion: content.contentVersion,
          previousStatus,
          nextStatus,
        };
        state.reviews.push(review);
        return success(res, requestId, {
          content: reviewSummary(state, content),
          review,
        });
      }

      case "review.history": {
        const content = getResource(
          state.contents,
          operation.params.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        if (actor.role === "MERCHANT") requireOwned(content, actor);
        const reviews = state.reviews
          .filter((item) => item.contentId === content.contentId)
          .map((item) =>
            actor.role === "MERCHANT" && item.decision === "APPROVED"
              ? { ...item, comment: null }
              : item,
          );
        return success(res, requestId, reviews);
      }

      case "publishing.accounts": {
        const channel = url.searchParams.get("channel");
        if (!channel || !CHANNELS.has(channel)) {
          throw new ApiError(400, "VALIDATION_ERROR", "channel is required");
        }
        return success(
          res,
          requestId,
          [...state.accounts.values()].filter((item) => item.channel === channel),
        );
      }

      case "publishing.create": {
        const body = await readJson(req);
        requireFields(body, ["contentId", "accountId", "channel", "idempotencyKey"]);
        const fingerprint = JSON.stringify({
          contentId: body.contentId,
          accountId: body.accountId,
          channel: body.channel,
        });
        const prior = state.idempotency.get(body.idempotencyKey);
        if (prior) {
          if (prior.fingerprint !== fingerprint) {
            throw new ApiError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key conflict");
          }
          return success(
            res,
            requestId,
            getResource(
              state.publications,
              prior.publicationId,
              "PUBLICATION_NOT_FOUND",
              "Publication",
            ),
          );
        }
        const content = getResource(
          state.contents,
          body.contentId,
          "CONTENT_NOT_FOUND",
          "Content",
        );
        if (content.status !== "APPROVED") {
          throw new ApiError(409, "CONTENT_NOT_APPROVED", "Content is not approved");
        }
        const account = state.accounts.get(body.accountId);
        if (!account || !account.available || account.channel !== body.channel) {
          throw new ApiError(400, "ACCOUNT_NOT_AVAILABLE", "Account is unavailable");
        }
        const scenario = publicationScenario(req);
        const timestamp = now();
        const publicationId = makeId("PublicationId");
        const publication = {
          publicationId,
          merchantId: content.merchantId,
          contentId: content.contentId,
          productId: content.productId,
          channel: account.channel,
          accountId: account.accountId,
          idempotencyKey: String(body.idempotencyKey),
          status:
            scenario === "SUCCESS"
              ? "SUCCEEDED"
              : scenario === "FAILURE"
                ? "FAILED"
                : "PUBLISHING",
          externalTaskId: `task_${publicationId}`,
          externalWorkId:
            scenario === "SUCCESS" ? `work_${publicationId}` : null,
          externalUrl:
            scenario === "SUCCESS"
              ? `https://example.test/${account.channel.toLowerCase()}/${publicationId}`
              : null,
          errorCode: scenario === "FAILURE" ? "RATE_LIMITED" : null,
          errorMessage: scenario === "FAILURE" ? "Mock channel failure" : null,
          requestedBy: actor.userId,
          publishedAt: scenario === "SUCCESS" ? timestamp : null,
          createdAt: timestamp,
          updatedAt: timestamp,
        };
        state.publications.set(publicationId, publication);
        state.idempotency.set(body.idempotencyKey, { publicationId, fingerprint });
        return success(res, requestId, publication, 201);
      }

      case "publishing.get": {
        const publication = getResource(
          state.publications,
          operation.params.publicationId,
          "PUBLICATION_NOT_FOUND",
          "Publication",
        );
        if (actor.role === "MERCHANT") requireOwned(publication, actor);
        return success(res, requestId, publication);
      }

      case "publishing.list": {
        const { page, pageSize } = pagination(url);
        const status = url.searchParams.get("status");
        const channel = url.searchParams.get("channel");
        let items = [...state.publications.values()];
        if (actor.role === "MERCHANT") {
          const merchantId = requireMerchant(actor);
          items = items.filter((item) => item.merchantId === merchantId);
        }
        items = items
          .filter((item) => !status || item.status === status)
          .filter((item) => !channel || item.channel === channel);
        return success(res, requestId, pageItems(items, page, pageSize));
      }

      case "publishing.retry": {
        const publication = getResource(
          state.publications,
          operation.params.publicationId,
          "PUBLICATION_NOT_FOUND",
          "Publication",
        );
        const body = await readJson(req);
        requireFields(body, ["idempotencyKey"]);
        if (publication.status !== "FAILED") {
          throw new ApiError(409, "VALIDATION_ERROR", "Publication is not retryable");
        }
        publication.status = "QUEUED";
        publication.idempotencyKey = String(body.idempotencyKey);
        publication.errorCode = null;
        publication.errorMessage = null;
        publication.updatedAt = now();
        return success(res, requestId, publication);
      }

      case "publishing.callback": {
        if (req.headers["x-callback-signature"] !== "mock-valid-signature") {
          throw new ApiError(401, "CALLBACK_INVALID", "Callback signature is invalid");
        }
        const body = await readJson(req);
        requireFields(body, ["eventId", "externalTaskId", "status"]);
        if (state.callbackEvents.has(body.eventId)) {
          return success(res, requestId, { accepted: true, duplicate: true });
        }
        const publication = [...state.publications.values()].find(
          (item) => item.externalTaskId === body.externalTaskId,
        );
        if (!publication) {
          throw new ApiError(404, "PUBLICATION_NOT_FOUND", "Publication not found");
        }
        if (!["SUCCEEDED", "FAILED"].includes(body.status)) {
          throw new ApiError(400, "CALLBACK_INVALID", "Callback status is invalid");
        }
        publication.status = body.status;
        publication.externalWorkId = body.externalWorkId ?? null;
        publication.externalUrl = body.externalUrl ?? null;
        publication.errorCode = body.errorCode ?? null;
        publication.errorMessage = body.errorMessage ?? null;
        publication.publishedAt = body.status === "SUCCEEDED" ? body.occurredAt ?? now() : null;
        publication.updatedAt = now();
        state.callbackEvents.set(body.eventId, publication.publicationId);
        return success(res, requestId, { accepted: true, duplicate: false });
      }

      case "storefront.feed": {
        const { page, pageSize } = pagination(url);
        const items = [...state.publications.values()]
          .filter((item) => item.status === "SUCCEEDED")
          .map((publication) => {
            const product = state.products.get(publication.productId);
            const content = state.contents.get(publication.contentId);
            const merchant = state.merchants.get(publication.merchantId);
            if (!product || product.status !== "ACTIVE" || !content) return null;
            return {
              publicationId: publication.publicationId,
              contentId: publication.contentId,
              productId: publication.productId,
              merchantId: publication.merchantId,
              channel: publication.channel,
              externalWorkId: publication.externalWorkId,
              externalUrl: publication.externalUrl,
              videoUrl: content.videoUrl,
              title: content.title,
              productName: product.name,
              merchantName: merchant?.name ?? "Unknown merchant",
              sellingPoints: product.sellingPoints,
              publishedAt: publication.publishedAt,
            };
          })
          .filter(Boolean);
        return success(res, requestId, pageItems(items, page, pageSize));
      }

      case "storefront.product": {
        const product = getResource(
          state.products,
          operation.params.productId,
          "PRODUCT_NOT_FOUND",
          "Product",
        );
        const publicationId = url.searchParams.get("publicationId");
        const publication = publicationId
          ? getResource(
              state.publications,
              publicationId,
              "PUBLICATION_NOT_FOUND",
              "Publication",
            )
          : null;
        if (publication && publication.productId !== product.productId) {
          throw new ApiError(400, "SOURCE_MISMATCH", "Publication source mismatch");
        }
        const merchant = state.merchants.get(product.merchantId);
        return success(res, requestId, {
          productId: product.productId,
          merchantId: product.merchantId,
          merchantName: merchant?.name ?? "Unknown merchant",
          name: product.name,
          summary: product.summary,
          sellingPoints: product.sellingPoints,
          images: product.images,
          parameters: product.parameters,
          priceMode: product.priceMode,
          price: product.price,
          available: product.status === "ACTIVE",
          attribution: {
            merchantId: product.merchantId,
            productId: product.productId,
            contentId: publication?.contentId ?? null,
            publicationId: publication?.publicationId ?? null,
            channel: publication?.channel ?? null,
            externalWorkId: publication?.externalWorkId ?? null,
            referrer: null,
          },
        });
      }

      case "storefront.merchant": {
        const merchant = state.merchants.get(operation.params.merchantId);
        if (!merchant) {
          throw new ApiError(404, "VALIDATION_ERROR", "Merchant not found");
        }
        return success(res, requestId, merchant);
      }

      case "storefront.publication": {
        const publication = getResource(
          state.publications,
          operation.params.publicationId,
          "PUBLICATION_NOT_FOUND",
          "Publication",
        );
        if (publication.status !== "SUCCEEDED") {
          throw new ApiError(404, "PUBLICATION_NOT_FOUND", "Publication not found");
        }
        return success(res, requestId, {
          publicationId: publication.publicationId,
          merchantId: publication.merchantId,
          productId: publication.productId,
          contentId: publication.contentId,
          channel: publication.channel,
          externalWorkId: publication.externalWorkId,
          externalUrl: publication.externalUrl,
          publishedAt: publication.publishedAt,
        });
      }

      case "inquiry.create": {
        const body = await readJson(req);
        requireFields(body, ["productId", "buyerName", "contact", "message"]);
        const product = getResource(
          state.products,
          body.productId,
          "PRODUCT_NOT_FOUND",
          "Product",
        );
        let publication = null;
        if (body.publicationId) {
          publication = getResource(
            state.publications,
            body.publicationId,
            "PUBLICATION_NOT_FOUND",
            "Publication",
          );
          if (publication.productId !== product.productId) {
            throw new ApiError(400, "SOURCE_MISMATCH", "Publication source mismatch");
          }
        }
        const timestamp = now();
        const inquiry = {
          inquiryId: makeId("InquiryId"),
          merchantId: product.merchantId,
          productId: product.productId,
          buyerName: String(body.buyerName),
          contact: String(body.contact),
          quantity: body.quantity ? String(body.quantity) : null,
          message: String(body.message),
          status: "NEW",
          attribution: {
            merchantId: product.merchantId,
            productId: product.productId,
            contentId: publication?.contentId ?? null,
            publicationId: publication?.publicationId ?? null,
            channel: publication?.channel ?? null,
            accountId: publication?.accountId ?? null,
            externalWorkId: publication?.externalWorkId ?? null,
            referrer: body.referrer ? String(body.referrer) : null,
          },
          createdAt: timestamp,
          updatedAt: timestamp,
        };
        state.inquiries.set(inquiry.inquiryId, inquiry);
        state.inquiryHistory.set(inquiry.inquiryId, []);
        return success(
          res,
          requestId,
          { inquiryId: inquiry.inquiryId, status: "NEW", createdAt: timestamp },
          201,
        );
      }

      case "inquiry.list": {
        const merchantId = requireMerchant(actor);
        const { page, pageSize } = pagination(url);
        const status = url.searchParams.get("status");
        const items = [...state.inquiries.values()]
          .filter((item) => item.merchantId === merchantId)
          .filter((item) => !status || item.status === status);
        return success(res, requestId, pageItems(items, page, pageSize));
      }

      case "inquiry.get": {
        const inquiry = getResource(
          state.inquiries,
          operation.params.inquiryId,
          "INQUIRY_NOT_FOUND",
          "Inquiry",
        );
        requireOwned(inquiry, actor);
        return success(res, requestId, {
          ...inquiry,
          statusHistory: state.inquiryHistory.get(inquiry.inquiryId) ?? [],
        });
      }

      case "inquiry.updateStatus": {
        const inquiry = getResource(
          state.inquiries,
          operation.params.inquiryId,
          "INQUIRY_NOT_FOUND",
          "Inquiry",
        );
        if (actor.role === "MERCHANT") requireOwned(inquiry, actor);
        const body = await readJson(req);
        requireFields(body, ["status"]);
        ensureTransition(
          INQUIRY_TRANSITIONS,
          inquiry.status,
          body.status,
          "INQUIRY_STATUS_INVALID",
        );
        const previousStatus = inquiry.status;
        inquiry.status = body.status;
        inquiry.updatedAt = now();
        const history = state.inquiryHistory.get(inquiry.inquiryId) ?? [];
        history.push({
          fromStatus: previousStatus,
          toStatus: inquiry.status,
          changedBy: actor.userId,
          changedAt: inquiry.updatedAt,
          comment: body.comment ? String(body.comment) : null,
        });
        state.inquiryHistory.set(inquiry.inquiryId, history);
        return success(res, requestId, { ...inquiry, statusHistory: history });
      }

      default:
        throw new ApiError(500, "INTERNAL_ERROR", "Mock operation is not implemented", {
          operationId: operation.operationId,
        });
    }
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
    console.log(`Wotao MVP mock API: http://${host}:${port}`);
  });
}
