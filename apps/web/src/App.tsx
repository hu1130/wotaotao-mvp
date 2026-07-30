import { useCallback, useEffect, useState } from "react";
import type {
  RejectionReasonCode,
  ReviewContentDetail,
} from "@wotao/contracts";
import {
  ApiError,
  approveReview,
  getPendingReviews,
  getReviewDetail,
  rejectReview,
  type PendingFilters,
} from "./api";
import {
  DecisionDialog,
  type DecisionMode,
  type DecisionPayload,
} from "./components/DecisionDialog";
import { ReviewDetail } from "./components/ReviewDetail";
import { ReviewQueue } from "./components/ReviewQueue";

const INITIAL_FILTERS: PendingFilters = {
  page: 1,
  pageSize: 20,
  merchantId: "",
  submittedFrom: "",
  submittedTo: "",
};

function readSelectedContent(): string | null {
  return new URLSearchParams(window.location.search).get("contentId");
}

function messageFromError(error: unknown): string {
  if (error instanceof ApiError) {
    if (
      error.errorCode === "REVIEW_STATUS_CHANGED" ||
      error.errorCode === "REVIEW_CONFLICT" ||
      error.errorCode === "CONTENT_VERSION_CONFLICT"
    ) {
      return `${error.message}（请求 ${error.requestId}）`;
    }
    return error.message;
  }
  return "网络连接失败，请确认审核服务已经启动。";
}

export function App() {
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [queue, setQueue] = useState<Awaited<
    ReturnType<typeof getPendingReviews>
  > | null>(null);
  const [queueLoading, setQueueLoading] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [selectedId, setSelectedIdState] = useState(readSelectedContent);
  const [detail, setDetail] = useState<ReviewContentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [decisionMode, setDecisionMode] = useState<DecisionMode | null>(null);
  const [decisionSubmitting, setDecisionSubmitting] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const setSelectedId = useCallback((contentId: string | null) => {
    setSelectedIdState(contentId);
    const url = new URL(window.location.href);
    if (contentId) url.searchParams.set("contentId", contentId);
    else url.searchParams.delete("contentId");
    window.history.pushState({}, "", url);
  }, []);

  useEffect(() => {
    const handlePopState = () => setSelectedIdState(readSelectedContent());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setQueueLoading(true);
    setQueueError(null);

    void getPendingReviews(filters, controller.signal)
      .then((data) => {
        setQueue(data);
        if (
          selectedId &&
          !data.items.some((item) => item.contentId === selectedId)
        ) {
          setSelectedId(null);
        } else if (!selectedId && data.items[0]) {
          setSelectedId(data.items[0].contentId);
        }
      })
      .catch((error: unknown) => {
        if ((error as Error).name !== "AbortError") {
          setQueueError(messageFromError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setQueueLoading(false);
      });

    return () => controller.abort();
  }, [filters, reloadKey, selectedId, setSelectedId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError(null);
      return;
    }

    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError(null);

    void getReviewDetail(selectedId, controller.signal)
      .then(setDetail)
      .catch((error: unknown) => {
        if ((error as Error).name !== "AbortError") {
          setDetailError(messageFromError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });

    return () => controller.abort();
  }, [selectedId, reloadKey]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4_000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  async function handleDecision(payload: DecisionPayload) {
    if (!detail || !decisionMode) return;
    setDecisionSubmitting(true);
    setDecisionError(null);

    try {
      if (decisionMode === "approve") {
        await approveReview(detail.contentId, {
          contentVersion: detail.contentVersion,
          ...(payload.comment ? { comment: payload.comment } : {}),
        });
        setToast("内容已通过，可进入发布门禁检查。");
      } else {
        await rejectReview(detail.contentId, {
          contentVersion: detail.contentVersion,
          comment: payload.comment,
          ...(payload.reasonCode
            ? { reasonCode: payload.reasonCode as RejectionReasonCode }
            : {}),
        });
        setToast("内容已驳回，原因将对商家可见。");
      }

      setDecisionMode(null);
      setSelectedId(null);
      setReloadKey((value) => value + 1);
    } catch (error) {
      setDecisionError(messageFromError(error));
    } finally {
      setDecisionSubmitting(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="我淘淘内容审核台">
          <span className="brand__stamp" aria-hidden="true">
            淘
          </span>
          <span>
            <strong>我淘淘</strong>
            <small>内容审核台</small>
          </span>
        </a>
        <div className="operator-chip">
          <span className="operator-chip__status" aria-hidden="true" />
          <span>
            <small>当前运营</small>
            <strong>陈晨</strong>
          </span>
          <i>OP</i>
        </div>
      </header>

      <div className="workspace">
        <ReviewQueue
          data={queue}
          filters={filters}
          loading={queueLoading}
          error={queueError}
          selectedId={selectedId}
          onFiltersChange={setFilters}
          onSelect={setSelectedId}
          onRetry={() => setReloadKey((value) => value + 1)}
        />
        <ReviewDetail
          detail={detail}
          loading={detailLoading}
          error={detailError}
          hasSelection={Boolean(selectedId)}
          onRetry={() => setReloadKey((value) => value + 1)}
          onDecide={(mode) => {
            setDecisionError(null);
            setDecisionMode(mode);
          }}
        />
      </div>

      {decisionMode && detail && (
        <DecisionDialog
          mode={decisionMode}
          content={detail}
          submitting={decisionSubmitting}
          error={decisionError}
          onClose={() => {
            if (!decisionSubmitting) setDecisionMode(null);
          }}
          onSubmit={(payload) => void handleDecision(payload)}
        />
      )}

      {toast && (
        <div className="toast" role="status">
          <span aria-hidden="true">✓</span>
          {toast}
        </div>
      )}
    </div>
  );
}
