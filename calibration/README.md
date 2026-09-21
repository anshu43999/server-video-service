# Calibration asset workspace

Local development stores calibration assets uploaded through the admin API in
this directory. The service generates dataset YAML files and content hashes;
do not edit managed upload assets by hand. Uploaded dataset contents are
intentionally ignored by Git, and Docker deployments store them in the
`calibration-data` named volume.

`builtin/dev8` is the only checked-in exception. It contains the real
Ultralytics COCO8 smoke-test dataset, including its images, labels and license.
It proves that the production converter can complete an offline INT8 export,
but it is not representative data for a business model.
