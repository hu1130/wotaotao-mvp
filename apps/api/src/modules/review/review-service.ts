import { randomUUID } from "node:crypto";
import { Prisma, type PrismaClient } from "@prisma/client";
import type {
  PendingReviewsPage,
  ReviewContentDetail,
  ReviewDecision,
  ReviewDecisionResult,
  ReviewRecord,
} from "@wotao/contracts";
import type { Actor } from "../../domain/auth.js";
import { AppError } from "../../domain/app-error.js";
import {
  mapContentDetail,
  mapContentSummary,
  mapReview,
} from "./review-mappers.js";

export interface PendingFilter {
  page: number;
  pageSize: number;
  merchantId?: string;
  submittedFrom?: Date;
  submittedTo?: Date;
}

export interface DecisionInput {
  contentVersion: number;
  comment: string | null;
  reasonCode: string | null;
}

export async function listPendingReviews(
  prisma: PrismaClient,
  filter: PendingFilter,
): Promise<PendingReviewsPage> {
  const where: Prisma.ContentWhereInput = { status: "PENDING_REVIEW" };

  if (filter.merchantId) {
    where.merchantId = filter.merchantId;
  }

  if (filter.submittedFrom || filter.submittedTo) {
    where.submittedAt = {};
    if (filter.submittedFrom) where.submittedAt.gte = filter.submittedFrom;
    if (filter.submittedTo) where.submittedAt.lte = filter.submittedTo;
  }

  const [contents, total] = await prisma.$transaction([
    prisma.content.findMany({
      where,
      orderBy: [{ submittedAt: "desc" }, { contentId: "asc" }],
      skip: (filter.page - 1) * filter.pageSize,
      take: filter.pageSize,
    }),
    prisma.content.count({ where }),
  ]);

  return {
    items: contents.map(mapContentSummary),
    page: filter.page,
    pageSize: filter.pageSize,
    total,
  };
}

export async function getReviewDetail(
  prisma: PrismaClient,
  contentId: string,
): Promise<ReviewContentDetail> {
  const content = await prisma.content.findUnique({
    where: { contentId },
    include: { reviews: { orderBy: { reviewedAt: "desc" } } },
  });

  if (!content) {
    throw new AppError(404, "CONTENT_NOT_FOUND", "未找到指定内容。");
  }

  return mapContentDetail(content, content.reviews);
}

export async function decideReview(
  prisma: PrismaClient,
  contentId: string,
  decision: ReviewDecision,
  input: DecisionInput,
  actor: Actor,
): Promise<ReviewDecisionResult> {
  try {
    return await prisma.$transaction(async (tx) => {
      const content = await tx.content.findUnique({ where: { contentId } });
      if (!content) {
        throw new AppError(404, "CONTENT_NOT_FOUND", "未找到指定内容。");
      }

      if (content.version !== input.contentVersion) {
        throw new AppError(
          409,
          "CONTENT_VERSION_CONFLICT",
          "内容版本已变化，请刷新后重新审核。",
          {
            expectedVersion: input.contentVersion,
            currentVersion: content.version,
          },
        );
      }

      if (content.status !== "PENDING_REVIEW") {
        throw new AppError(
          409,
          "REVIEW_STATUS_CHANGED",
          "内容审核状态已变化，请刷新后查看最新结果。",
          { currentStatus: content.status },
        );
      }

      const updated = await tx.content.updateMany({
        where: {
          contentId,
          version: input.contentVersion,
          status: "PENDING_REVIEW",
        },
        data: { status: decision },
      });

      if (updated.count !== 1) {
        throw new AppError(
          409,
          "REVIEW_CONFLICT",
          "该版本已被其他运营人员处理，请刷新页面。",
        );
      }

      const review = await tx.review.create({
        data: {
          reviewId: `rev_${randomUUID()}`,
          contentId,
          decision,
          reasonCode: input.reasonCode,
          comment: input.comment,
          reviewerId: actor.userId,
          reviewerName: actor.userName,
          contentVersion: input.contentVersion,
          previousStatus: "PENDING_REVIEW",
          nextStatus: decision,
        },
      });

      const decidedContent = await tx.content.findUniqueOrThrow({
        where: { contentId },
      });

      return {
        content: mapContentSummary(decidedContent),
        review: mapReview(review),
      };
    });
  } catch (error) {
    if (
      error instanceof Prisma.PrismaClientKnownRequestError &&
      error.code === "P2002"
    ) {
      throw new AppError(
        409,
        "REVIEW_CONFLICT",
        "该版本已被其他运营人员处理，请刷新页面。",
      );
    }
    throw error;
  }
}

export async function getReviewHistory(
  prisma: PrismaClient,
  contentId: string,
  actor: Actor,
): Promise<ReviewRecord[]> {
  const content = await prisma.content.findUnique({
    where: { contentId },
    include: { reviews: { orderBy: { reviewedAt: "desc" } } },
  });

  if (!content) {
    throw new AppError(404, "CONTENT_NOT_FOUND", "未找到指定内容。");
  }

  if (actor.role === "BUYER") {
    throw new AppError(403, "FORBIDDEN", "买家无权查看内部审核记录。");
  }

  if (
    actor.role === "MERCHANT" &&
    (!actor.merchantId || actor.merchantId !== content.merchantId)
  ) {
    throw new AppError(403, "FORBIDDEN", "无权查看其他商家的审核记录。");
  }

  return content.reviews.map((review) => {
    const mapped = mapReview(review);
    if (actor.role === "MERCHANT" && mapped.decision === "APPROVED") {
      return { ...mapped, comment: null };
    }
    return mapped;
  });
}

export async function requireApprovedContent(
  prisma: PrismaClient,
  contentId: string,
): Promise<void> {
  const content = await prisma.content.findUnique({
    where: { contentId },
    select: { status: true },
  });

  if (!content) {
    throw new AppError(404, "CONTENT_NOT_FOUND", "未找到指定内容。");
  }

  if (content.status !== "APPROVED") {
    throw new AppError(
      409,
      "CONTENT_NOT_APPROVED",
      "内容尚未审核通过，不能进入发布流程。",
      { currentStatus: content.status },
    );
  }
}

