"""Capture live gesture correction samples.

Usage:
    python -m core.gesture.capture_corrections

Hotkeys:
    n none
    h heart
    o ok
    m middle_finger
    a open_hand
    p peace
    t thumbs_up
    q quit
"""

from __future__ import annotations

import json
import os
import time
import uuid

import cv2

from core.gesture.classifier import StaticGestureClassifier
from core.gesture.collect import DATA_DIR
from core.gesture.detector import MediaPipeHandDetector
from core.gesture.schemas import (
    FEATURE_VERSION,
    HandObservation,
    observation_to_features,
)


HOTKEY_LABELS = {
    ord("n"): "none",
    ord("h"): "heart",
    ord("o"): "ok",
    ord("m"): "middle_finger",
    ord("a"): "open_hand",
    ord("p"): "peace",
    ord("t"): "thumbs_up",
}


def main() -> None:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: cannot open camera 0")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    detector = MediaPipeHandDetector()
    classifier = StaticGestureClassifier()
    session_id = f"correction-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    saved = 0
    print(f"Correction session: {session_id}")
    print(
        "Hotkeys: n none, h heart, o ok, m middle_finger, "
        "a open_hand, p peace, t thumbs_up, q quit"
    )

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                continue
            frame = cv2.flip(frame, 1)
            observations = detector.detect(frame)
            best = _best_observation(observations, classifier)
            display = frame.copy()
            status = "no hand"
            if best is not None:
                observation, prediction = best
                status = (
                    f"pred={prediction.name} conf={prediction.confidence:.2f} "
                    f"hand={observation.handedness} saved={saved}"
                )
                _draw_landmarks(display, observation)
            cv2.putText(
                display,
                status,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )
            cv2.imshow("Gesture Corrections", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key in HOTKEY_LABELS and best is not None:
                label = HOTKEY_LABELS[key]
                observation, prediction = best
                if _save_sample(label, observation, prediction, session_id):
                    saved += 1
                    print(
                        f"  saved {label} from pred={prediction.name} "
                        f"conf={prediction.confidence:.2f} total={saved}"
                    )
    finally:
        detector.close()
        cap.release()
        cv2.destroyAllWindows()


def _best_observation(
    observations: list[HandObservation],
    classifier: StaticGestureClassifier,
):
    best = None
    for observation in observations:
        prediction = classifier.classify(observation)
        if best is None or prediction.confidence > best[1].confidence:
            best = (observation, prediction)
    return best


def _draw_landmarks(frame, observation: HandObservation) -> None:
    h, w = frame.shape[:2]
    for lm in observation.landmarks:
        cx, cy = int(lm.x * w), int(lm.y * h)
        cv2.circle(frame, (cx, cy), 3, (0, 255, 255), -1)


def _save_sample(
    label: str,
    observation: HandObservation,
    prediction,
    session_id: str,
) -> bool:
    features = observation_to_features(observation)
    if features is None:
        return False
    label_dir = os.path.join(DATA_DIR, label)
    os.makedirs(label_dir, exist_ok=True)
    existing = [name for name in os.listdir(label_dir) if name.endswith(".json")]
    filepath = os.path.join(label_dir, f"{len(existing):05d}.json")
    sample = {
        "label": label,
        "hand": observation.handedness,
        "session_id": session_id,
        "feature_version": FEATURE_VERSION,
        "features": features,
        "source": "correction",
        "predicted_label": prediction.name,
        "predicted_confidence": prediction.confidence,
    }
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(sample, file)
    return True


if __name__ == "__main__":
    main()
