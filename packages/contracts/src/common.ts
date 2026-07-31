export const CONTRACT_VERSION = "1.0.0" as const;

export type IsoDateTime = string;
export type MerchantId = string;
export type ProductId = string;
export type ContentId = string;
export type AccountId = string;
export type PublicationId = string;
export type InquiryId = string;
export type ReviewId = string;
export type GenerationRequestId = string;

export const BUSINESS_ID_PREFIXES = {
  merchantId: "mer_",
  productId: "prd_",
  contentId: "cnt_",
  accountId: "acc_",
  publicationId: "pub_",
  inquiryId: "inq_",
  reviewId: "rev_",
  generationRequestId: "gen_",
} as const;

export type BusinessIdKind = keyof typeof BUSINESS_ID_PREFIXES;

export function hasBusinessIdPrefix(
  kind: BusinessIdKind,
  value: string,
): boolean {
  const prefix = BUSINESS_ID_PREFIXES[kind];
  if (!value.startsWith(prefix)) return false;
  return /^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(value.slice(prefix.length));
}

export const ROLES = ["MERCHANT", "OPERATOR", "BUYER"] as const;
export type Role = (typeof ROLES)[number];

export const CHANNELS = ["DOUYIN", "XIAOHONGSHU"] as const;
export type Channel = (typeof CHANNELS)[number];

export const CONTENT_STATUSES = [
  "DRAFT",
  "GENERATED",
  "PENDING_REVIEW",
  "APPROVED",
  "REJECTED",
] as const;
export type ContentStatus = (typeof CONTENT_STATUSES)[number];

export const PUBLICATION_STATUSES = [
  "QUEUED",
  "PUBLISHING",
  "SUCCEEDED",
  "FAILED",
] as const;
export type PublicationStatus = (typeof PUBLICATION_STATUSES)[number];

export const INQUIRY_STATUSES = [
  "NEW",
  "CONTACTED",
  "QUOTED",
  "WON",
  "LOST",
] as const;
export type InquiryStatus = (typeof INQUIRY_STATUSES)[number];

export const CONTENT_STATUS_TRANSITIONS = {
  DRAFT: ["GENERATED"],
  GENERATED: ["PENDING_REVIEW"],
  PENDING_REVIEW: ["APPROVED", "REJECTED"],
  APPROVED: [],
  REJECTED: ["PENDING_REVIEW"],
} as const satisfies Record<ContentStatus, readonly ContentStatus[]>;

export const PUBLICATION_STATUS_TRANSITIONS = {
  QUEUED: ["PUBLISHING", "FAILED"],
  PUBLISHING: ["SUCCEEDED", "FAILED"],
  SUCCEEDED: [],
  FAILED: ["QUEUED"],
} as const satisfies Record<PublicationStatus, readonly PublicationStatus[]>;

export const INQUIRY_STATUS_TRANSITIONS = {
  NEW: ["CONTACTED", "LOST"],
  CONTACTED: ["QUOTED", "LOST"],
  QUOTED: ["WON", "LOST"],
  WON: [],
  LOST: [],
} as const satisfies Record<InquiryStatus, readonly InquiryStatus[]>;

export const ERROR_CODES = [
  "VALIDATION_ERROR",
  "UNAUTHENTICATED",
  "FORBIDDEN",
  "INTERNAL_ERROR",
  "IDEMPOTENCY_CONFLICT",
  "PRODUCT_VALIDATION_FAILED",
  "PRODUCT_NOT_FOUND",
  "PRODUCT_INACTIVE",
  "CONTENT_NOT_FOUND",
  "CONTENT_NOT_APPROVED",
  "CONTENT_VERSION_CONFLICT",
  "CONTENT_NOT_EDITABLE",
  "GENERATION_FAILED",
  "GENERATION_IN_PROGRESS",
  "REVIEW_STATUS_CHANGED",
  "REVIEW_CONFLICT",
  "REJECTION_REASON_REQUIRED",
  "ACCOUNT_NOT_AVAILABLE",
  "PUBLICATION_NOT_FOUND",
  "RATE_LIMITED",
  "EXTERNAL_TIMEOUT",
  "CONTENT_REJECTED_BY_CHANNEL",
  "CALLBACK_INVALID",
  "INQUIRY_NOT_FOUND",
  "INQUIRY_STATUS_INVALID",
  "SOURCE_MISMATCH",
  "DUPLICATE_INQUIRY",
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

export interface ActorContext {
  role: Role;
  userId: string;
  userName: string;
  merchantId: MerchantId | null;
}

export interface PaginationQuery {
  page?: number;
  pageSize?: number;
}

export interface Page<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

export interface SuccessResponse<T> {
  data: T;
  requestId: string;
}

export interface ErrorResponse {
  errorCode: ErrorCode;
  message: string;
  requestId: string;
  details?: Record<string, unknown>;
}

export interface IdempotentInput {
  idempotencyKey: string;
}

export interface SourceAttribution {
  merchantId: MerchantId;
  productId: ProductId;
  contentId: ContentId | null;
  publicationId: PublicationId | null;
  channel: Channel | null;
  accountId: AccountId | null;
  externalWorkId: string | null;
  referrer: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isIsoUtcDateTime(value: unknown): value is IsoDateTime {
  if (typeof value !== "string") {
    return false;
  }
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,3})?Z$/.exec(
      value,
    );
  if (!match) return false;

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return false;

  return (
    parsed.getUTCFullYear() === Number(match[1]) &&
    parsed.getUTCMonth() + 1 === Number(match[2]) &&
    parsed.getUTCDate() === Number(match[3]) &&
    parsed.getUTCHours() === Number(match[4]) &&
    parsed.getUTCMinutes() === Number(match[5]) &&
    parsed.getUTCSeconds() === Number(match[6])
  );
}

export function isSuccessResponse<T = unknown>(
  value: unknown,
): value is SuccessResponse<T> {
  return (
    isRecord(value) &&
    Object.prototype.hasOwnProperty.call(value, "data") &&
    typeof value.requestId === "string" &&
    value.requestId.length > 0
  );
}

export function isErrorResponse(value: unknown): value is ErrorResponse {
  return (
    isRecord(value) &&
    typeof value.errorCode === "string" &&
    ERROR_CODES.includes(value.errorCode as ErrorCode) &&
    typeof value.message === "string" &&
    typeof value.requestId === "string" &&
    value.requestId.length > 0 &&
    (value.details === undefined || isRecord(value.details))
  );
}

export function isPage(value: unknown): value is Page<unknown> {
  return (
    isRecord(value) &&
    Array.isArray(value.items) &&
    Number.isInteger(value.page) &&
    (value.page as number) >= 1 &&
    Number.isInteger(value.pageSize) &&
    (value.pageSize as number) >= 1 &&
    Number.isInteger(value.total) &&
    (value.total as number) >= 0
  );
}
