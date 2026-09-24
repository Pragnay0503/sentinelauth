"""
serialization.py - Universal JSON serialization safeguards for NumPy data types.
Prevents "Object of type int64 is not JSON serializable" across all pipeline outputs,
database payloads, and API responses.
"""
from __future__ import annotations

import json
from typing import Any
import numpy as np


def to_json_safe(obj: Any) -> Any:
    """
    Recursively walks any dict, list, tuple, or scalar value and converts
    NumPy scalars and arrays to native Python types (int, float, bool, list).
    """
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, set):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return [to_json_safe(v) for v in obj.tolist()]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if hasattr(obj, "item") and callable(obj.item):
        try:
            val = obj.item()
            if isinstance(val, (int, float, bool, str)):
                return val
        except Exception:
            pass
    return obj


class NumpySafeEncoder(json.JSONEncoder):
    """
    Custom JSONEncoder that automatically converts NumPy data types to standard Python primitives.
    """
    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        if hasattr(obj, "item") and callable(obj.item):
            try:
                val = obj.item()
                if isinstance(val, (int, float, bool, str)):
                    return val
            except Exception:
                pass
        return super().default(obj)


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """
    Convenience wrapper executing to_json_safe and encoding with NumpySafeEncoder.
    """
    kwargs.setdefault("cls", NumpySafeEncoder)
    return json.dumps(to_json_safe(obj), **kwargs)
