import unittest

from safe_drive.helmet import HELMET_CLASSES, HelmetDetection, HelmetInference


class FakeModel:
    names = {index: name for index, name in enumerate(HELMET_CLASSES)}


class HelmetInferenceTests(unittest.TestCase):
    def setUp(self):
        self.inference = HelmetInference(FakeModel())

    def test_requires_expected_model_class_order(self):
        model = FakeModel()
        model.names = {0: "no_helmet", 1: "half_face_helmet"}
        with self.assertRaisesRegex(ValueError, "classes must be ordered"):
            HelmetInference(model)

    def test_associates_head_box_only_to_unique_person_and_preserves_class(self):
        result = self.inference.associate(
            [("person-7", [0, 0, 100, 200])],
            [HelmetDetection((35, 15, 65, 45), "half_face_helmet", 0.91)],
        )
        self.assertEqual(result, {"person-7": "half_face_helmet"})

    def test_no_detection_does_not_infer_no_helmet(self):
        result = self.inference.associate([("person-7", [0, 0, 100, 200])], [])
        self.assertEqual(result, {"person-7": None})

    def test_ambiguous_person_association_is_uncertain(self):
        people = [("a", [0, 0, 100, 200]), ("b", [0, 0, 100, 200])]
        result = self.inference.associate(
            people, [HelmetDetection((35, 15, 65, 45), "no_helmet", 0.95)]
        )
        self.assertEqual(result, {"a": "uncertain", "b": "uncertain"})


if __name__ == "__main__":
    unittest.main()
