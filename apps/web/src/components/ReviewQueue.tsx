import type { PendingReviewsPage } from "@wotao/contracts";
import type { PendingFilters } from "../api";
import { StatusBadge } from "./StatusBadge";

const MERCHANT_OPTIONS = [
  { id: "", name: "全部商家" },
  { id: "mer_jiangnan_001", name: "景德镇青屿瓷业" },
  { id: "mer_guangming_002", name: "宁波光屿家居" },
  { id: "mer_linjiang_003", name: "泉州林匠户外" },
];

interface ReviewQueueProps {
  data: PendingReviewsPage | null;
  filters: PendingFilters;
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onFiltersChange: (filters: PendingFilters) => void;
  onSelect: (contentId: string) => void;
  onRetry: () => void;
}

function formatSubmittedAt(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

export function ReviewQueue({
  data,
  filters,
  loading,
  error,
  selectedId,
  onFiltersChange,
  onSelect,
  onRetry,
}: ReviewQueueProps) {
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;

  return (
    <aside className="queue-panel" aria-label="待审核内容">
      <div className="queue-panel__heading">
        <div>
          <p className="eyebrow">Review queue</p>
          <h1>待审核内容</h1>
        </div>
        <span className="queue-count" aria-label={`${data?.total ?? 0} 条待审核`}>
          {String(data?.total ?? 0).padStart(2, "0")}
        </span>
      </div>

      <div className="queue-filters">
        <label>
          <span>商家</span>
          <select
            value={filters.merchantId}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                merchantId: event.target.value,
                page: 1,
              })
            }
          >
            {MERCHANT_OPTIONS.map((merchant) => (
              <option key={merchant.id || "all"} value={merchant.id}>
                {merchant.name}
              </option>
            ))}
          </select>
        </label>

        <div className="date-filter">
          <label>
            <span>从</span>
            <input
              type="datetime-local"
              value={filters.submittedFrom}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  submittedFrom: event.target.value,
                  page: 1,
                })
              }
            />
          </label>
          <label>
            <span>至</span>
            <input
              type="datetime-local"
              value={filters.submittedTo}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  submittedTo: event.target.value,
                  page: 1,
                })
              }
            />
          </label>
        </div>
      </div>

      <div className="queue-list" aria-live="polite" aria-busy={loading}>
        {loading &&
          Array.from({ length: 3 }, (_, index) => (
            <div className="queue-skeleton" key={index}>
              <span />
              <span />
              <span />
            </div>
          ))}

        {!loading && error && (
          <div className="state-panel state-panel--error">
            <strong>队列加载失败</strong>
            <p>{error}</p>
            <button type="button" className="text-button" onClick={onRetry}>
              重新加载
            </button>
          </div>
        )}

        {!loading && !error && data?.items.length === 0 && (
          <div className="state-panel">
            <span className="state-panel__mark" aria-hidden="true">
              ✓
            </span>
            <strong>当前筛选下没有待审核内容</strong>
            <p>调整商家或提交时间，查看其他内容。</p>
          </div>
        )}

        {!loading &&
          !error &&
          data?.items.map((item) => (
            <button
              type="button"
              key={item.contentId}
              className={`queue-item ${
                selectedId === item.contentId ? "queue-item--active" : ""
              }`}
              onClick={() => onSelect(item.contentId)}
            >
              <span className="queue-item__topline">
                <StatusBadge status={item.status} />
                <time dateTime={item.submittedAt}>
                  {formatSubmittedAt(item.submittedAt)}
                </time>
              </span>
              <strong>{item.title}</strong>
              <span className="queue-item__product">{item.productTitle}</span>
              <span className="queue-item__footer">
                <span>{item.merchantName}</span>
                <span className="version-token">V{item.contentVersion}</span>
              </span>
            </button>
          ))}
      </div>

      <div className="queue-pagination">
        <button
          type="button"
          disabled={filters.page <= 1 || loading}
          onClick={() => onFiltersChange({ ...filters, page: filters.page - 1 })}
          aria-label="上一页"
        >
          ←
        </button>
        <span>
          {filters.page} / {totalPages}
        </span>
        <button
          type="button"
          disabled={filters.page >= totalPages || loading}
          onClick={() => onFiltersChange({ ...filters, page: filters.page + 1 })}
          aria-label="下一页"
        >
          →
        </button>
      </div>
    </aside>
  );
}
