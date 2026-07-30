"""Collect hand landmark samples for gesture classifier training.

Usage:
    python -m core.gesture.collect --gesture heart --count 200
    python -m core.gesture.collect --gesture ok --count 200
    python -m core.gesture.collect --gesture none --count 300

Keys during collection:
    SPACE  - start/pause collection
    Q      - quit
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid

import cv2

from core.gesture.detector import MediaPipeHandDetector
from core.gesture.schemas import (
    FEATURE_VERSION,
    HandObservation,
    observation_to_features,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

GESTURE_LABELS = [
    "none",
    "heart",
    "ok",
    "middle_finger",
    "open_hand",
    "peace",
    "thumbs_up",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect gesture landmark samples")
    parser.add_argument(
        "--gesture",
        required=True,
        choices=GESTURE_LABELS,
        help="Gesture label to collect",
    )
    parser.add_argument(
        "--count", type=int, default=200, help="Number of samples to collect"
    )
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    args = parser.parse_args()

    gesture_dir = os.path.join(DATA_DIR, args.gesture)
    os.makedirs(gesture_dir, exist_ok=True)

    existing_files = [f for f in os.listdir(gesture_dir) if f.endswith(".json")]
    start_index = len(existing_files)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"ERROR: cannot open camera {args.camera}")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    detector = MediaPipeHandDetector()
    detect_scale = 1.25
    collected = 0
    target = args.count
    collecting = False
    last_collect_time = 0.0
    collect_interval = 0.15
    session_id = f"{args.gesture}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

    print(
        f"Collecting '{args.gesture}' samples: {start_index} existing, target {start_index + target}"
    )
    print(f"Session: {session_id}")
    print("Press SPACE to start/pause, Q to quit")

    try:
        while collected < target:
            ret, frame = cap.read()
            if not ret:
                continue

            frame = cv2.flip(frame, 1)

            if detect_scale > 1.0:
                frame = cv2.resize(
                    frame,
                    None,
                    fx=detect_scale,
                    fy=detect_scale,
                    interpolation=cv2.INTER_LINEAR,
                )

            observations = detector.detect(frame)

            display = frame.copy()
            status_text = f"{args.gesture}: {collected}/{target}"
            if collecting:
                status_text += " [COLLECTING]"
            else:
                status_text += " [PAUSED - press SPACE]"
            cv2.putText(
                display,
                status_text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )

            if observations:
                for obs in observations:
                    for lm in obs.landmarks:
                        h, w = frame.shape[:2]
                        cx, cy = int(lm.x * w), int(lm.y * h)
                        cv2.circle(display, (cx, cy), 3, (0, 255, 255), -1)

            cv2.imshow("Gesture Collector", display)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break
            elif key == ord(" "):
                collecting = not collecting
                print(f"{'Started' if collecting else 'Paused'} collecting")

            if collecting and observations:
                now = time.time()
                if now - last_collect_time >= collect_interval:
                    for obs in observations:
                        features = observation_to_features(obs)
                        if features is None:
                            continue
                        sample = {
                            "label": args.gesture,
                            "hand": obs.handedness,
                            "session_id": session_id,
                            "feature_version": FEATURE_VERSION,
                            "features": features,
                        }
                        filepath = os.path.join(
                            gesture_dir, f"{start_index + collected:05d}.json"
                        )
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(sample, f)
                        collected += 1
                        last_collect_time = now
                        if collected >= target:
                            break
                        print(f"  Saved {collected}/{target}", end="\r")

    finally:
        detector.close()
        cap.release()
        cv2.destroyAllWindows()

    print(
        f"\nDone! Collected {collected} samples for '{args.gesture}' in {gesture_dir}"
    )


if __name__ == "__main__":
    main()
