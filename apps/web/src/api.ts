import type {
  ApproveReviewInput,
  ErrorResponse,
  PendingReviewsPage,
  RejectReviewInput,
  ReviewContentDetail,
  ReviewDecisionResult,
  SuccessResponse,
} from "@wotao/contracts";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:3001";

const OPERATOR_HEADERS = {
  "x-role": "OPERATOR",
  "x-user-id": "op_chen_001",
  "x-user-name": encodeURIComponent("陈晨"),
};

export class ApiError extends Error {
  readonly errorCode: string;
  readonly requestId: string;

  constructor(error: ErrorResponse) {
    super(error.message);
    this.name = "ApiError";
    this.errorCode = error.errorCode;
    this.requestId = error.requestId;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  const headers = new Headers(OPERATOR_HEADERS);
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const requestInit: RequestInit = {
    ...init,
    headers,
  };
  if (signal) requestInit.signal = signal;

  const response = await fetch(`${API_URL}${path}`, requestInit);

  const payload = (await response.json()) as SuccessResponse<T> | ErrorResponse;

  if (!response.ok) {
    throw new ApiError(payload as ErrorResponse);
  }

  return (payload as SuccessResponse<T>).data;
}

export interface PendingFilters {
  page: number;
  pageSize: number;
  merchantId: string;
  submittedFrom: string;
  submittedTo: string;
}

export function getPendingReviews(
  filters: PendingFilters,
  signal?: AbortSignal,
): Promise<PendingReviewsPage> {
  const params = new URLSearchParams({
    page: String(filters.page),
    pageSize: String(filters.pageSize),
  });

  if (filters.merchantId) params.set("merchantId", filters.merchantId);
  if (filters.submittedFrom) {
    params.set("submittedFrom", new Date(filters.submittedFrom).toISOString());
  }
  if (filters.submittedTo) {
    params.set("submittedTo", new Date(filters.submittedTo).toISOString());
  }

  return request(`/reviews/pending?${params.toString()}`, {}, signal);
}

export function getReviewDetail(
  contentId: string,
  signal?: AbortSignal,
): Promise<ReviewContentDetail> {
  return request(`/reviews/${encodeURIComponent(contentId)}`, {}, signal);
}

export function approveReview(
  contentId: string,
  input: ApproveReviewInput,
): Promise<ReviewDecisionResult> {
  return request(`/reviews/${encodeURIComponent(contentId)}/approve`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function rejectReview(
  contentId: string,
  input: RejectReviewInput,
): Promise<ReviewDecisionResult> {
  return request(`/reviews/${encodeURIComponent(contentId)}/reject`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}
