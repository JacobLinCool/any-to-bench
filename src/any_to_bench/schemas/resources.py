"""Public resource-corpus, access, and citation result models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

ResourceAccessMode = Literal["all_files", "utf8_text_only", "unknown"]


class ResourceFile(BaseModel):
    """One byte-faithful public file under ``resources/``."""

    path: str = Field(description="Bundle-relative POSIX path under resources/")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    text: bool = Field(description="Strict UTF-8 without NUL; exposed to direct LLM tools")

    @field_validator("path")
    @classmethod
    def _safe_canonical_path(cls, value: str) -> str:
        parsed = PurePosixPath(value)
        if (
            "\\" in value
            or parsed.is_absolute()
            or ".." in parsed.parts
            or len(parsed.parts) < 2
            or parsed.parts[0] != "resources"
            or parsed.as_posix() != value
        ):
            raise ValueError("must be a canonical bundle-relative POSIX path under resources/")
        return value


class Citation(BaseModel):
    """Optional evidence supplied with one answer."""

    path: str = Field(min_length=1, description="Bundle-relative public resource path")
    excerpt: str = Field(min_length=1, description="Exact excerpt copied from the resource")


class ResourceAccess(BaseModel):
    """The portion of a bundle's public corpus exposed to one taker."""

    mode: ResourceAccessMode
    total_files: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    exposed_files: int = Field(ge=0)
    exposed_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent_exposure(self) -> ResourceAccess:
        if self.exposed_files > self.total_files or self.exposed_bytes > self.total_bytes:
            raise ValueError("exposed resource counts must not exceed corpus totals")
        if self.mode == "all_files" and (
            self.exposed_files != self.total_files or self.exposed_bytes != self.total_bytes
        ):
            raise ValueError("all_files mode must expose the complete corpus")
        if self.mode == "unknown" and (self.exposed_files or self.exposed_bytes):
            raise ValueError("unknown mode cannot claim known resource exposure")
        return self

    @property
    def file_coverage(self) -> float | None:
        return self.exposed_files / self.total_files if self.total_files else None

    @property
    def byte_coverage(self) -> float | None:
        return self.exposed_bytes / self.total_bytes if self.total_bytes else None


CitationStatus = Literal["verified", "quote_mismatch", "missing_resource", "unverifiable_binary"]


class CitationCheck(BaseModel):
    question_id: str
    citation_index: int = Field(ge=0)
    path: str
    status: CitationStatus


class CitationSummary(BaseModel):
    submitted: int = 0
    valid_paths: int = 0
    verified: int = 0
    quote_mismatches: int = 0
    missing_resources: int = 0
    unverifiable_binary: int = 0

    @computed_field
    @property
    def path_valid_percentage(self) -> float | None:
        return 100.0 * self.valid_paths / self.submitted if self.submitted else None

    @computed_field
    @property
    def text_quote_verified_percentage(self) -> float | None:
        verifiable = self.verified + self.quote_mismatches
        return 100.0 * self.verified / verifiable if verifiable else None
