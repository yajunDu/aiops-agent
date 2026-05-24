"""Prometheus 客户端 - 拉取指标并保存为 parquet"""
import requests
import pandas as pd
from datetime import datetime, timedelta


class PromClient:
    def __init__(self, url="http://localhost:30090"):
        self.url = url

    def query_range(self, query, start_ts, end_ts, step="15s"):
        """范围查询，返回 DataFrame"""
        r = requests.get(
            f"{self.url}/api/v1/query_range",
            params={"query": query, "start": start_ts, "end": end_ts, "step": step},
            timeout=30,
        )
        if r.status_code != 200:
            return pd.DataFrame()
        data = r.json().get("data", {}).get("result", [])
        rows = []
        for series in data:
            metric = series.get("metric", {})
            for ts, val in series.get("values", []):
                row = {**metric, "timestamp": float(ts), "value": float(val)}
                rows.append(row)
        return pd.DataFrame(rows)

    def collect_window(self, start_ts, end_ts, ns="train-ticket"):
        """采集一个时间窗口内的所有关键指标"""
        queries = {
            "cpu": f'rate(container_cpu_usage_seconds_total{{namespace="{ns}",container!=""}}[1m])',
            "memory": f'container_memory_usage_bytes{{namespace="{ns}",container!=""}}',
            "net_rx": f'rate(container_network_receive_bytes_total{{namespace="{ns}"}}[1m])',
            "net_tx": f'rate(container_network_transmit_bytes_total{{namespace="{ns}"}}[1m])',
            "net_rx_drop": f'rate(container_network_receive_packets_dropped_total{{namespace="{ns}"}}[1m])',
            "net_tx_drop": f'rate(container_network_transmit_packets_dropped_total{{namespace="{ns}"}}[1m])',
            "cpu_throttle": f'rate(container_cpu_cfs_throttled_periods_total{{namespace="{ns}",container!=""}}[1m])',
            "restart": f'kube_pod_container_status_restarts_total{{namespace="{ns}"}}',
        }
        frames = []
        for metric_name, q in queries.items():
            df = self.query_range(q, start_ts, end_ts, step="15s")
            if df.empty:
                continue
            df["metric_name"] = metric_name
            frames.append(df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    # 自测
    c = PromClient()
    now = datetime.now().timestamp()
    df = c.collect_window(now - 300, now)
    print(f"采集 5 分钟数据: {len(df)} 行")
    print(df.head(3))
    print(f"\n指标分布:\n{df['metric_name'].value_counts()}")
