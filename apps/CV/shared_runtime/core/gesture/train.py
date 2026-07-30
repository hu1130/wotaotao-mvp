"""Train a lightweight gesture classifier from collected landmark samples.

Usage:
    python -m core.gesture.train

Reads samples from core/gesture/data/<label>/*.json
Saves model to core/gesture/model/gesture_classifier.joblib
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

import numpy as np
from core.gesture.schemas import FEATURE_VERSION, normalize_features

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")
MODEL_PATH = os.path.join(MODEL_DIR, "gesture_classifier.joblib")

LABELS = ["none", "heart", "ok", "middle_finger", "open_hand", "peace", "thumbs_up"]
LEGACY_SESSION_CHUNK_SIZE = 50


def build_classifier():
    try:
        from sklearn.ensemble import RandomForestClassifier
    except ImportError:
        print("ERROR: scikit-learn not installed.")
        print(
            "  Run: pip install scikit-learn -i https://pypi.tuna.tsinghua.edu.cn/simple"
        )
        sys.exit(1)
    return RandomForestClassifier(
        n_estimators=100,
        max_depth=12,
        min_samples_leaf=3,
        random_state=42,
        n_jobs=-1,
    )


def load_samples() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    X_list = []
    y_list = []
    group_list = []
    label_names = []
    legacy_normalized = 0

    for label in LABELS:
        label_dir = os.path.join(DATA_DIR, label)
        if not os.path.isdir(label_dir):
            print(f"  SKIP {label}: directory not found")
            if label == "none":
                print(
                    "    建议采集 none 类: python -m core.gesture.collect --gesture none --count 300"
                )
            continue

        files = sorted(f for f in os.listdir(label_dir) if f.endswith(".json"))
        if not files:
            print(f"  SKIP {label}: no samples")
            continue

        count = 0
        session_counts: dict[str, int] = defaultdict(int)
        for index, filename in enumerate(files):
            filepath = os.path.join(label_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                sample = json.load(f)
            features = sample.get("features")
            if features is None or len(features) != 63:
                continue
            if sample.get("feature_version") != FEATURE_VERSION:
                features = normalize_features(features)
                legacy_normalized += 1
                if features is None:
                    continue
            session_id = sample.get("session_id") or _legacy_session_id(label, index)
            X_list.append(features)
            y_list.append(label)
            group_list.append(session_id)
            session_counts[session_id] += 1
            count += 1

        label_names.append(label)
        print(f"  {label}: {count} samples, {len(session_counts)} sessions")

    if not X_list:
        raise RuntimeError("No training data found. Run collect.py first.")
    if legacy_normalized:
        print(
            f"  Normalized {legacy_normalized} legacy samples to feature version {FEATURE_VERSION}"
        )

    return (
        np.array(X_list, dtype=np.float32),
        np.array(y_list),
        np.array(group_list),
        label_names,
    )


def _legacy_session_id(label: str, index: int) -> str:
    return f"{label}:legacy:{index // LEGACY_SESSION_CHUNK_SIZE:03d}"


def split_by_label_groups(
    y: np.ndarray,
    groups: np.ndarray,
    test_size: float = 0.2,
) -> tuple[np.ndarray, np.ndarray] | None:
    rng = np.random.default_rng(42)
    train_indices: list[int] = []
    test_indices: list[int] = []
    for label in sorted(set(y.tolist())):
        label_indices = np.where(y == label)[0]
        label_groups = sorted(set(groups[label_indices].tolist()))
        if len(label_groups) < 2:
            return None
        test_group_count = max(1, int(round(len(label_groups) * test_size)))
        shuffled_groups = label_groups[:]
        rng.shuffle(shuffled_groups)
        test_groups = set(shuffled_groups[:test_group_count])
        for index in label_indices:
            if groups[index] in test_groups:
                test_indices.append(int(index))
            else:
                train_indices.append(int(index))
    if not train_indices or not test_indices:
        return None
    return np.array(train_indices), np.array(test_indices)


def train() -> None:
    try:
        from sklearn.metrics import classification_report
        from sklearn.model_selection import (
            GroupKFold,
            StratifiedGroupKFold,
            cross_val_score,
            train_test_split,
        )
    except ImportError:
        print("ERROR: scikit-learn not installed.")
        print(
            "  Run: pip install scikit-learn -i https://pypi.tuna.tsinghua.edu.cn/simple"
        )
        sys.exit(1)

    try:
        import joblib
    except ImportError:
        from sklearn.externals import joblib

    print("Loading training data...")
    X, y, groups, label_names = load_samples()
    print(f"Total: {len(X)} samples, {len(label_names)} classes")
    print(f"Classes: {label_names}")
    print(f"Feature dim: {X.shape[1]}")
    print(f"Sessions: {len(set(groups.tolist()))}")

    split = split_by_label_groups(y, groups)
    if split is None:
        print("WARNING: not enough sessions per label; falling back to random split")
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        train_groups = test_groups = None
    else:
        train_idx, test_idx = split
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        train_groups, test_groups = groups[train_idx], groups[test_idx]
        print(
            f"Group split: train={len(train_idx)} samples/{len(set(train_groups.tolist()))} sessions, "
            f"test={len(test_idx)} samples/{len(set(test_groups.tolist()))} sessions"
        )

    clf = build_classifier()

    print("\nTraining RandomForest...")
    clf.fit(X_train, y_train)

    train_acc = clf.score(X_train, y_train)
    test_acc = clf.score(X_test, y_test)
    print(f"Train accuracy: {train_acc:.4f}")
    print(f"Test accuracy:  {test_acc:.4f}")

    label_group_counts = [
        len(set(groups[np.where(y == label)[0]].tolist())) for label in label_names
    ]
    n_splits = min(5, min(label_group_counts)) if label_group_counts else 0
    if n_splits >= 2:
        print(f"\nSession cross-validation ({n_splits}-fold)...")
        try:
            cv = StratifiedGroupKFold(
                n_splits=n_splits,
                shuffle=True,
                random_state=42,
            )
        except TypeError:
            cv = GroupKFold(n_splits=n_splits)
        cv_scores = cross_val_score(
            clf,
            X,
            y,
            groups=groups,
            cv=cv,
            scoring="accuracy",
        )
        print(
            f"Session CV accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})"
        )
    else:
        print("\nSession cross-validation skipped: not enough sessions per label")

    print("\nClassification report (test set):")
    y_pred = clf.predict(X_test)
    print(classification_report(y_test, y_pred, labels=label_names))

    print("Feature importances (top 10):")
    importances = clf.feature_importances_
    top_indices = np.argsort(importances)[::-1][:10]
    landmark_names = [
        "wrist",
        "thumb_cmc",
        "thumb_mcp",
        "thumb_ip",
        "thumb_tip",
        "index_mcp",
        "index_pip",
        "index_dip",
        "index_tip",
        "middle_mcp",
        "middle_pip",
        "middle_dip",
        "middle_tip",
        "ring_mcp",
        "ring_pip",
        "ring_dip",
        "ring_tip",
        "pinky_mcp",
        "pinky_pip",
        "pinky_dip",
        "pinky_tip",
    ]
    for idx in top_indices:
        lm_idx = idx // 3
        axis = ["x", "y", "z"][idx % 3]
        print(f"  {landmark_names[lm_idx]}.{axis}: {importances[idx]:.4f}")

    print("\nRetraining final model on all samples...")
    final_clf = build_classifier()
    final_clf.fit(X, y)

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(final_clf, MODEL_PATH)
    print(f"\nModel saved to {MODEL_PATH}")


if __name__ == "__main__":
    train()
