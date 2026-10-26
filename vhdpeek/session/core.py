"""
The stateful session behind any front end.

No toolkit here. A `Session` opens an image and exposes **scopes**: one per
partition, plus one per ISO mounted from inside a filesystem. Nothing is
opened automatically — the caller decides what to look at, which is what
makes an explorer behave like an explorer instead of jumping somewhere.

Every path operation names its scope, so the GUI can show the image, its
partitions and any mounted ISO in one tree, and the CLI can drive the same
object when that is convenient.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..core.containers import VHDInfo, detect_and_parse
from ..core.partitions import Partition, PartitionView, parse_partitions
from ..core.source import Source, make_source
from ..core.volume import Entry, format_size
from ..fs import mount_iso, open_reader, probe
from .types import ImageInfo, Scope, VolumeInfo


class Session:
    def __init__(self) -> None:
        self.source: Optional[Source] = None
        self.disk: Optional[VHDInfo] = None
        self.image: Optional[ImageInfo] = None
        self.volumes: List[VolumeInfo] = []
        self.scopes: List[Scope] = []
        self._partitions: List[Partition] = []
        self._readers: Dict[str, object] = {}
        self._iso_counter = 0

    # -- lifecycle ------------------------------------------------------

    def open(self, path_or_url: str) -> ImageInfo:
        """Open an image and probe every partition. Raises on failure."""
        self.close()
        source = make_source(path_or_url)
        try:
            disk = detect_and_parse(source)
        except Exception:
            source.close()
            raise

        self.source = source
        self.disk = disk
        self._partitions = parse_partitions(disk)
        self.volumes = []
        self.scopes = []
        self._readers = {}
        self._iso_counter = 0

        for part in self._partitions:
            self.volumes.append(self._open_partition(disk, part))

        self.image = ImageInfo(
            path=path_or_url,
            remote=path_or_url.lower().startswith(("http://", "https://")),
            disk_type=disk.disk_type,
            virtual_size=disk.virtual_size,
            file_size=disk.file_size,
            sector_size=disk.logical_sector_size,
            block_size=disk.block_size,
            is_dirty=disk.is_dirty,
            parent_name=disk.parent_name,
        )
        return self.image

    def _open_partition(self, disk: VHDInfo, part: Partition) -> VolumeInfo:
        info = VolumeInfo(
            index=part.index,
            start_lba=part.start_lba,
            end_lba=part.end_lba,
            type=part.type,
            name=part.name,
            size_bytes=part.size_bytes,
            scheme=part.scheme,
        )
        try:
            view = PartitionView(disk, part)
            info.fs_type = probe(view)
            if info.fs_type != "unknown":
                reader = open_reader(view)
                info.label = getattr(reader, "label", "") or ""
                scope_id = f"p{part.index}"
                self._readers[scope_id] = reader
                self.scopes.append(Scope(
                    id=scope_id,
                    kind="partition",
                    label=info.label or f"partition {part.index}",
                    fs_type=info.fs_type,
                    detail=info.subtitle,
                    index=part.index,
                    size_bytes=part.size_bytes,
                ))
        except Exception:
            info.fs_type = "unknown"
        return info

    def close(self) -> None:
        self._readers.clear()
        self.scopes = []
        self.volumes = []
        self._partitions = []
        self.disk = None
        self.image = None
        self._iso_counter = 0
        if self.source is not None:
            try:
                self.source.close()
            except Exception:
                pass
            self.source = None

    # -- scopes ---------------------------------------------------------

    def scope(self, scope_id: str) -> Scope:
        for scope in self.scopes:
            if scope.id == scope_id:
                return scope
        raise KeyError(f"no scope {scope_id!r}")

    def reader(self, scope_id: str):
        try:
            return self._readers[scope_id]
        except KeyError:
            raise KeyError(f"no reader for scope {scope_id!r}") from None

    def mount_iso(self, scope_id: str, path: str) -> Scope:
        """Mount an ISO that lives at `path` inside `scope_id`."""
        iso = mount_iso(self.reader(scope_id), path)
        self._iso_counter += 1
        new_id = f"iso{self._iso_counter}"
        self._readers[new_id] = iso
        name = path.rsplit("/", 1)[-1]
        scope = Scope(
            id=new_id,
            kind="iso",
            label=iso.volume_id or name,
            fs_type="iso9660",
            detail=self._iso_detail(iso),
            parent_scope=scope_id,
            parent_path=path,
            size_bytes=iso.volume_size,
        )
        self.scopes.append(scope)
        return scope

    @staticmethod
    def _iso_detail(iso) -> str:
        parts = [name for name, present in (
            ("Joliet", iso.has_joliet),
            ("Rock Ridge", iso.has_rock_ridge),
        ) if present]
        return ", ".join(parts) or format_size(iso.volume_size)

    def mounted_at(self, scope_id: str, path: str) -> Optional[Scope]:
        """The ISO scope mounted from (scope_id, path), if any."""
        for scope in self.scopes:
            if scope.kind == "iso" and scope.parent_scope == scope_id \
                    and scope.parent_path == path:
                return scope
        return None

    # -- filesystem access ---------------------------------------------

    def list_dir(self, scope_id: str, path: str = "") -> List[Entry]:
        return self.reader(scope_id).list_dir(path)

    def stat(self, scope_id: str, path: str) -> Optional[Entry]:
        return self.reader(scope_id).stat(path)

    def read_file(self, scope_id: str, path: str, offset: int = 0,
                  size: Optional[int] = None) -> bytes:
        return self.reader(scope_id).read_file(path, offset, size)

    def file_reader(self, scope_id: str, path: str):
        return self.reader(scope_id).file_reader(path)

    def walk(self, scope_id: str, path: str = "") -> List[tuple]:
        """
        Every file under `path`, as (relative path, size, absolute path).

        Used to size a recursive copy before it starts, so progress means
        something.
        """
        found: List[tuple] = []

        def visit(prefix: str) -> None:
            try:
                entries = self.list_dir(scope_id, prefix)
            except Exception:
                return
            for entry in entries:
                child = f"{prefix}/{entry.name}" if prefix else entry.path
                if entry.is_dir:
                    visit(child)
                else:
                    rel = (child[len(path):].lstrip("/")
                           if path else child.lstrip("/"))
                    found.append((rel, entry.size, child))

        visit(path)
        return found
