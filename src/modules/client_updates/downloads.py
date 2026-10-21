"""把已核验的下载文件清单按必需资源和选配标签归并。"""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from .contracts import (
    ClientDownloadPlan,
    ClientUpdateStructureError,
    sum_manifest_patch_file_sizes,
)


def manifest_download_plan(
    manifests: Sequence[tuple[str, object, object]],
    pak_key: str,
    res_key: str,
    *,
    basis: str = "patch_manifest",
    package_size: int = 0,
    package_from: int | None = None,
    package_to: int | None = None,
) -> ClientDownloadPlan:
    files: dict[tuple[str, str], tuple[str | None, int, str]] = {}
    for directory, pak, res in manifests:
        # 复用统计契约校验文件名、字节数与两个平台 key，不能把坏数据当成零。
        sum_manifest_patch_file_sizes(pak_key, res_key, pak, res)
        for payload, key in ((pak, pak_key), (res, res_key)):
            for entry in cast(dict[str, Any], payload)["pakFilesMap"][key][
                "pakFileInfos"
            ]:
                name, size = entry["fileName"], entry["fileSize"]
                digest = entry.get("hash")
                tag = entry.get("pakOptionalSign", "")
                if not isinstance(tag, str) or (
                    digest is not None and (not isinstance(digest, str) or not digest)
                ):
                    raise ClientUpdateStructureError("invalid download file metadata")
                identity = (digest, size, tag)
                path = (directory, name)
                if path in files and files[path] != identity:
                    raise ClientUpdateStructureError(
                        "conflicting download file identity"
                    )
                files[path] = identity

    required = package_size
    optional: dict[str, int] = {}
    for _digest, size, tag in files.values():
        if tag:
            optional[tag] = optional.get(tag, 0) + size
        else:
            required += size
    return ClientDownloadPlan(
        required_size_bytes=required,
        optional_sizes=tuple(sorted(optional.items())),
        basis=basis,
        package_from=package_from,
        package_to=package_to,
    )


def hdiff_download_size(payload: object) -> int:
    """只读取传输包大小，new_size 是安装后大小。"""

    if not isinstance(payload, Mapping):
        raise ClientUpdateStructureError("HPatchDiffMd5 must be an object")
    file = payload.get("hdiff_file")
    if not isinstance(file, Mapping):
        raise ClientUpdateStructureError("missing hdiff_file")
    name, digest, size = file.get("name"), file.get("md5"), file.get("size")
    if (
        not isinstance(name, str)
        or not name.endswith(".hdiff")
        or "/" in name
        or "\\" in name
        or not isinstance(digest, str)
        or len(digest) != 32
        or any(c not in "0123456789abcdefABCDEF" for c in digest)
        or type(size) is not int
        or size <= 0
    ):
        raise ClientUpdateStructureError("invalid hdiff download file")
    return size
