import {
  REJECTION_REASONS,
  type ReviewContentDetail,
  type ReviewRecord,
} from "@wotao/contracts";
import type { DecisionMode } from "./DecisionDialog";
import { StatusBadge } from "./StatusBadge";

interface ReviewDetailProps {
  detail: ReviewContentDetail | null;
  loading: boolean;
  error: string | null;
  hasSelection: boolean;
  onRetry: () => void;
  onDecide: (mode: DecisionMode) => void;
}

function formatFullTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

function reasonLabel(record: ReviewRecord): string | null {
  if (!record.reasonCode) return null;
  return (
    REJECTION_REASONS.find((reason) => reason.code === record.reasonCode)?.label ??
    record.reasonCode
  );
}

function DetailSkeleton() {
  return (
    <div className="detail-skeleton" aria-label="正在加载审核详情">
      <div className="detail-skeleton__hero" />
      <div className="detail-skeleton__line" />
      <div className="detail-skeleton__line detail-skeleton__line--short" />
      <div className="detail-skeleton__media" />
    </div>
  );
}

export function ReviewDetail({
  detail,
  loading,
  error,
  hasSelection,
  onRetry,
  onDecide,
}: ReviewDetailProps) {
  if (!hasSelection) {
    return (
      <main className="detail-empty">
        <div className="detail-empty__seal" aria-hidden="true">
          审
        </div>
        <p className="eyebrow">Content inspection desk</p>
        <h2>从左侧选择一条内容开始审核</h2>
        <p>确认内容版本、视频素材与商品信息后，再记录通过或驳回决定。</p>
      </main>
    );
  }

  if (loading) {
    return (
      <main className="detail-panel">
        <DetailSkeleton />
      </main>
    );
  }

  if (error || !detail) {
    return (
      <main className="detail-panel detail-panel--state">
        <div className="state-panel state-panel--error">
          <strong>审核详情加载失败</strong>
          <p>{error ?? "没有可展示的内容。"}</p>
          <button type="button" className="text-button" onClick={onRetry}>
            重新加载
          </button>
        </div>
      </main>
    );
  }

  const canDecide = detail.status === "PENDING_REVIEW";

  return (
    <main className="detail-panel">
      <article className="review-sheet">
        <header className="review-sheet__header">
          <div className="version-rail" aria-label={`当前内容版本 ${detail.contentVersion}`}>
            <span>CONTENT</span>
            <strong>V{detail.contentVersion}</strong>
            <i />
            <small>{detail.contentId}</small>
          </div>
          <div className="review-sheet__title">
            <div className="review-sheet__topline">
              <StatusBadge status={detail.status} />
              <time dateTime={detail.submittedAt}>
                提交于 {formatFullTime(detail.submittedAt)}
              </time>
            </div>
            <h2>{detail.title}</h2>
            <p>
              {detail.merchantName}
              <span aria-hidden="true"> · </span>
              {detail.productTitle}
            </p>
          </div>
        </header>

        <section className="review-grid">
          <div className="media-proof">
            <div className="section-heading">
              <span>01</span>
              <div>
                <p className="eyebrow">Media proof</p>
                <h3>视频预览</h3>
              </div>
            </div>
            <div className="video-frame">
              <video controls preload="metadata" src={detail.videoUrl}>
                当前浏览器不支持视频播放。
              </video>
              <span className="video-frame__corner video-frame__corner--tl" />
              <span className="video-frame__corner video-frame__corner--br" />
            </div>
          </div>

          <div className="copy-proof">
            <div className="section-heading">
              <span>02</span>
              <div>
                <p className="eyebrow">Copy deck</p>
                <h3>发布文案</h3>
              </div>
            </div>
            <blockquote>{detail.copy}</blockquote>
          </div>
        </section>

        <section className="product-proof">
          <div className="section-heading">
            <span>03</span>
            <div>
              <p className="eyebrow">Product evidence</p>
              <h3>商品依据</h3>
            </div>
          </div>
          <div className="product-proof__content">
            <div>
              <h4>核心卖点</h4>
              <ul>
                {detail.sellingPoints.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </div>
            <div>
              <h4>目标客户</h4>
              <p>{detail.targetAudience}</p>
              <dl>
                <div>
                  <dt>商品 ID</dt>
                  <dd>{detail.productId}</dd>
                </div>
                <div>
                  <dt>商家 ID</dt>
                  <dd>{detail.merchantId}</dd>
                </div>
              </dl>
            </div>
          </div>
        </section>

        <section className="history-section">
          <div className="section-heading">
            <span>04</span>
            <div>
              <p className="eyebrow">Decision trail</p>
              <h3>审核记录</h3>
            </div>
          </div>

          {detail.reviewHistory.length === 0 ? (
            <p className="history-empty">这是该内容的首次审核，尚无历史记录。</p>
          ) : (
            <ol className="history-timeline">
              {detail.reviewHistory.map((record) => (
                <li key={record.reviewId}>
                  <span
                    className={`history-timeline__node history-timeline__node--${record.decision.toLowerCase()}`}
                    aria-hidden="true"
                  />
                  <div className="history-timeline__meta">
                    <StatusBadge status={record.decision} />
                    <span>V{record.contentVersion}</span>
                    <time dateTime={record.reviewedAt}>
                      {formatFullTime(record.reviewedAt)}
                    </time>
                  </div>
                  <strong>{record.reviewerName}</strong>
                  {reasonLabel(record) && <em>{reasonLabel(record)}</em>}
                  {record.comment && <p>{record.comment}</p>}
                </li>
              ))}
            </ol>
          )}
        </section>
      </article>

      <footer className="decision-bar">
        <div>
          <span className="decision-bar__indicator" aria-hidden="true" />
          <p>
            <strong>{canDecide ? "等待你的判断" : "该版本已完成审核"}</strong>
            <span>
              {canDecide
                ? "决定将绑定当前版本，提交后不可覆盖历史记录。"
                : "刷新队列可继续处理其他待审核内容。"}
            </span>
          </p>
        </div>
        {canDecide && (
          <div className="decision-bar__actions">
            <button
              className="button button--reject"
              type="button"
              onClick={() => onDecide("reject")}
            >
              驳回修改
            </button>
            <button
              className="button button--approve"
              type="button"
              onClick={() => onDecide("approve")}
            >
              通过内容
            </button>
          </div>
        )}
      </footer>
    </main>
  );
}

