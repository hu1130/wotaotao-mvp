import type { ContentStatus, ReviewDecision } from "@wotao/contracts";

const STATUS_LABELS: Record<ContentStatus, string> = {
  DRAFT: "草稿",
  GENERATED: "已生成",
  PENDING_REVIEW: "待审核",
  APPROVED: "已通过",
  REJECTED: "已驳回",
};

export function StatusBadge({
  status,
}: {
  status: ContentStatus | ReviewDecision;
}) {
  const tone =
    status === "APPROVED"
      ? "approved"
      : status === "REJECTED"
        ? "rejected"
        : "pending";

  return (
    <span className={`status-badge status-badge--${tone}`}>
      <span aria-hidden="true" className="status-badge__dot" />
      {STATUS_LABELS[status]}
    </span>
  );
}

