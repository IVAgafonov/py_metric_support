# py_metric_support

Prometheus metric helper.

## Install

```bash
pip install -e .
```

Or with requirements files:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Usage

```python
from py_metric_support import Measure, MetricSupport

MetricSupport.counter("requests_total", ("path", "/health")).inc()
MetricSupport.gauge("workers").set(4)
MetricSupport.gauge_on_scrape("build_info", "version", callback=lambda: Measure(1, "0.1.0"))
MetricSupport.summary("request_latency_seconds", ("path", "/health"), quantiles=[0.5, (0.95, 0.01)]).observe(0.123)

print(MetricSupport.to_prometheus())
print(MetricSupport.to_json_string())
```

`quantiles=` accepts either raw ranks like `0.5` or `(rank, precision)` pairs like `(0.95, 0.01)`.
When quantiles are requested, `py_metric_support` uses the `prometheus-summary` backend because the official Python Prometheus client exports `_sum` and `_count` only.
