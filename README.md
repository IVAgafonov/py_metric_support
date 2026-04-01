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

print(MetricSupport.to_prometheus())
print(MetricSupport.to_json_string())
```
