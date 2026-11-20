#!/usr/bin/env bash
# Run only on the authorized development build server with an explicit stage.
set -euo pipefail
stage=${1:?explicit existing build directory required}
image=aiyolo-video-service:1.0.3-appupdates.20261106-r1
test -d "$stage"
test -f "$stage/Dockerfile.app-updates"
cd "$stage"
docker image inspect "$image" --format '{{.Id}} {{.Os}}/{{.Architecture}} user={{.Config.User}} size={{.Size}}'
run=(docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev,size=268435456 --entrypoint python)
"${run[@]}" "$image" /app/tools/check_app_update_runtime.py --tools-only
"${run[@]}" "$image" /app/tools/check_cpu_runtime.py
"${run[@]}" "$image" -m pip check
"${run[@]}" "$image" -c 'import os,subprocess; assert os.getuid()==10001; print("uid=10001"); subprocess.run([os.environ["APP_APK_AAPT2_PATH"],"version"],check=True); subprocess.run([os.environ["APP_APK_JAVA_PATH"],"-version"],check=True); subprocess.run([os.environ["APP_APK_JAVA_PATH"],"-jar",os.environ["APP_APK_APKSIGNER_JAR_PATH"],"version"],check=True)'
"${run[@]}" "$image" -c 'import os,sys; sys.path.insert(0,"/app/tools"); from check_app_update_runtime import check; result=check(os.environ); assert not result["ok"]; assert not result["production_ready"]; print("Missing runtime configuration correctly rejected; no production settings loaded")'
docker image inspect aiyolo-video-service:1.0.3-build.20261106-c1e554f --format '{{.Id}}'
docker image inspect aiyolo-model-converter:1.0.2-build.20261106-c1e554f --format '{{.Id}}'
archive=aiyolo-video-service-1.0.3-appupdates.20261106-r1.tar.gz
test ! -e "$archive"
test ! -e "$archive.partial"
docker save "$image" | gzip -1 > "$archive.partial"
gzip -t "$archive.partial"
mv "$archive.partial" "$archive"
sha256sum "$archive" | tee "$archive.sha256"
sha256sum -c "$archive.sha256"
stat -c '%n %s bytes' "$archive"
df -h /
