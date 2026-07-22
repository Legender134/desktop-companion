from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping


@dataclass(frozen=True)
class ActionSource:
    atlas: Path
    manifest: Path
    action_id: str
    manifest_kind: Literal["pet", "action"] = "pet"
    atlas_start_frame: int | None = None


@dataclass(frozen=True)
class ShotSpec:
    id: str
    kind: Literal["action", "video", "still", "card"]
    duration_ms: int
    source: Path | ActionSource | None
    title: str = ""
    caption: str = ""
    loop: bool = False


@dataclass(frozen=True)
class ChapterSpec:
    id: str
    title: str
    duration_ms: int
    shots: tuple[ShotSpec, ...]


@dataclass(frozen=True)
class VideoPlan:
    chapters: tuple[ChapterSpec, ...]
    action_sources: Mapping[str, ActionSource]

    @property
    def duration_ms(self) -> int:
        return sum(chapter.duration_ms for chapter in self.chapters)

    @property
    def source_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for chapter in self.chapters:
            for shot in chapter.shots:
                if isinstance(shot.source, Path):
                    paths.append(shot.source)
                elif isinstance(shot.source, ActionSource):
                    paths.extend((shot.source.atlas, shot.source.manifest))
        return tuple(paths)
