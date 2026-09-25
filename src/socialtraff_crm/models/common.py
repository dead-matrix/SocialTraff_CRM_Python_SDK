"""Shared pydantic building blocks.

CRM always sends datetimes with an offset. Models use ``AwareDatetime`` so a naive value is
rejected instead of being silently treated as local time (plan §7.2, Notes п.3).
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict

__all__ = ["AwareDatetime", "CrmModel"]


class CrmModel(BaseModel):
    """Base for CRM payloads: immutable, unknown fields ignored for forward compatibility."""

    model_config = ConfigDict(extra="ignore", frozen=True)
