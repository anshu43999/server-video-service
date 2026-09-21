# Built-in COCO8 conversion smoke-test calibration set

Ultralytics COCO8 is a small, but versatile object detection dataset composed of the first 8 images of the COCO train
2017 set, 4 for training and 4 for validation. This dataset is ideal for testing and debugging object detection models,
or for experimenting with new detection approaches. With 8 images, it is small enough to be easily manageable, yet
diverse enough to test training pipelines for errors and act as a sanity check before training larger datasets.

This dataset is intended for use with Ultralytics YOLOv8.

Docs: https://docs.ultralytics.com
Community: https://community.ultralytics.com
GitHub: https://github.com/ultralytics/ultralytics

The supplied `LICENSE` is retained with the dataset. Review the current
Ultralytics and COCO terms before redistributing this repository or its Docker
images. The public dataset ID remains `coco8-dev` for configuration
compatibility. This asset verifies the conversion chain only; it is not
representative business calibration data. Business conversions should select a
versioned calibration set uploaded through the admin console.
