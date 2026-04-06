import json
import os
import time
import unittest

from py_metric_support import Measure, MetricSupport

class MetricSupportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_project_name = os.environ.get("PROJECT_NAME")
        os.environ["PROJECT_NAME"] = "unnamed_project"
        MetricSupport.reset_shared()

    def tearDown(self) -> None:
        MetricSupport.reset_shared()
        if self.previous_project_name is None:
            os.environ.pop("PROJECT_NAME", None)
        else:
            os.environ["PROJECT_NAME"] = self.previous_project_name

    def test_counter_increments_metric(self) -> None:
        MetricSupport.counter("test_counter", ("label1", "value1"), ("label2", "value2")).inc()
        MetricSupport.counter("test_counter", ("label2", "value2"), ("label1", "value1")).inc()

        self.assertIn(
            'unnamed_project_test_counter_total{label1="value1",label2="value2"} 2.0',
            MetricSupport.to_prometheus(),
        )

    def test_gauge_keeps_metric(self) -> None:
        MetricSupport.gauge("test_gauge", ("label1", "value1"), ("label2", "value2")).set(30)
        MetricSupport.gauge("test_gauge", ("label2", "value2"), ("label1", "value1")).inc()

        self.assertIn(
            'unnamed_project_test_gauge{label1="value1",label2="value2"} 31.0',
            MetricSupport.to_prometheus(),
        )

    def test_gauge_on_scrape_updates_metric(self) -> None:
        MetricSupport.gauge_on_scrape(
            "test_gauge_observe",
            "label1",
            "label2",
            callback=lambda: Measure(0.42, "value1", "value2"),
        )

        self.assertIn(
            'unnamed_project_test_gauge_observe{label1="value1",label2="value2"} 0.42',
            MetricSupport.to_prometheus(),
        )

    def test_summary_calculates_metric(self) -> None:
        MetricSupport.summary("test_summary", ("label1", "value1"), ("label2", "value2")).observe(10)
        MetricSupport.summary("test_summary", ("label2", "value2"), ("label1", "value1")).observe(10)

        rendered = MetricSupport.to_prometheus()
        self.assertIn(
            'unnamed_project_test_summary_count{label1="value1",label2="value2"} 2.0',
            rendered,
        )
        self.assertIn(
            'unnamed_project_test_summary_sum{label1="value1",label2="value2"} 20.0',
            rendered,
        )

    def test_summary_exports_requested_quantiles(self) -> None:
        metric = MetricSupport.summary(
            "test_summary_quantiles",
            ("label1", "value1"),
            quantiles=[0.5, (0.95, 0.01)],
        )
        for value in (1, 2, 3, 4, 5):
            metric.observe(value)

        rendered = MetricSupport.to_prometheus()
        self.assertIn(
            'unnamed_project_test_summary_quantiles{label1="value1",quantile="0.5"}',
            rendered,
        )
        self.assertIn(
            'unnamed_project_test_summary_quantiles{label1="value1",quantile="0.95"}',
            rendered,
        )

    def test_timer_counts_time(self) -> None:
        with MetricSupport.timer("test_timer", ("label1", "value1"), ("label2", "value2")):
            time.sleep(0.1)
        with MetricSupport.timer("test_timer", ("label2", "value2"), ("label1", "value1")):
            time.sleep(0.1)

        rendered = MetricSupport.to_prometheus()
        self.assertIn('unnamed_project_test_timer_count{label1="value1",label2="value2"} 2.0', rendered)
        self.assertIn('unnamed_project_test_timer_sum{label1="value1",label2="value2"}', rendered)

    def test_histogram_calculates_metric(self) -> None:
        MetricSupport.histogram("test_histogram", ("label1", "value1"), ("label2", "value2")).observe(10)
        MetricSupport.histogram("test_histogram", ("label2", "value2"), ("label1", "value1")).observe(10)

        rendered = MetricSupport.to_prometheus()
        self.assertIn(
            'unnamed_project_test_histogram_bucket{label1="value1",label2="value2",le="8.0"} 0',
            rendered,
        )
        self.assertIn(
            'unnamed_project_test_histogram_bucket{label1="value1",label2="value2",le="16.0"} 2',
            rendered,
        )

    def test_json_export_matches_expected_shape(self) -> None:
        MetricSupport.counter("test_counter_1").inc()
        MetricSupport.summary("test_summary_1").observe(0.1)

        payload = json.loads(MetricSupport.to_json_string())

        self.assertEqual(payload["counter"]["unnamed_project_test_counter_1"], 1.0)

if __name__ == "__main__":
    unittest.main()
