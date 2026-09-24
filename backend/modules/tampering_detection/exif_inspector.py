"""
exif_inspector.py - EXIF metadata and forensic tool signature inspection.
Detects image editing suites, stripped metadata, and timestamp discrepancies.
"""
import io
from typing import Dict, List, Optional, Union
from PIL import Image, ExifTags
from .schemas import EXIFResult

_SUSPICIOUS_SOFTWARE_KEYWORDS = [
    "photoshop", "gimp", "canva", "picsart", "snapseed", "pixelmator",
    "paint.net", "lightroom", "affinity", "coreldraw", "illustrator",
    "facetune", "airbrush", "photoscape", "retouch"
]


def inspect_exif(image_input: Union[bytes, str]) -> EXIFResult:
    """
    Inspects image EXIF headers for editing signatures and anomalies.
    """
    try:
        if isinstance(image_input, str):
            pil_img = Image.open(image_input)
        elif isinstance(image_input, (bytes, bytearray)):
            pil_img = Image.open(io.BytesIO(image_input))
        else:
            return EXIFResult(
                has_exif=False,
                software_detected=None,
                editing_tools_found=[],
                is_suspicious=False,
                metadata_dump={"note": "In-memory raw array; no EXIF container available"}
            )
    except Exception as e:
        return EXIFResult(
            has_exif=False,
            software_detected=None,
            editing_tools_found=[],
            is_suspicious=False,
            metadata_dump={"error": str(e)}
        )

    raw_exif = None
    try:
        raw_exif = pil_img.getexif()
    except Exception:
        raw_exif = None

    metadata_dump: Dict[str, str] = {}
    software_tag: Optional[str] = None
    editing_tools_found: List[str] = []
    has_exif: bool = False

    if raw_exif and len(raw_exif) > 0:
        has_exif = True
        for tag_id, val in raw_exif.items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            val_str = str(val).strip()
            # Store up to 15 key attributes
            if len(metadata_dump) < 15 and len(val_str) < 100:
                metadata_dump[tag_name] = val_str

            if tag_name.lower() in ("software", "processingsoftware", "imageuniqueid"):
                software_tag = val_str
                for keyword in _SUSPICIOUS_SOFTWARE_KEYWORDS:
                    if keyword in val_str.lower():
                        if keyword not in editing_tools_found:
                            editing_tools_found.append(keyword.capitalize())

    # Also inspect IPTC, PNG text chunks, or container info
    info = getattr(pil_img, "info", {})
    if info:
        for k, v in info.items():
            k_str = str(k).lower()
            v_str = str(v).lower()
            if len(metadata_dump) < 15 and len(str(v)) < 100:
                metadata_dump[str(k)] = str(v)
            for keyword in _SUSPICIOUS_SOFTWARE_KEYWORDS:
                if keyword in v_str and keyword.capitalize() not in editing_tools_found:
                    editing_tools_found.append(keyword.capitalize())
            if k_str in ("software", "source", "tool") and not software_tag:
                software_tag = str(v)
                has_exif = True

    if not has_exif and not metadata_dump:
        metadata_dump["status"] = "EXIF stripped or not present in image container"

    is_suspicious = len(editing_tools_found) > 0

    return EXIFResult(
        has_exif=has_exif,
        software_detected=software_tag,
        editing_tools_found=editing_tools_found,
        is_suspicious=is_suspicious,
        metadata_dump=metadata_dump
    )
