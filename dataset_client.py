"""Dataset Collector Universal Client SDK
1-line dataset access and project synchronization across ClimateTwin, FinanceIntelligenceSystem, and Edge-AI.

Usage:
    from dataset_client import get_dataset, list_datasets, sync_to_project, ingest_telemetry

    # Load as pandas DataFrame
    df = get_dataset('climatetwin_cmwssb_reservoirs')
    print(df.head())

    # Ingest raw CSV telemetry directly
    res = ingest_telemetry(raw_csv_string, title="Realtime Sensors", project="climatetwin")
"""
from __future__ import annotations
import csv
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Auto-detect Dataset Collector root
BASE_DIR = Path(__file__).resolve().parent
PROJECTS_ROOT = BASE_DIR.parent
DEFAULT_API_URL = os.getenv("DATASET_COLLECTOR_URL", "http://127.0.0.1:8080")


def _api_get(endpoint: str) -> Dict[str, Any]:
    url = f"{DEFAULT_API_URL.rstrip('/')}{endpoint}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DatasetClient/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def _api_post(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{DEFAULT_API_URL.rstrip('/')}{endpoint}"
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "DatasetClient/1.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        raise RuntimeError(f"API Error ({e.code}): {err_msg}")
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Dataset Collector API at {url}: {e}")


def list_datasets() -> List[Dict[str, Any]]:
    """Lists all available datasets across local cache, curated project catalog, and downloaded manifests."""
    datasets = []
    # 1. From API if server is running
    manifest_data = _api_get("/api/manifest")
    if manifest_data and "manifest" in manifest_data:
        for m in manifest_data["manifest"]:
            datasets.append({
                "id": m.get("id"),
                "title": m.get("title"),
                "source": m.get("source"),
                "path": m.get("local_path"),
                "files_count": m.get("files_count", 1)
            })

    # 2. Local fallback inspection
    synth_dir = BASE_DIR / "datasets" / "synthetic"
    if synth_dir.exists():
        for d in synth_dir.iterdir():
            if d.is_dir() and (d / "metadata.json").exists():
                try:
                    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
                    if not any(x["id"] == meta.get("id") for x in datasets):
                        datasets.append({
                            "id": meta.get("id", f"synthetic:{d.name}"),
                            "title": meta.get("title", d.name),
                            "source": "synthetic",
                            "path": str(d),
                            "files_count": len([f for f in d.iterdir() if f.is_file()])
                        })
                except Exception:
                    pass

    return datasets


def get_dataset(
    dataset_id: str,
    as_dataframe: bool = True,
    file_name: Optional[str] = None
) -> Any:
    """Loads a dataset by ID or slug.

    Args:
        dataset_id: ID or slug (e.g. 'climatetwin_cmwssb_reservoirs', 'synthetic:chennai_reservoir_telemetry', 'uci:45')
        as_dataframe: If True and pandas is available, returns a pandas.DataFrame; otherwise returns list of dicts.
        file_name: Optional specific file name within the dataset folder to read.

    Returns:
        pandas.DataFrame or List[dict]
    """
    slug = dataset_id.split(":", 1)[1] if ":" in dataset_id else dataset_id
    search_paths = [
        BASE_DIR / "datasets" / "synthetic" / slug,
        BASE_DIR / "datasets" / "ingested" / slug,
        BASE_DIR / "datasets" / "uci" / slug,
        BASE_DIR / "datasets" / "huggingface" / slug,
        BASE_DIR / "datasets" / "kaggle" / slug,
        BASE_DIR / "datasets" / slug,
        PROJECTS_ROOT / "climatetwin" / "data" / "raw" / "water_level" / "cmwssb",
        PROJECTS_ROOT / "FinanceIntelligenceSystem" / "data" / "market" / slug,
        PROJECTS_ROOT / "Edge-AI" / slug,
    ]

    target_file: Optional[Path] = None

    for p in search_paths:
        if not p.exists():
            continue
        if p.is_file():
            target_file = p
            break
        if file_name and (p / file_name).exists():
            target_file = p / file_name
            break
        # Pick primary CSV or JSON
        csv_candidates = list(p.glob("*.csv"))
        if csv_candidates:
            target_file = csv_candidates[0]
            break
        json_candidates = [j for j in p.glob("*.json") if j.name not in ("metadata.json", "manifest.json")]
        if json_candidates:
            target_file = json_candidates[0]
            break

    if not target_file or not target_file.exists():
        raise FileNotFoundError(
            f"Dataset '{dataset_id}' could not be located locally. "
            f"Make sure it is downloaded or generated via Dataset Collector."
        )

    # Read data
    ext = target_file.suffix.lower()
    if as_dataframe:
        try:
            import pandas as pd
            if ext == ".csv":
                return pd.read_csv(target_file)
            elif ext == ".json":
                return pd.read_json(target_file)
            elif ext == ".parquet":
                return pd.read_parquet(target_file)
        except ImportError:
            pass  # Fallback to standard Python types

    # Standard python structure
    if ext == ".csv":
        with open(target_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    elif ext == ".json":
        with open(target_file, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return target_file.read_bytes()


def sync_to_project(dataset_id: str, project: str) -> Dict[str, Any]:
    """Syncs a dataset to a project ('climatetwin', 'finance', 'edgeai', etc.)."""
    return _api_post("/api/projects/sync", {"dataset_id": dataset_id, "destination": project})


def ingest_telemetry(
    raw_content: str,
    title: Optional[str] = None,
    project: str = "climatetwin",
    format: str = "csv"
) -> Dict[str, Any]:
    """Ingests raw CSV or JSON text and immediately syncs it to the target project."""
    return _api_post("/api/projects/ingest", {
        "raw_content": raw_content,
        "title": title,
        "destination": project,
        "format": format
    })
