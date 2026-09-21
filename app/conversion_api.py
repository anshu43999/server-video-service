from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .auth import require_admin
from .calibration import CalibrationDatasetCatalog, CalibrationDatasetError
from .conversion import ConversionConfig, ConversionPreflightError, ConversionService, atomic_json
from .model_catalog import ModelCatalog
from .model_signing import ModelManifestSigner, build_android_manifest
from .config import settings


class UploadMetadata(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(default="1.0.0", min_length=1, max_length=50)
    scenario: str = Field(default="general-detection", min_length=1, max_length=100)
    purpose: Literal["development", "business"] = "development"


class ModelJobs:
    def __init__(self, service: ConversionService, catalog: ModelCatalog,
                 calibration_catalog: CalibrationDatasetCatalog, signer: ModelManifestSigner):
        self.service, self.catalog = service, catalog
        self.calibration_catalog, self.signer = calibration_catalog, signer
        service.handler = self.execute

    def upload_path(self, upload_id: str) -> Path:
        if len(upload_id) != 32 or any(c not in "0123456789abcdef" for c in upload_id):
            raise ValueError("非法上传标识")
        return self.service.root / "uploads" / upload_id

    def execute(self, job: dict, directory: Path, config: ConversionConfig) -> dict:
        if job["action"] == "check":
            return self.service.run_action(job, config, "check", directory)
        self.service.report_progress(job, {
            "stage": "preparing",
            "message": "正在校验并复制上传的 PT 文件",
        })
        upload_id = job["metadata"]["upload_id"]
        upload_dir = self.upload_path(upload_id)
        metadata = json.loads((upload_dir / "metadata.json").read_text(encoding="utf-8"))
        original = upload_dir / "source.pt"
        if self.catalog.sha256(original).lower() != metadata["source_sha256"].lower():
            raise ValueError("上传的 PT 已变化，请重新上传")
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, directory / "source.pt")
        model_id = "uploaded-" + upload_id
        action = job["action"]
        if action == "inspect":
            # PT must actually load in the server runtime, independent of WSL/export readiness.
            runtime = config.model_copy(update={"mode": "local", "python_path": sys.executable})
            result = self.service.run_action(job, runtime, "inspect", directory)
            self.service.report_progress(job, {
                "stage": "publishing",
                "message": "PT 验证通过，正在登记服务端模型资产",
            })
            self.catalog.publish_upload(model_id, metadata, result, original, "server")
            conversion_error = None
            if config.auto_convert:
                try:
                    calibration = self.calibration_catalog.snapshot(
                        config.default_calibration_dataset_id
                    )
                    self.service.submit("mobile", {
                        "upload_id": upload_id,
                        "calibration_dataset": calibration,
                    })
                except ValueError as exc:
                    conversion_error = str(exc)
            return {**result, "model_id": model_id, "server_ready": True,
                    "auto_conversion_error": conversion_error}
        current = self.catalog.get(model_id)
        if not current.get("serverReady"):
            raise ValueError("PT 尚未通过服务端验证")
        if current.get("androidConverted"):
            raise ValueError("该版本已有移动端产物，无需重复转换")
        # Source labels and input size are frozen when PT validation succeeded.
        calibration = job["metadata"].get("calibration_dataset")
        if not isinstance(calibration, dict):
            raise ValueError("转换任务缺少校准集快照，请重新创建任务")
        calibration_path = self.calibration_catalog.runtime_path(calibration, config.mode)
        config = config.model_copy(update={
            "input_size": current["inputSize"],
            "calibration_data": calibration_path,
        })
        result = self.service.run_action(job, config, "mobile", directory)
        result["calibration_dataset"] = calibration
        self.service.report_progress(job, {
            "stage": "publishing",
            "message": "转换与复验通过，正在签名并登记移动端模型资产",
        })
        manifest = build_android_manifest(model_id, metadata, result)
        signature_status = "unsigned"
        if self.signer.configured:
            manifest = self.signer.sign(manifest)
            signature_status = "signed"
        atomic_json(directory / "android-manifest.json", manifest)
        publication = {**result, "signatureStatus": signature_status, "signatureValid": signature_status == "signed"}
        self.catalog.publish_upload(model_id, metadata, publication, directory / "android.tflite", "android")
        return {**result, "model_id": model_id, "server_ready": True,
                "android_converted": True, "android_ready": signature_status == "signed",
                "signature_status": signature_status}

    def calibration_references(self, dataset_id: str) -> list[str]:
        references = [
            f"task:{job['id']}"
            for job in self.service.jobs()
            if isinstance(job.get("metadata", {}).get("calibration_dataset"), dict)
            and job["metadata"]["calibration_dataset"].get("datasetId") == dataset_id
        ]
        references.extend(f"model:{model_id}" for model_id in self.catalog.calibration_references(dataset_id))
        return references


def create_conversion_router(service: ConversionService, catalog: ModelCatalog,
                             max_upload_bytes: int = 512 * 1024 * 1024,
                             calibration_catalog: CalibrationDatasetCatalog | None = None,
                             max_calibration_upload_bytes: int = 512 * 1024 * 1024,
                             signer: ModelManifestSigner | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/conversion", dependencies=[Depends(require_admin)], tags=["model conversion"])
    signer = signer or ModelManifestSigner(settings.model_signing_key_id, settings.model_signing_private_key_path)
    calibration_catalog = calibration_catalog or CalibrationDatasetCatalog(
        service.root.parents[1] / "calibration"
    )
    pipeline = ModelJobs(service, catalog, calibration_catalog, signer)
    uploading = asyncio.Semaphore(1)
    calibration_uploading = asyncio.Semaphore(1)

    @router.get("/config")
    def get_config():
        return {"config": service.config().model_dump(), "max_upload_bytes": max_upload_bytes,
                "max_calibration_upload_bytes": max_calibration_upload_bytes,
                "concurrency": 1, "workspace": str(service.root.resolve()),
                "supported_modes": ["wsl", "local", "remote"], "remote_service_supported": True}

    @router.put("/config")
    def save_config(config: ConversionConfig):
        try:
            return {"config": service.configure(config).model_dump()}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def submit(action: str, metadata: dict | None = None):
        try:
            return service.submit(action, metadata)
        except ConversionPreflightError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/check", status_code=202)
    def check_environment():
        return submit("check")

    @router.get("/jobs")
    def list_jobs():
        return {"jobs": service.jobs()[:100]}

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return service.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc

    @router.post("/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str):
        try:
            return service.retry(job_id)
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        except ConversionPreflightError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/jobs/{job_id}/log", response_class=PlainTextResponse)
    def job_log(job_id: str):
        job = get_job(job_id)
        log = service.root / job["id"] / str(job["attempt"]) / "worker.log"
        if not log.is_file():
            return "任务尚未产生执行日志"
        with log.open("rb") as handle:
            handle.seek(max(0, log.stat().st_size - 32000))
            return handle.read(32000).decode("utf-8", errors="replace")

    @router.get("/calibration-datasets")
    def list_calibration_datasets():
        return {
            "datasets": calibration_catalog.list(),
            "max_upload_bytes": max_calibration_upload_bytes,
            "max_expanded_bytes": calibration_catalog.max_expanded_bytes,
            "max_files": calibration_catalog.max_files,
        }

    @router.get("/calibration-datasets/{dataset_id}")
    def get_calibration_dataset(dataset_id: str):
        try:
            return calibration_catalog.get(dataset_id)
        except KeyError as exc:
            raise HTTPException(404, "校准集不存在") from exc

    @router.post("/calibration-datasets", status_code=201)
    async def upload_calibration_dataset(
        request: Request,
        filename: str = Query(min_length=1, max_length=200),
        name: str = Query(min_length=1, max_length=100),
        version: str = Query(min_length=1, max_length=50),
        scenario: str = Query(min_length=1, max_length=100),
    ):
        if Path(filename).suffix.lower() != ".zip":
            raise HTTPException(422, "请上传包含校准图片的 ZIP 文件")
        if calibration_uploading.locked():
            raise HTTPException(429, "已有校准集正在上传，请稍后重试")
        temporary = calibration_catalog.incoming_path()
        async with calibration_uploading:
            received = 0
            try:
                with temporary.open("wb") as handle:
                    async with asyncio.timeout(300):
                        async for chunk in request.stream():
                            received += len(chunk)
                            if received > max_calibration_upload_bytes:
                                raise HTTPException(413, "校准集 ZIP 超过上传大小限制")
                            await asyncio.to_thread(handle.write, chunk)
                if not received:
                    raise HTTPException(422, "校准集 ZIP 为空")
                try:
                    return await asyncio.to_thread(
                        calibration_catalog.create_from_zip,
                        temporary,
                        name=name,
                        version=version,
                        scenario=scenario,
                    )
                except CalibrationDatasetError as exc:
                    raise HTTPException(422, str(exc)) from exc
            finally:
                temporary.unlink(missing_ok=True)

    @router.delete("/calibration-datasets/{dataset_id}")
    def delete_calibration_dataset(dataset_id: str):
        with service._guard:
            references = pipeline.calibration_references(dataset_id)
            if references:
                raise HTTPException(409, f"校准集已被 {len(references)} 个模型或转换任务引用")
            try:
                return {"deleted": calibration_catalog.delete(dataset_id)}
            except KeyError as exc:
                raise HTTPException(404, "校准集不存在") from exc
            except CalibrationDatasetError as exc:
                raise HTTPException(409, str(exc)) from exc

    @router.post("/uploads", status_code=202)
    async def upload(request: Request, filename: str = Query(min_length=1, max_length=200),
                     name: str = Query(min_length=1, max_length=100), version: str = Query(default="1.0.0", min_length=1, max_length=50),
                     scenario: str = Query(default="general-detection", min_length=1, max_length=100),
                     purpose: Literal["development", "business"] = "development"):
        if Path(filename).suffix.lower() != ".pt":
            raise HTTPException(422, "请上传训练完成的 .pt 目标检测权重")
        if uploading.locked():
            raise HTTPException(429, "已有上传正在进行，请稍后重试")
        try:
            metadata = UploadMetadata(name=name.strip(), version=version.strip(), scenario=scenario.strip(), purpose=purpose).model_dump()
        except ValueError as exc:
            raise HTTPException(422, "模型名称、版本与场景不能为空白") from exc
        upload_id = uuid.uuid4().hex
        upload_dir = pipeline.upload_path(upload_id)
        async with uploading:
            upload_dir.mkdir(parents=True, exist_ok=False)
            target = upload_dir / "source.pt"
            received, digest = 0, hashlib.sha256()
            try:
                with target.open("wb") as handle:
                    async with asyncio.timeout(300):
                        async for chunk in request.stream():
                            received += len(chunk)
                            if received > max_upload_bytes:
                                raise HTTPException(413, "模型文件超过上传大小限制")
                            if shutil.disk_usage(upload_dir).free < len(chunk) + 128 * 1024 * 1024:
                                raise HTTPException(507, "磁盘空间不足，请清理后重试")
                            digest.update(chunk)
                            await asyncio.to_thread(handle.write, chunk)
                if not received:
                    raise HTTPException(422, "模型文件为空")
                metadata.update(source_sha256=digest.hexdigest(), upload_id=upload_id)
                atomic_json(upload_dir / "metadata.json", metadata)
                job = submit("inspect", {"upload_id": upload_id, "name": name, "version": version})
                return {"upload_id": upload_id, "model_id": "uploaded-" + upload_id, "job": job}
            except BaseException:
                # This directory was just created by this request, contains no registered artifact.
                target.unlink(missing_ok=True)
                (upload_dir / "metadata.json").unlink(missing_ok=True)
                upload_dir.rmdir()
                raise

    @router.post("/uploads/{upload_id}/mobile", status_code=202)
    def convert_mobile(
        upload_id: str,
        calibration_dataset_id: str | None = Query(default=None, alias="calibrationDatasetId"),
    ):
        try:
            pipeline.upload_path(upload_id)
            model = catalog.get("uploaded-" + upload_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, "未找到已验证的上传模型") from exc
        with service._guard:
            if model.get("androidConverted"):
                raise HTTPException(409, "该版本已经生成移动端产物")
            if any(job["metadata"].get("upload_id") == upload_id and job["action"] == "mobile" and
                   job["status"] in {"queued", "running"} for job in service.jobs()):
                raise HTTPException(409, "该模型已有移动端转换任务")
            selected = calibration_dataset_id or service.config().default_calibration_dataset_id
            try:
                calibration = calibration_catalog.snapshot(selected)
            except KeyError as exc:
                raise HTTPException(422, "请选择有效的校准集") from exc
            except CalibrationDatasetError as exc:
                raise HTTPException(422, str(exc)) from exc
            return submit("mobile", {
                "upload_id": upload_id,
                "name": model["name"],
                "version": model["version"],
                "calibration_dataset": calibration,
            })

    return router
