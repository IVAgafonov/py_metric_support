from __future__ import annotations

from dataclasses import dataclass

from py_metric_support.metric_support import MetricSupport


@dataclass(frozen=True)
class Response:
    body: str
    content_type: str
    status_code: int = 200


class PrometheusController(MetricSupport):
    @property
    def routes(self) -> dict[str, callable]:
        return {
            "/api/metrics": self.metrics_response,
            "/api/metrics-json": self.json_metrics_response,
        }

    def metrics_response(self) -> Response:
        return Response(
            body=self.to_prometheus(),
            content_type='text/plain; version=0.0.4; charset=utf-8',
        )

    def json_metrics_response(self) -> Response:
        return Response(
            body=self.to_json_string(),
            content_type="application/json",
        )


prometheus_controller = PrometheusController()
