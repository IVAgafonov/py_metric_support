from __future__ import annotations

import json
import os
import resource
import threading
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Sequence

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Summary, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_summary import Summary as QuantileSummary


@dataclass(frozen=True)
class Measure:
    value: float
    label_values: tuple[str, ...]

    def __init__(self, value: float, *label_values: str) -> None:
        object.__setattr__(self, "value", float(value))
        object.__setattr__(self, "label_values", tuple(label_values))


@dataclass(frozen=True)
class _MetricKey:
    metric_type: str
    requested_name: str
    label_names: tuple[str, ...]
    config: tuple[object, ...] = ()


class _MetricBackend:
    def __init__(self) -> None:
        self.prefix = _sanitize_prefix(os.getenv("PROJECT_NAME", "unnamed_project"))
        self.registry = CollectorRegistry(auto_describe=True)
        self.lock = threading.RLock()
        self.metrics_cache: dict[_MetricKey, object] = {}
        self.registered_names: dict[str, tuple[str, tuple[str, ...]]] = {}


def _sanitize_prefix(value: str) -> str:
    return value.lower().translate(str.maketrans({" ": "_", ".": "_", ",": "_"}))


def _sorted_labels(labels: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(labels, key=lambda item: item[0])


def _normalize_summary_quantiles(
    quantiles: Sequence[float | tuple[float, float]] | None,
) -> tuple[tuple[float, float], ...]:
    if quantiles is None:
        return ()

    normalized: list[tuple[float, float]] = []
    for quantile in quantiles:
        if isinstance(quantile, tuple):
            rank, precision = quantile
        else:
            rank = quantile
            if rank >= 0.99:
                precision = 0.001
            elif rank >= 0.9:
                precision = 0.01
            else:
                precision = 0.05
        normalized.append((float(rank), float(precision)))

    return tuple(normalized)


def _build_quantile_summary(exported_name: str, label_names: Sequence[str], invariants: tuple[tuple[float, float], ...]):
    return QuantileSummary(
        exported_name,
        f"Summary for {exported_name}",
        labelnames=label_names,
        registry=MetricSupport._get_shared_backend().registry,
        invariants=invariants,
    )


class _GaugeCallbackCollector:
    def __init__(
        self,
        name: str,
        label_names: Sequence[str],
        callback: Callable[[], Sequence[Measure]],
    ) -> None:
        self.name = name
        self.label_names = tuple(label_names)
        self.callback = callback

    def collect(self) -> list[GaugeMetricFamily]:
        metric = GaugeMetricFamily(self.name, "gauge callback metric", labels=self.label_names)
        for measure in self.callback():
            metric.add_metric(measure.label_values, measure.value)
        return [metric]


class MetricSupport:
    _shared_backend: _MetricBackend | None = None
    _shared_lock = threading.RLock()

    def __init__(self) -> None:
        pass

    @classmethod
    def shared(cls) -> "MetricSupport":
        return cls()

    @classmethod
    def reset_shared(cls) -> None:
        with MetricSupport._shared_lock:
            MetricSupport._shared_backend = None

    @classmethod
    def _get_shared_backend(cls) -> _MetricBackend:
        with MetricSupport._shared_lock:
            if MetricSupport._shared_backend is None:
                MetricSupport._shared_backend = _MetricBackend()
            return MetricSupport._shared_backend

    @classmethod
    def counter(cls, name: str, *labels: tuple[str, str]):
        sorted_labels = _sorted_labels(labels)
        metric = cls._get_or_create_metric(
            "counter",
            name,
            [label_name for label_name, _ in sorted_labels],
            (),
            lambda exported_name, label_names: Counter(
                exported_name,
                f"Counter for {exported_name}",
                labelnames=label_names,
                registry=cls._get_shared_backend().registry,
            ),
        )
        return metric.labels(*[label_value for _, label_value in sorted_labels]) if sorted_labels else metric

    @classmethod
    def summary(
        cls,
        name: str,
        *labels: tuple[str, str],
        quantiles: Sequence[float | tuple[float, float]] | None = None,
    ):
        sorted_labels = _sorted_labels(labels)
        invariants = _normalize_summary_quantiles(quantiles)
        metric = cls._get_or_create_metric(
            "summary",
            name,
            [label_name for label_name, _ in sorted_labels],
            (
                ("quantiles",)
                + invariants
                if invariants
                else ()
            ),
            lambda exported_name, label_names: _build_quantile_summary(exported_name, label_names, invariants)
            if invariants
            else Summary(
                exported_name,
                f"Summary for {exported_name}",
                labelnames=label_names,
                registry=cls._get_shared_backend().registry,
            ),
        )
        return metric.labels(*[label_value for _, label_value in sorted_labels]) if sorted_labels else metric

    @classmethod
    def timer(cls, name: str, *labels: tuple[str, str], func: Callable[[], object] | None = None):
        if func is not None:
            start = time.perf_counter()
            result = func()
            cls.summary(name, *labels, quantiles=[0.1, 0.5, 0.9, 0.99]).observe(time.perf_counter() - start)
            return result

        @contextmanager
        def _timer_context() -> Iterator[None]:
            start = time.perf_counter()
            try:
                yield
            finally:
                cls.summary(name, *labels, quantiles=[0.1, 0.5, 0.9, 0.99]).observe(time.perf_counter() - start)

        return _timer_context()

    @classmethod
    def gauge(cls, name: str, *labels: tuple[str, str]):
        sorted_labels = _sorted_labels(labels)
        metric = cls._get_or_create_metric(
            "gauge",
            name,
            [label_name for label_name, _ in sorted_labels],
            (),
            lambda exported_name, label_names: Gauge(
                exported_name,
                f"Gauge for {exported_name}",
                labelnames=label_names,
                registry=cls._get_shared_backend().registry,
            ),
        )
        return metric.labels(*[label_value for _, label_value in sorted_labels]) if sorted_labels else metric

    @classmethod
    def gauge_on_scrape_seq(
        cls,
        name: str,
        *label_names: str,
        callback: Callable[[], Sequence[Measure]],
    ) -> None:
        cls._get_or_create_metric(
            "gauge_callback",
            name,
            list(label_names),
            (),
            lambda exported_name, metric_label_names: cls._register_collector(
                _GaugeCallbackCollector(exported_name, metric_label_names, callback)
            ),
        )

    @classmethod
    def gauge_on_scrape(
        cls,
        name: str,
        *label_names: str,
        callback: Callable[[], Measure],
    ) -> None:
        cls.gauge_on_scrape_seq(name, *label_names, callback=lambda: [callback()])

    @classmethod
    def histogram(
        cls,
        name: str,
        *labels: tuple[str, str],
        start: int = 1,
        factor: int = 2,
        count: int = 10,
    ):
        sorted_labels = _sorted_labels(labels)
        buckets = tuple(float(start * (factor**idx)) for idx in range(count))
        metric = cls._get_or_create_metric(
            "histogram",
            name,
            [label_name for label_name, _ in sorted_labels],
            (start, factor, count),
            lambda exported_name, label_names: Histogram(
                exported_name,
                f"Histogram for {exported_name}",
                labelnames=label_names,
                buckets=buckets,
                registry=cls._get_shared_backend().registry,
            ),
        )
        return metric.labels(*[label_value for _, label_value in sorted_labels]) if sorted_labels else metric

    @classmethod
    def to_prometheus(cls) -> str:
        return generate_latest(cls._get_shared_backend().registry).decode("utf-8")

    @classmethod
    def to_json_string(cls) -> str:
        result: dict[str, dict[str, float | int]] = {
            "counter": {},
            "summary": {},
            "histogram": {},
            "gauge": {},
        }

        for family in cls._get_shared_backend().registry.collect():
            if family.type == "counter":
                for sample in family.samples:
                    if sample.name.endswith("_created"):
                        continue
                    key = cls._json_metric_name(family.name, sample.labels)
                    if sample.name.endswith("_total"):
                        result["counter"][key] = sample.value
            elif family.type == "gauge":
                for sample in family.samples:
                    result["gauge"][cls._json_metric_name(family.name, sample.labels)] = sample.value
            elif family.type == "summary":
                for sample in family.samples:
                    key = cls._json_metric_name(family.name, sample.labels)
                    if sample.name.endswith("_sum"):
                        result["summary"][f"{key}[sum]"] = sample.value
                    elif sample.name.endswith("_count"):
                        result["summary"][f"{key}[count]"] = sample.value
                    else:
                        result["summary"][key] = sample.value
            elif family.type == "histogram":
                bucket_index = 0
                for sample in family.samples:
                    if sample.name.endswith("_created"):
                        continue
                    key = cls._json_metric_name(family.name, sample.labels, exclude=("le",))
                    if sample.name.endswith("_bucket"):
                        le = sample.labels["le"]
                        if le == "+Inf":
                            continue
                        suffix = f"[b_{chr(bucket_index + 97)}_{le}]"
                        result["histogram"][f"{key}{suffix}"] = sample.value
                        bucket_index += 1
                    elif sample.name.endswith("_sum"):
                        result["histogram"][f"{key}[sum]"] = sample.value
                    elif sample.name.endswith("_count"):
                        result["histogram"][f"{key}[count]"] = sample.value

        return json.dumps(result, indent=2, sort_keys=True)

    @classmethod
    def collect_app_metrics(cls) -> None:
        tracemalloc.start()

        def memory_usage() -> Sequence[Measure]:
            current, peak = tracemalloc.get_traced_memory()
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_bytes = rss if os.uname().sysname == "Darwin" else rss * 1024
            return [
                Measure(peak, "heap", "max"),
                Measure(current, "heap", "used"),
                Measure(rss_bytes, "non_heap", "max"),
                Measure(rss_bytes, "non_heap", "used"),
            ]

        def cpu_usage() -> Sequence[Measure]:
            measures = [Measure(time.process_time(), "process_cpu_time")]
            try:
                measures.append(Measure(os.getloadavg()[0], "cpu_load"))
            except OSError:
                pass
            return measures

        cls.gauge_on_scrape_seq("memory_usage", "type", "measure", callback=memory_usage)
        cls.gauge_on_scrape_seq("cpu_usage", "type", callback=cpu_usage)

    @classmethod
    def toPrometheus(cls) -> str:
        return cls.to_prometheus()

    @classmethod
    def toJsonString(cls) -> str:
        return cls.to_json_string()

    @classmethod
    def gaugeOnScrapeSeq(
        cls,
        name: str,
        *label_names: str,
        callback: Callable[[], Sequence[Measure]],
    ) -> None:
        cls.gauge_on_scrape_seq(name, *label_names, callback=callback)

    @classmethod
    def gaugeOnScrape(
        cls,
        name: str,
        *label_names: str,
        callback: Callable[[], Measure],
    ) -> None:
        cls.gauge_on_scrape(name, *label_names, callback=callback)

    @classmethod
    def collectAppMetrics(cls) -> None:
        cls.collect_app_metrics()

    @classmethod
    def _get_or_create_metric(
        cls,
        metric_type: str,
        name: str,
        label_names: Sequence[str],
        config: tuple[object, ...],
        factory: Callable[[str, Sequence[str]], object],
    ) -> object:
        key = _MetricKey(metric_type, name, tuple(label_names), config)
        backend = cls._get_shared_backend()
        with backend.lock:
            metric = backend.metrics_cache.get(key)
            if metric is not None:
                return metric

            exported_name = cls._resolve_exported_name(name, metric_type, tuple(label_names), config)
            metric = factory(exported_name, label_names)
            backend.metrics_cache[key] = metric
            return metric

    @classmethod
    def _resolve_exported_name(
        cls,
        requested_name: str,
        metric_type: str,
        label_names: tuple[str, ...],
        config: tuple[object, ...],
    ) -> str:
        backend = cls._get_shared_backend()
        base_name = f"{backend.prefix}_{requested_name}"
        candidate = base_name
        suffix = 1
        signature = (metric_type, label_names, config)

        while True:
            existing = backend.registered_names.get(candidate)
            if existing is None or existing == signature:
                backend.registered_names[candidate] = signature
                return candidate
            candidate = f"{base_name}_{suffix}"
            suffix += 1

    @classmethod
    def _register_collector(cls, collector: object) -> object:
        cls._get_shared_backend().registry.register(collector)
        return collector

    @staticmethod
    def _json_metric_name(metric_name: str, labels: dict[str, str], exclude: Sequence[str] = ()) -> str:
        suffix = "".join(
            f"[{label_name}:{label_value}]"
            for label_name, label_value in labels.items()
            if label_name not in exclude
        )
        return f"{metric_name}{suffix}"
