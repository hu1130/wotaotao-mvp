import { useEffect, useId, useState } from "react";
import {
  REJECTION_REASONS,
  type RejectionReasonCode,
  type ReviewContentDetail,
} from "@wotao/contracts";

export type DecisionMode = "approve" | "reject";

export interface DecisionPayload {
  comment: string;
  reasonCode?: RejectionReasonCode;
}

interface DecisionDialogProps {
  mode: DecisionMode;
  content: ReviewContentDetail;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (payload: DecisionPayload) => void;
}

export function DecisionDialog({
  mode,
  content,
  submitting,
  error,
  onClose,
  onSubmit,
}: DecisionDialogProps) {
  const titleId = useId();
  const [comment, setComment] = useState("");
  const [reasonCode, setReasonCode] = useState<RejectionReasonCode | "">("");

  useEffect(() => {
    setComment("");
    setReasonCode("");
  }, [mode, content.contentId]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !submitting) onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, submitting]);

  const isReject = mode === "reject";
  const canSubmit = !submitting && (!isReject || comment.trim().length > 0);

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className={`decision-dialog decision-dialog--${mode}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="decision-dialog__mark" aria-hidden="true">
          {isReject ? "×" : "✓"}
        </div>
        <div className="decision-dialog__heading">
          <p className="eyebrow">{isReject ? "Return to merchant" : "Release gate"}</p>
          <h2 id={titleId}>{isReject ? "驳回这个版本？" : "确认通过这个版本？"}</h2>
          <p>
            《{content.title}》 · V{content.contentVersion}
          </p>
        </div>

        {isReject && (
          <label className="dialog-field">
            <span>结构化原因（可选）</span>
            <select
              value={reasonCode}
              onChange={(event) =>
                setReasonCode(event.target.value as RejectionReasonCode | "")
              }
              autoFocus
            >
              <option value="">不选择分类</option>
              {REJECTION_REASONS.map((reason) => (
                <option value={reason.code} key={reason.code}>
                  {reason.label}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="dialog-field">
          <span>{isReject ? "给商家的驳回说明（必填）" : "内部备注（可选）"}</span>
          <textarea
            autoFocus={!isReject}
            value={comment}
            maxLength={1000}
            rows={5}
            placeholder={
              isReject
                ? "具体说明需要修改的内容，商家将看到这段文字。"
                : "记录判断依据，备注仅供内部查看。"
            }
            onChange={(event) => setComment(event.target.value)}
          />
          <small>{comment.length} / 1000</small>
        </label>

        {error && <p className="dialog-error">{error}</p>}

        <div className="decision-dialog__actions">
          <button
            className="button button--quiet"
            type="button"
            disabled={submitting}
            onClick={onClose}
          >
            返回检查
          </button>
          <button
            className={`button ${isReject ? "button--reject" : "button--approve"}`}
            type="button"
            disabled={!canSubmit}
            onClick={() =>
              onSubmit({
                comment: comment.trim(),
                ...(reasonCode ? { reasonCode } : {}),
              })
            }
          >
            {submitting
              ? "正在记录…"
              : isReject
                ? "确认驳回"
                : "确认通过"}
          </button>
        </div>
      </section>
    </div>
  );
}

