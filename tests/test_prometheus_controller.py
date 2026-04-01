import json
import os
import unittest

from py_metric_support import MetricSupport
from py_metric_support.controller import PrometheusController



class PrometheusControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_project_name = os.environ.get("PROJECT_NAME")
        os.environ["PROJECT_NAME"] = "unnamed_project"
        MetricSupport.reset_shared()
        self.controller = PrometheusController()

    def tearDown(self) -> None:
        MetricSupport.reset_shared()
        if self.previous_project_name is None:
            os.environ.pop("PROJECT_NAME", None)
        else:
            os.environ["PROJECT_NAME"] = self.previous_project_name

    def test_controller_has_metrics_to_export(self) -> None:
        self.controller.counter("test_counter_1").inc()

        metrics_response = self.controller.metrics_response()
        self.assertIn("unnamed_project_test_counter_1_total 1.0", metrics_response.body)
        self.assertEqual(metrics_response.content_type, "text/plain; version=0.0.4; charset=utf-8")

        json_response = self.controller.json_metrics_response()
        payload = json.loads(json_response.body)
        self.assertEqual(payload["counter"]["unnamed_project_test_counter_1"], 1.0)

    def test_shared_metrics_are_visible_through_shared_controller(self) -> None:
        MetricSupport.shared().counter("shared_counter").inc()

        metrics_response = PrometheusController.shared().metrics_response()

        self.assertIn("unnamed_project_shared_counter_total 1.0", metrics_response.body)


if __name__ == "__main__":
    unittest.main()
