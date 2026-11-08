# Git-first server release

Effective 2026-11-08 by operator request. The source of a release is an explicitly
approved, pushed Git commit, not a developer directory or an ad-hoc server patch.

1. Review an explicit local file list. Keep unrelated changes, secrets, model
   uploads, databases, logs and caches out. Commit and push only with operator
   authorization; do not add the entire dirty workspace.
2. Check the build server working tree before synchronization. Stop on local
   edits or divergence; never discard them. Fetch the approved remote commit,
   fast-forward the intended branch where applicable, and verify the full SHA.
3. Build from a clean checkout of that SHA using its tracked Dockerfile and
   tools. The canonical video build is Dockerfile, including frontend builds,
   Java and the checksum-pinned Android verifier. Do not copy uncommitted files
   into server source, a temporary build context, or an existing image. Do not
   use the historical Dockerfile.app-updates overlay as the release path.
4. Use a new image tag, record the full source SHA in image revision metadata,
   and record actual base image digests, dependency locks, platform, build
   command and logs. Build cache is allowed. A Git SHA alone does not guarantee
   identical image bytes when external dependencies are not fully pinned.
5. Record image ID, pushed registry manifest digest, archive size and SHA256 as
   separate fields. Never overwrite a published tag. Match the build checkout
   SHA to the approved source before handing off the archive.
6. Apply production runtime configuration and switch workloads only under
   separate deployment approval. Do not bake credentials into source/images.
   Development and production model data and databases remain isolated.

Production App updates and external HTTPS APK storage remain required. Runtime
signing keys, feature flags and ConfigMaps are injected at deployment, not copied
into the image. This source commit does not enable or deploy production by itself.

## Current release scope

This change packages the existing M33-T26 ORM mapping fix and M42-T14 container
verifier tooling into the normal source build, with self-contained regression
tests. The index and JSON mappings match existing migrations; no new migration
or production database operation is part of this change.

The operator requested that remaining joint acceptance not be continued. API27,
real RTSP/long-duration acceptance and the known unnamed-model UI issue remain
unverified/unresolved; this is not a fabricated pass. New focused source tests
check this commit's packaging and mapping only, not complete production behavior.

The temporary 1.0.3-appupdates.20261108-r2 overlay image is retained as historical
evidence and is on hold for production handoff. A future image must be built from
this pushed source commit under a new tag. No production rollout, APK publication,
Git force push, or deletion of prior artifacts is authorized by this document.

This document defines the workflow, not an installed CI enforcement mechanism.
