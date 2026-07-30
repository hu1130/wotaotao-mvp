import type { Content, Review } from "@prisma/client";
import type {
  ContentStatus,
  ReviewContentDetail,
  ReviewContentSummary,
  ReviewDecision,
  ReviewRecord,
} from "@wotao/contracts";

function parseSellingPoints(value: string): string[] {
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

export function mapContentSummary(content: Content): ReviewContentSummary {
  return {
    contentId: content.contentId,
    merchantId: content.merchantId,
    merchantName: content.merchantName,
    productId: content.productId,
    productTitle: content.productTitle,
    title: content.title,
    status: content.status as ContentStatus,
    contentVersion: content.version,
    submittedAt: content.submittedAt.toISOString(),
  };
}

export function mapReview(review: Review): ReviewRecord {
  return {
    reviewId: review.reviewId,
    contentId: review.contentId,
    decision: review.decision as ReviewDecision,
    reasonCode: review.reasonCode,
    comment: review.comment,
    reviewerId: review.reviewerId,
    reviewerName: review.reviewerName,
    reviewedAt: review.reviewedAt.toISOString(),
    contentVersion: review.contentVersion,
    previousStatus: review.previousStatus as ContentStatus,
    nextStatus: review.nextStatus as ContentStatus,
  };
}

export function mapContentDetail(
  content: Content,
  reviews: Review[],
): ReviewContentDetail {
  return {
    ...mapContentSummary(content),
    copy: content.copy,
    videoUrl: content.videoUrl,
    sellingPoints: parseSellingPoints(content.sellingPointsJson),
    targetAudience: content.targetAudience,
    reviewHistory: reviews.map(mapReview),
  };
}

