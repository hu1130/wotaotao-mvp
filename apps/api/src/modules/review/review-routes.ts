import type { FastifyInstance } from "fastify";
import type { PrismaClient } from "@prisma/client";
import {
  REJECTION_REASONS,
  type ApproveReviewInput,
  type RejectReviewInput,
} from "@wotao/contracts";
import { AppError } from "../../domain/app-error.js";
import { getActor, requireOperator } from "../../domain/auth.js";
import {
  decideReview,
  getReviewDetail,
  getReviewHistory,
  listPendingReviews,
  type PendingFilter,
} from "./review-service.js";

interface ReviewParams {
  contentId: string;
}

interface PendingQueryRaw {
  page?: string;
  pageSize?: string;
  merchantId?: string;
  submittedFrom?: string;
  submittedTo?: string;
}

function parsePositiveInteger(
  value: string | undefined,
  fallback: number,
  field: string,
  maximum: number,
): number {
  if (value === undefined) return fallback;
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1 || number > maximum) {
    throw new AppError(400, "VALIDATION_ERROR", `${field} 参数无效。`, {
      field,
    });
  }
  return number;
}

function parseDate(value: string | undefined, field: string): Date | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new AppError(400, "VALIDATION_ERROR", `${field} 必须是有效时间。`, {
      field,
    });
  }
  return date;
}

function parsePendingFilter(query: PendingQueryRaw): PendingFilter {
  const filter: PendingFilter = {
    page: parsePositiveInteger(query.page, 1, "page", 100_000),
    pageSize: parsePositiveInteger(query.pageSize, 20, "pageSize", 100),
  };

  const merchantId = query.merchantId?.trim();
  const submittedFrom = parseDate(query.submittedFrom, "submittedFrom");
  const submittedTo = parseDate(query.submittedTo, "submittedTo");

  if (merchantId) filter.merchantId = merchantId;
  if (submittedFrom) filter.submittedFrom = submittedFrom;
  if (submittedTo) filter.submittedTo = submittedTo;

  if (
    filter.submittedFrom &&
    filter.submittedTo &&
    filter.submittedFrom > filter.submittedTo
  ) {
    throw new AppError(
      400,
      "VALIDATION_ERROR",
      "开始时间不能晚于结束时间。",
      { field: "submittedFrom" },
    );
  }

  return filter;
}

function parseVersion(value: unknown): number {
  if (!Number.isInteger(value) || (value as number) < 1) {
    throw new AppError(
      400,
      "VALIDATION_ERROR",
      "contentVersion 必须是正整数。",
      { field: "contentVersion" },
    );
  }
  return value as number;
}

function parseOptionalComment(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") {
    throw new AppError(400, "VALIDATION_ERROR", "comment 必须是字符串。", {
      field: "comment",
    });
  }
  const comment = value.trim();
  if (comment.length > 1_000) {
    throw new AppError(400, "VALIDATION_ERROR", "comment 不能超过 1000 字。", {
      field: "comment",
    });
  }
  return comment || null;
}

export async function registerReviewRoutes(
  app: FastifyInstance,
  prisma: PrismaClient,
): Promise<void> {
  app.get<{ Querystring: PendingQueryRaw }>(
    "/reviews/pending",
    async (request) => {
      requireOperator(request);
      const data = await listPendingReviews(
        prisma,
        parsePendingFilter(request.query),
      );
      return { data, requestId: request.id };
    },
  );

  app.get<{ Params: ReviewParams }>(
    "/reviews/:contentId",
    async (request) => {
      requireOperator(request);
      const data = await getReviewDetail(prisma, request.params.contentId);
      return { data, requestId: request.id };
    },
  );

  app.post<{ Params: ReviewParams; Body: ApproveReviewInput }>(
    "/reviews/:contentId/approve",
    async (request) => {
      const actor = requireOperator(request);
      const body = request.body ?? ({} as ApproveReviewInput);
      const data = await decideReview(
        prisma,
        request.params.contentId,
        "APPROVED",
        {
          contentVersion: parseVersion(body.contentVersion),
          comment: parseOptionalComment(body.comment),
          reasonCode: null,
        },
        actor,
      );
      return { data, requestId: request.id };
    },
  );

  app.post<{ Params: ReviewParams; Body: RejectReviewInput }>(
    "/reviews/:contentId/reject",
    async (request) => {
      const actor = requireOperator(request);
      const body = request.body ?? ({} as RejectReviewInput);
      const comment = parseOptionalComment(body.comment);

      if (!comment) {
        throw new AppError(
          400,
          "REJECTION_REASON_REQUIRED",
          "驳回时必须填写商家可见的原因。",
          { field: "comment" },
        );
      }

      const reasonCode = body.reasonCode?.trim() || null;
      if (
        reasonCode &&
        !REJECTION_REASONS.some((reason) => reason.code === reasonCode)
      ) {
        throw new AppError(
          400,
          "VALIDATION_ERROR",
          "reasonCode 不是支持的驳回原因。",
          { field: "reasonCode" },
        );
      }

      const data = await decideReview(
        prisma,
        request.params.contentId,
        "REJECTED",
        {
          contentVersion: parseVersion(body.contentVersion),
          comment,
          reasonCode,
        },
        actor,
      );
      return { data, requestId: request.id };
    },
  );

  app.get<{ Params: ReviewParams }>(
    "/contents/:contentId/review-history",
    async (request) => {
      const actor = getActor(request);
      const data = await getReviewHistory(
        prisma,
        request.params.contentId,
        actor,
      );
      return { data, requestId: request.id };
    },
  );
}

