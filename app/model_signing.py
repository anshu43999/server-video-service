from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _boolean(value: bool) -> str:
    return "true" if value else "false"


def _number(value: Any) -> str:
    return str(float(value))


def canonical_manifest_payload(manifest: dict[str, Any]) -> bytes:
    """Mirror Android ModelPackageManifest.canonicalPayload() byte-for-byte."""
    model_file = manifest["modelFile"]
    runtime = manifest["runtime"]
    input_contract = manifest["input"]
    output_contract = manifest["output"]
    input_tensor = input_contract["tensor"]
    output_tensor = output_contract["tensor"]
    quantization = manifest["quantization"]
    license_info = manifest["license"]
    source = manifest["source"]
    lines = [
        f'schemaVersion={manifest["schemaVersion"]}',
        f'modelId={manifest["modelId"]}',
        f'version={manifest["version"]}',
        f'purpose={manifest["purpose"]}',
        f'runtime.name={runtime["name"]}',
        f'runtime.version={runtime["version"]}',
        f'modelFile.repositoryPath={model_file["repositoryPath"]}',
        f'modelFile.sizeBytes={model_file["sizeBytes"]}',
        f'modelFile.sha256={model_file["sha256"].lower()}',
        f'input.width={input_contract["width"]}',
        f'input.height={input_contract["height"]}',
        f'input.layout={input_contract["layout"]}',
        f'input.dataType={input_contract["dataType"].upper()}',
        f'input.colorOrder={input_contract["colorOrder"]}',
        f'input.valueRange={_number(input_contract["valueRange"][0])},{_number(input_contract["valueRange"][1])}',
        f'input.tensor.name={input_tensor["name"]}',
        f'input.tensor.shape={",".join(str(value) for value in input_tensor["shape"])}',
        f'input.tensor.dataType={input_tensor["dataType"].upper()}',
        f'input.tensor.quantization={_number(input_tensor["quantization"][0])},{input_tensor["quantization"][1]}',
        f'output.layout={output_contract["layout"]}',
        f'output.boxFormat={output_contract["boxFormat"]}',
        f'output.coordinateSpace={output_contract["coordinateSpace"]}',
        f'output.classCount={output_contract["classCount"]}',
        f'output.classScoreRange={output_contract["classScoreRange"][0]},{output_contract["classScoreRange"][1]}',
        f'output.hasObjectnessChannel={_boolean(output_contract["hasObjectnessChannel"])}',
        f'output.requiresNms={_boolean(output_contract["requiresNms"])}',
        f'output.decoderVersion={output_contract["decoderVersion"]}',
        f'output.tensor.name={output_tensor["name"]}',
        f'output.tensor.shape={",".join(str(value) for value in output_tensor["shape"])}',
        f'output.tensor.dataType={output_tensor["dataType"].upper()}',
        f'output.tensor.quantization={_number(output_tensor["quantization"][0])},{output_tensor["quantization"][1]}',
    ]
    lines.extend(f"labels[{index}]={label}" for index, label in enumerate(manifest["labels"]))
    lines.extend([
        f'labelSha256={manifest["labelSha256"].lower()}',
        f'quantization.scheme={quantization["scheme"]}',
        f'quantization.input={_number(quantization["inputScale"])},{quantization["inputZeroPoint"]}',
        f'quantization.output={_number(quantization["outputScale"])},{quantization["outputZeroPoint"]}',
        f'license.model={license_info["model"]}',
        f'license.data={license_info["data"]}',
        f'license.distribution={license_info["distribution"]}',
        f'source.repository={source["repository"]}',
        f'source.revision={source["revision"]}',
        f'minAppVersion={manifest["minAppVersion"]}',
        f'releaseEligible={_boolean(manifest["releaseEligible"])}',
    ])
    lines.extend(f"labelColors[{index}]={color}" for index, color in enumerate(manifest.get("labelColors", [])))
    return ("\n".join(lines) + "\n").encode("utf-8")


class ModelManifestSigner:
    def __init__(self, key_id: str | None, private_key_path: str | Path | None):
        self.key_id = key_id.strip() if key_id else None
        self.private_key_path = Path(private_key_path).expanduser() if private_key_path else None

    @property
    def configured(self) -> bool:
        return bool(self.key_id and self.private_key_path)

    def sign(self, manifest: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise ValueError("模型签名私钥尚未配置")
        if any(character.isspace() or not character.isprintable() for character in self.key_id or ""):
            raise ValueError("模型签名 keyId 格式无效")
        try:
            key_bytes = self.private_key_path.read_bytes()
            key = serialization.load_pem_private_key(key_bytes, password=None)
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("模型签名私钥无法读取或格式无效") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("模型签名私钥必须为 Ed25519")
        payload = canonical_manifest_payload(manifest)
        signed = dict(manifest)
        signed["signature"] = {
            "algorithm": "Ed25519",
            "keyId": self.key_id,
            "signatureBase64": base64.b64encode(key.sign(payload)).decode("ascii"),
            "signedPayloadSha256": hashlib.sha256(payload).hexdigest(),
        }
        return signed


def build_android_manifest(model_id: str, metadata: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    labels = result["labels"]
    size = int(result["input_size"])
    input_tensor = result["input"]
    output_tensor = result["output"]
    input_quantization = input_tensor.get("quantization", [0.0, 0])
    output_quantization = output_tensor.get("quantization", [0.0, 0])
    label_bytes = ("\n".join(labels) + "\n").encode("utf-8")
    return {
        "schemaVersion": 1,
        "modelId": model_id,
        "version": metadata["version"],
        "purpose": metadata["purpose"],
        "runtime": {"name": "LiteRT", "version": "2.1.6"},
        "modelFile": {
            "repositoryPath": f"models/{model_id}/{metadata['version']}/android.tflite",
            "sizeBytes": result["sizeBytes"],
            "sha256": result["sha256"],
        },
        "input": {
            "width": size,
            "height": size,
            "layout": "NCHW",
            "dataType": "float32",
            "colorOrder": "RGB",
            "valueRange": [0.0, 1.0],
            "tensor": input_tensor,
        },
        "output": {
            "layout": "batch,channels,candidates",
            "boxFormat": "center_x,center_y,width,height",
            "coordinateSpace": "normalized-input",
            "classCount": len(labels),
            "classScoreRange": [4, len(labels) + 3],
            "hasObjectnessChannel": False,
            "requiresNms": True,
            "decoderVersion": "yolo-v1",
            "tensor": output_tensor,
        },
        "labels": labels,
        "labelSha256": hashlib.sha256(label_bytes).hexdigest(),
        "quantization": {
            "scheme": str(result.get("quantization", "float32-boundary")),
            "inputScale": input_quantization[0],
            "inputZeroPoint": input_quantization[1],
            "outputScale": output_quantization[0],
            "outputZeroPoint": output_quantization[1],
        },
        "calibrationDataset": result.get("calibration_dataset"),
        "license": {
            "model": "administrator-supplied-review-required",
            "data": "administrator-supplied-review-required",
            "distribution": "internal-functional-testing-only" if metadata["purpose"] == "development" else "requires-review",
        },
        "source": {"repository": "administrator-upload", "revision": metadata["source_sha256"]},
        "minAppVersion": "0.1.0",
        "releaseEligible": False,
    }
