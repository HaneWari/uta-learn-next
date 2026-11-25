"""更新检查、下载补丁、回退。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import jobs, settings, updater
from app.schemas import UpdateApplyRequest

router = APIRouter()


@router.get("/api/update/check")
def api_update_check(force: bool = False):
    """Compare this build with the newest release.

    `force=false` respects the 自动检查更新 setting: a disabled check returns
    "unknown" rather than hitting the network, because the user turned it off
    on purpose.
    """
    if not force and not settings.get("update_check", True):
        return {"enabled": False, "available": False, "current": updater.APP_VERSION}
    try:
        manifest = updater.fetch_manifest()
    except updater.NoManifest as e:
        return {"enabled": True, "available": False,
                "current": updater.APP_VERSION, "note": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"enabled": True, "available": False,
                "current": updater.APP_VERSION, "error": str(e)}
    return {"enabled": True, **updater.decide(manifest)}


@router.post("/api/update/apply")
def api_update_apply(payload: UpdateApplyRequest | None = None):
    """Download the pending update in the background and stage it."""
    body = payload or {}
    try:
        manifest = body.get("manifest") or updater.fetch_manifest()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"无法获取更新清单：{e}") from None
    decision = updater.decide(manifest)
    if not decision["available"]:
        raise HTTPException(status_code=409, detail="已经是最新版本")
    if decision["kind"] != "patch":
        raise HTTPException(
            status_code=409,
            detail="这个版本更换了运行时，需要下载完整包（发布页可手动下载）",
        )
    asset = decision["asset"]
    jid = jobs.create("update", "net")

    def work(progress):
        progress(0.02, "下载更新…")
        zip_path = updater.download(asset, progress)
        progress(0.92, "校验并解压…")
        updater.stage_patch(zip_path, progress)
        updater.mark_pending(str(manifest.get("version") or ""))
        return {"ready": True, "version": manifest.get("version"),
                "needs_restart": True}

    jobs.run(jid, work)
    return {"job_id": jid, "kind": "patch"}


@router.get("/api/update/pending")
def api_update_pending():
    return {"version": updater.pending_version()}


@router.post("/api/update/rollback")
def api_update_rollback():
    """Restore the previous app layer (available after one patch update)."""
    if not updater.rollback():
        raise HTTPException(status_code=404, detail="没有可回退的上一版本")
    return {"rolled_back": True, "needs_restart": True}
