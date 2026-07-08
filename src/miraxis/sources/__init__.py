"""Dataset source layer.

The only place miraxis performs filesystem or network I/O for reading a
dataset (02_ARCHITECTURE.md §3.1). Resolves a local path or Hub repo id into
a version-detected SourceHandle with lazy, bounded access to metadata,
Parquet shards, and video shards.
"""

from miraxis.sources.bounds import MAX_DECLARED_EPISODES, MAX_DECLARED_FRAMES, check_resource_bound
from miraxis.sources.handles import VideoShardHandle, open_parquet_shard, open_video_shard
from miraxis.sources.info import DatasetInfoModel, load_info
from miraxis.sources.loader import SourceHandle, SourceLoader
from miraxis.sources.paths import safe_join
from miraxis.sources.version import DatasetVersion, detect_version

__all__ = [
    "MAX_DECLARED_EPISODES",
    "MAX_DECLARED_FRAMES",
    "DatasetInfoModel",
    "DatasetVersion",
    "SourceHandle",
    "SourceLoader",
    "VideoShardHandle",
    "check_resource_bound",
    "detect_version",
    "load_info",
    "open_parquet_shard",
    "open_video_shard",
    "safe_join",
]
