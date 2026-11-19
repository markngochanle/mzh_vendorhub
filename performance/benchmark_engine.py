"""
Multi-threaded HTTP Benchmark Engine with detailed statistical analysis.
Designed with pure Python standard library for maximum portability and zero external dependencies.
"""

import io
import time
import math
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, List, Dict, Any, Optional

from performance.config import SLA_THRESHOLDS
import server


class MockHeaders(dict):
    def get(self, k, default=""):
        return super().get(k.lower(), default)

    def __getitem__(self, k):
        return super().__getitem__(k.lower())

    def __contains__(self, k):
        return super().__contains__(k.lower())


class DirectHandler(server.Handler):
    """
    Direct in-process handler for running benchmarks without network proxy interference.
    Executes actual server routing, business logic, templates, and database queries.
    """
    def __init__(self, path: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, body: bytes = b""):
        self.path = path
        self.command = method.upper()
        self.headers = MockHeaders({"user-agent": "MizuhoVMS-PerfTester/1.0", "host": "localhost:8800"})
        if headers:
            for k, v in headers.items():
                self.headers[k.lower()] = str(v)
        if body and "content-length" not in self.headers:
            self.headers["content-length"] = str(len(body))
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.response_status = 200
        self.response_headers = {}

    def send_response(self, status: int, message: Optional[str] = None):
        self.response_status = status

    def send_header(self, name: str, value: Any):
        self.response_headers[name.lower()] = str(value)

    def end_headers(self):
        pass

    def log_message(self, *args):
        pass


@dataclass
class RequestMetric:
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    bytes_received: int
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class BenchmarkResult:
    scenario_name: str
    concurrency: int
    duration_sec: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate_pct: float
    rps: float
    throughput_kb_s: float
    total_bytes_kb: float
    latency_min_ms: float
    latency_max_ms: float
    latency_mean_ms: float
    latency_median_ms: float
    latency_p90_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_stddev_ms: float
    apdex_score: float
    performance_grade: str
    status_codes: Dict[int, int]
    endpoint_breakdown: Dict[str, Dict[str, Any]]
    timeline_series: List[Dict[str, Any]]
    sla_compliance: Dict[str, bool]
    raw_metrics: List[RequestMetric] = field(default_factory=list)


def calculate_percentile(sorted_values: List[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[int(f)] * (c - k)
    d1 = sorted_values[int(c)] * (k - f)
    return d0 + d1


def determine_grade(apdex: float, error_rate: float, p95: float) -> str:
    if error_rate > 5.0 or apdex < 0.70 or p95 > 1000.0:
        return "F (Poor)"
    if error_rate > 2.0 or apdex < 0.80 or p95 > 500.0:
        return "C (Fair)"
    if error_rate > 0.5 or apdex < 0.90 or p95 > 300.0:
        return "B (Good)"
    if apdex >= 0.95 and p95 <= 150.0 and error_rate == 0.0:
        return "A+ (Excellent)"
    return "A (Very Good)"


class BenchmarkEngine:
    def __init__(self, base_url: str = "http://127.0.0.1:8800", transport: str = "auto"):
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        if self.transport == "auto":
            self.transport = self._detect_best_transport()

    def _detect_best_transport(self) -> str:
        """
        Detects if network HTTP requests succeed to base_url without proxy interference.
        If blocked or unavailable, falls back to direct in-process engine.
        """
        try:
            req = urllib.request.Request(f"{self.base_url}/contracts", headers={"User-Agent": "MizuhoVMS-PerfTester/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if 200 <= resp.status < 400:
                    return "http"
        except Exception:
            pass
        return "inprocess"

    def _execute_inprocess(self, target: Dict[str, Any]) -> RequestMetric:
        path = target.get("path", "/")
        method = target.get("method", "GET").upper()
        data = target.get("data")
        headers = target.get("headers", {})

        body_bytes = b""
        req_headers = dict(headers)
        if data is not None:
            if isinstance(data, dict):
                body_bytes = urllib.parse.urlencode(data).encode("utf-8")
                if "Content-Type" not in req_headers and "content-type" not in req_headers:
                    req_headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif isinstance(data, str):
                body_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                body_bytes = data

        start_time = time.perf_counter()
        status_code = 200
        bytes_rec = 0
        error_msg = None

        try:
            handler = DirectHandler(path=path, method=method, headers=req_headers, body=body_bytes)
            if method == "GET":
                handler.do_GET()
            elif method == "POST":
                handler.do_POST()
            elif method == "HEAD":
                handler.do_HEAD()
            else:
                handler.do_GET()

            status_code = handler.response_status
            bytes_rec = len(handler.wfile.getvalue())
            if status_code >= 400:
                error_msg = f"HTTP {status_code}"
        except Exception as e:
            status_code = 500
            error_msg = f"{type(e).__name__}: {str(e)}"

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return RequestMetric(
            endpoint=path,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            bytes_received=bytes_rec,
            error=error_msg
        )

    def _execute_http(self, target: Dict[str, Any], timeout: float = 10.0) -> RequestMetric:
        path = target.get("path", "/")
        method = target.get("method", "GET").upper()
        data = target.get("data")
        headers = target.get("headers", {})

        url = f"{self.base_url}{path}"
        req_headers = {"User-Agent": "MizuhoVMS-PerfTester/1.0"}
        req_headers.update(headers)

        encoded_data = None
        if data is not None:
            if isinstance(data, dict):
                encoded_data = urllib.parse.urlencode(data).encode("utf-8")
                if "Content-Type" not in req_headers:
                    req_headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif isinstance(data, str):
                encoded_data = data.encode("utf-8")
            elif isinstance(data, bytes):
                encoded_data = data

        req = urllib.request.Request(url, data=encoded_data, headers=req_headers, method=method)

        start_time = time.perf_counter()
        status_code = 0
        bytes_rec = 0
        error_msg = None

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status_code = response.getcode()
                content = response.read()
                bytes_rec = len(content)
        except urllib.error.HTTPError as e:
            status_code = e.code
            try:
                content = e.read()
                bytes_rec = len(content)
            except Exception:
                bytes_rec = 0
            if status_code >= 400:
                error_msg = f"HTTP {status_code}"
        except urllib.error.URLError as e:
            status_code = 0
            error_msg = f"ConnectionError: {e.reason}"
        except Exception as e:
            status_code = 0
            error_msg = f"{type(e).__name__}: {str(e)}"

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        return RequestMetric(
            endpoint=path,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            bytes_received=bytes_rec,
            error=error_msg
        )

    def _execute_request(self, target: Dict[str, Any], timeout: float = 10.0) -> RequestMetric:
        if self.transport == "inprocess":
            return self._execute_inprocess(target)
        return self._execute_http(target, timeout=timeout)

    def run_workload(
        self,
        scenario_name: str,
        target_generator: Callable[[], Dict[str, Any]],
        concurrency: int = 10,
        duration_sec: float = 15.0,
        on_progress: Optional[Callable[[float, int, float], None]] = None
    ) -> BenchmarkResult:
        metrics: List[RequestMetric] = []
        start_wall_time = time.time()
        end_wall_time = start_wall_time + duration_sec
        active = True

        def worker_loop():
            local_metrics = []
            while active and time.time() < end_wall_time:
                target = target_generator()
                metric = self._execute_request(target)
                local_metrics.append(metric)
            return local_metrics

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker_loop) for _ in range(concurrency)]

            # Progress polling loop
            last_report = time.time()
            while any(not f.done() for f in futures):
                time.sleep(0.5)
                now = time.time()
                if on_progress and (now - last_report) >= 1.0:
                    last_report = now
                    elapsed = now - start_wall_time
                    on_progress(elapsed, duration_sec, min(100.0, (elapsed / duration_sec) * 100.0))

            for f in as_completed(futures):
                metrics.extend(f.result())

        actual_duration = time.time() - start_wall_time
        return self._analyze_metrics(scenario_name, concurrency, actual_duration, metrics)

    def _analyze_metrics(
        self,
        scenario_name: str,
        concurrency: int,
        duration_sec: float,
        metrics: List[RequestMetric]
    ) -> BenchmarkResult:
        total_requests = len(metrics)
        if total_requests == 0:
            return BenchmarkResult(
                scenario_name=scenario_name,
                concurrency=concurrency,
                duration_sec=duration_sec,
                total_requests=0,
                successful_requests=0,
                failed_requests=0,
                error_rate_pct=100.0,
                rps=0.0,
                throughput_kb_s=0.0,
                total_bytes_kb=0.0,
                latency_min_ms=0.0,
                latency_max_ms=0.0,
                latency_mean_ms=0.0,
                latency_median_ms=0.0,
                latency_p90_ms=0.0,
                latency_p95_ms=0.0,
                latency_p99_ms=0.0,
                latency_stddev_ms=0.0,
                apdex_score=0.0,
                performance_grade="F (No data)",
                status_codes={},
                endpoint_breakdown={},
                timeline_series=[],
                sla_compliance={}
            )

        status_codes: Dict[int, int] = {}
        successful_requests = 0
        failed_requests = 0
        total_bytes = 0

        endpoint_map: Dict[str, List[RequestMetric]] = {}
        latencies = []
        satisfied_count = 0
        tolerating_count = 0

        target_t = SLA_THRESHOLDS["apdex_target_ms"]
        tolerating_t = SLA_THRESHOLDS["apdex_tolerating_ms"]

        for m in metrics:
            status_codes[m.status_code] = status_codes.get(m.status_code, 0) + 1
            total_bytes += m.bytes_received
            latencies.append(m.latency_ms)

            # Successful: standard HTTP 2xx or 3xx redirects
            if 200 <= m.status_code < 400:
                successful_requests += 1
            else:
                failed_requests += 1

            # Apdex counting
            if m.status_code < 400:
                if m.latency_ms <= target_t:
                    satisfied_count += 1
                elif m.latency_ms <= tolerating_t:
                    tolerating_count += 1

            endpoint_map.setdefault(m.endpoint, []).append(m)

        latencies.sort()
        lat_min = latencies[0]
        lat_max = latencies[-1]
        lat_mean = sum(latencies) / total_requests
        lat_median = calculate_percentile(latencies, 50.0)
        lat_p90 = calculate_percentile(latencies, 90.0)
        lat_p95 = calculate_percentile(latencies, 95.0)
        lat_p99 = calculate_percentile(latencies, 99.0)

        variance = sum((x - lat_mean) ** 2 for x in latencies) / total_requests
        lat_stddev = math.sqrt(variance)

        rps = total_requests / duration_sec if duration_sec > 0 else 0.0
        total_bytes_kb = total_bytes / 1024.0
        throughput_kb_s = total_bytes_kb / duration_sec if duration_sec > 0 else 0.0
        error_rate_pct = (failed_requests / total_requests) * 100.0

        apdex_score = (satisfied_count + (tolerating_count * 0.5)) / total_requests if total_requests > 0 else 0.0
        grade = determine_grade(apdex_score, error_rate_pct, lat_p95)

        # Endpoint Breakdown
        endpoint_breakdown = {}
        for ep, ep_metrics in endpoint_map.items():
            ep_lats = sorted(m.latency_ms for m in ep_metrics)
            ep_errors = sum(1 for m in ep_metrics if m.status_code >= 400 or m.status_code == 0)
            ep_total = len(ep_metrics)
            endpoint_breakdown[ep] = {
                "count": ep_total,
                "errors": ep_errors,
                "error_rate_pct": round((ep_errors / ep_total) * 100.0, 1),
                "rps": round(ep_total / duration_sec, 1) if duration_sec > 0 else 0.0,
                "min_ms": round(ep_lats[0], 1),
                "mean_ms": round(sum(ep_lats) / ep_total, 1),
                "median_ms": round(calculate_percentile(ep_lats, 50.0), 1),
                "p95_ms": round(calculate_percentile(ep_lats, 95.0), 1),
                "p99_ms": round(calculate_percentile(ep_lats, 99.0), 1),
                "max_ms": round(ep_lats[-1], 1)
            }

        # Timeline generation (second-by-second bucket aggregation)
        timeline_buckets: Dict[int, List[float]] = {}
        min_ts = min(m.timestamp for m in metrics)
        for m in metrics:
            sec_idx = int(m.timestamp - min_ts)
            timeline_buckets.setdefault(sec_idx, []).append(m.latency_ms)

        timeline_series = []
        for sec in sorted(timeline_buckets.keys()):
            bucket = sorted(timeline_buckets[sec])
            timeline_series.append({
                "second": sec,
                "requests": len(bucket),
                "mean_ms": round(sum(bucket) / len(bucket), 1),
                "p95_ms": round(calculate_percentile(bucket, 95.0), 1)
            })

        # SLA Compliance checks
        sla_compliance = {
            "p50_latency": lat_median <= SLA_THRESHOLDS["p50_latency_ms"],
            "p95_latency": lat_p95 <= SLA_THRESHOLDS["p95_latency_ms"],
            "p99_latency": lat_p99 <= SLA_THRESHOLDS["p99_latency_ms"],
            "error_rate": error_rate_pct <= SLA_THRESHOLDS["max_error_rate_pct"],
            "min_rps": rps >= SLA_THRESHOLDS["min_rps"],
            "apdex_score": apdex_score >= SLA_THRESHOLDS["min_apdex_score"],
        }

        return BenchmarkResult(
            scenario_name=scenario_name,
            concurrency=concurrency,
            duration_sec=round(duration_sec, 2),
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            error_rate_pct=round(error_rate_pct, 2),
            rps=round(rps, 1),
            throughput_kb_s=round(throughput_kb_s, 2),
            total_bytes_kb=round(total_bytes_kb, 1),
            latency_min_ms=round(lat_min, 1),
            latency_max_ms=round(lat_max, 1),
            latency_mean_ms=round(lat_mean, 1),
            latency_median_ms=round(lat_median, 1),
            latency_p90_ms=round(lat_p90, 1),
            latency_p95_ms=round(lat_p95, 1),
            latency_p99_ms=round(lat_p99, 1),
            latency_stddev_ms=round(lat_stddev, 1),
            apdex_score=round(apdex_score, 3),
            performance_grade=grade,
            status_codes=status_codes,
            endpoint_breakdown=endpoint_breakdown,
            timeline_series=timeline_series,
            sla_compliance=sla_compliance,
            raw_metrics=metrics
        )
