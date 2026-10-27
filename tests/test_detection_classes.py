import unittest

from safe_drive.cli import DETECTION_CLASSES, VEHICLE_CLASSES, detector_class_map


class DetectionClassTests(unittest.TestCase):
    def test_coco_person_and_supported_vehicle_classes_are_selected(self):
        self.assertEqual(DETECTION_CLASSES[0], "pedestrian")
        self.assertEqual({key: DETECTION_CLASSES[key] for key in VEHICLE_CLASSES}, VEHICLE_CLASSES)
        self.assertEqual(set(DETECTION_CLASSES), {0, 2, 3, 5, 7})

    def test_model_labels_are_mapped_by_name_not_assumed_class_id(self):
        names = {0: "motorcycle", 1: "person", 2: "car", 3: "truck", 4: "bus"}
        self.assertEqual(detector_class_map(names), {
            0: "motorcycle", 1: "pedestrian", 2: "car", 3: "truck", 4: "bus"
        })


if __name__ == "__main__":
    unittest.main()
