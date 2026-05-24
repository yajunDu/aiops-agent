import os
"""12.3-B Neo4j 拓扑查询工具（带护栏 + warning 抑制）"""
import json
import re
import warnings
import logging
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PWD = os.getenv("NEO4J_PWD", "aiops2026")

# 抑制 Neo4j warnings
warnings.filterwarnings("ignore")
logging.getLogger("neo4j").setLevel(logging.ERROR)

FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|REMOVE|SET|DROP|DETACH|CALL|LOAD|USING)\b",
    re.IGNORECASE,
)


class GraphTool:
    def __init__(self):
        try:
            self._driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD),
                notifications_min_severity="OFF",
                warn_notification_severity="OFF",
            )
        except TypeError:
            # 旧版 neo4j driver 不支持 notifications 参数
            self._driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD))

    def close(self):
        self._driver.close()

    def query(self, cypher: str, max_rows: int = 30) -> str:
        if FORBIDDEN.search(cypher):
            return json.dumps({"error": "Cypher 包含禁用关键字（仅允许只读查询）"})
        try:
            with self._driver.session() as s:
                result = s.run(cypher)
                rows = []
                for i, rec in enumerate(result):
                    if i >= max_rows:
                        break
                    row = {}
                    for k in rec.keys():
                        v = rec[k]
                        if hasattr(v, "items"):
                            row[k] = dict(v.items())
                        else:
                            row[k] = v
                    rows.append(row)
                return json.dumps({
                    "rows": rows, "row_count": len(rows),
                    "truncated": len(rows) >= max_rows,
                }, default=str, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})


_TOOL = None
def get_tool():
    global _TOOL
    if _TOOL is None:
        _TOOL = GraphTool()
    return _TOOL


def query_graph_topology(cypher: str) -> str:
    return get_tool().query(cypher)


if __name__ == "__main__":
    print(query_graph_topology("MATCH (s:Service) RETURN s.name LIMIT 3"))
