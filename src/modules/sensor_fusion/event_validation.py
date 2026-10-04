"""Stateful sliding-window validation that prevents transient alert escalation."""
from collections import defaultdict, deque
from time import time
from typing import Any, Dict

class EventValidator:
    def __init__(self, config: Dict[str, Any]): self.config=config["temporal"]; self.history=defaultdict(lambda: deque(maxlen=self.config["window_size"]))
    def ingest(self, event: str, confidence: float) -> Dict[str, Any]:
        samples=self.history[event]; now=time(); samples.append((now, confidence)); good=[v for _,v in samples if v >= self.config["minimum_average_confidence"]]
        consecutive=len(samples)>=self.config["consecutive_positive"] and all(v >= self.config["minimum_average_confidence"] for _,v in list(samples)[-self.config["consecutive_positive"]:])
        confirmed=len(good)>=self.config["positive_frames"] and consecutive
        state="CONFIRMED" if confirmed else ("OBSERVING" if samples else "CANDIDATE")
        return {"state": state, "confirmed": confirmed, "positive_frames": len(good), "window_size": len(samples), "persistence_ratio": round(len(good)/max(1,len(samples)),3), "average_confidence": round(sum(v for _,v in samples)/len(samples),3)}
