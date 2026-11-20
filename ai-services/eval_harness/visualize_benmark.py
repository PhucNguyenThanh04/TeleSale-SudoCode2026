
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from eval_harness.dashboard_data import load_run, metric_rows, scenario_outcomes

RESULTS = Path(__file__).resolve().parent / "results"


def _rows_for_scenario(run: dict, scenario: str) -> list[dict]:
    trace_name = run["index"].get("traces", {}).get("full")
    if not trace_name:
        return []
    path = run["path"] / trace_name
    return [row for row in (json.loads(line) for line in path.read_text(
        encoding="utf-8").splitlines() if line.strip())
            if scenario == "Tất cả" or row.get("scenario_id") == scenario]


def main() -> None:
    import plotly.graph_objects as go
    import streamlit as st

    st.set_page_config(page_title="TeleSale · BTC Text Eval", layout="wide")
    st.title("Đánh giá hội thoại text · BTC")
    options = []
    for path in sorted(RESULTS.iterdir(), reverse=True) if RESULTS.exists() else []:
        if (path / "run.json").is_file():
            try:
                load_run(path)
            except (ValueError, KeyError, OSError, json.JSONDecodeError):
                continue
            options.append(path)
    if not options:
        st.info("Chưa có run hợp lệ. Chạy `python -m eval_harness.run_official --btc-root ...`.")
        return
    selected = st.sidebar.selectbox("Run", options, format_func=lambda path: path.name)
    run = load_run(selected)
    run["index"] = json.loads((selected / "run.json").read_text(encoding="utf-8"))
    score = run["score"]
    system = score["system"]
    all_traces = _rows_for_scenario(run, "Tất cả")
    groups = run["index"].get("scenario_groups") or {
        row["scenario_id"]: "Khác" for row in all_traces}
    group_filter = st.sidebar.selectbox("Nhóm kịch bản", ["Tất cả", *sorted(set(groups.values()))])
    group_value = None if group_filter == "Tất cả" else group_filter
    outcomes = scenario_outcomes(score, groups, group_value)
    selected_scenario = st.sidebar.selectbox(
        "Kịch bản", ["Tất cả", *[row["scenario"] for row in outcomes]])
    st.caption(f"{run['scenarios']} kịch bản · {run['turns']} lượt thoại · "
               f"{run['manifests']['full'].get('model_id', 'model chưa ghi')}")
    rates = metric_rows(score)
    metric_filter = st.sidebar.selectbox("Chỉ số", ["Tất cả", *[row["label"] for row in rates]])
    columns = st.columns(4)
    for index, row in enumerate(rates):
        value = f"{row['value']:g}{row['unit']}" if row["value"] is not None else "Chưa đo"
        columns[index % 4].metric(row["label"], value)
        if row["denominator"] is not None:
            columns[index % 4].caption(
                f"{row['numerator'] if row['numerator'] is not None else '—'} / {row['denominator']}")
    st.subheader("Tỷ lệ và ngưỡng BTC")
    measured = [row for row in rates if row["status"] == "measured" and row["unit"] == "%"
                and metric_filter in ("Tất cả", row["label"])]
    if measured:
        fig = go.Figure(go.Bar(x=[row["label"] for row in measured],
                               y=[row["value"] for row in measured],
                               text=[f"{row['value']:g}%" for row in measured],
                               marker_color="#2563eb"))
        fig.update_layout(yaxis_title="%", yaxis_range=[0, 100], height=380)
        st.plotly_chart(fig, use_container_width=True)
        for row in measured:
            if row["target"] is not None:
                st.caption(f"{row['label']}: ngưỡng BTC {row['target']}%")
    else:
        st.info("Chưa có tỷ lệ với mẫu số hợp lệ.")
    failures = (system.get("task_success_rate") or {}).get("failures") or []
    st.subheader("Kết quả theo kịch bản")
    if outcomes:
        fig = go.Figure(go.Bar(x=[row["scenario"] for row in outcomes],
                               y=[1] * len(outcomes),
                               marker_color=["#16a34a" if row["status"] == "pass"
                                             else "#dc2626" for row in outcomes],
                               text=[row["status"].upper() for row in outcomes]))
        fig.update_layout(yaxis_title="Kết quả", yaxis_visible=False, height=320)
        st.plotly_chart(fig, use_container_width=True)
    visible = [row for row in failures
               if (selected_scenario == "Tất cả" or row.get("scenario") == selected_scenario)
               and (group_value is None or groups.get(row.get("scenario")) == group_value)]
    if visible:
        labels = [f"{row.get('scenario')} · {row.get('call')}" for row in visible]
        fig = go.Figure(go.Bar(x=labels, y=[len(row.get("reasons", [])) for row in visible],
                               marker_color="#ef4444"))
        fig.update_layout(yaxis_title="Số lý do thất bại", height=360)
        st.plotly_chart(fig, use_container_width=True)
        counts = Counter(reason for row in visible for reason in row.get("reasons", []))
        if counts:
            fig = go.Figure(go.Bar(x=list(counts), y=list(counts.values()),
                                   marker_color="#f59e0b"))
            fig.update_layout(yaxis_title="Số lần", height=320)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.success("Không có ca thất bại trong bộ lọc.")
    latency = system.get("latency") or {}
    st.subheader("Độ trễ")
    st.caption(latency.get("warning") or "TTFT dùng tổng thời gian vì API hiện không streaming.")
    for key, label in (("total", "Tổng"), ("ttft", "TTFT (ước tính)"),
                       ("call_brief", "Call Brief")):
        block = latency.get(key) or {}
        st.write(f"{label}: n={block.get('n', 0)} · p50={block.get('p50_ms', '—')} ms · "
                 f"p95={block.get('p95_ms', '—')} ms")
    traces = [row for row in all_traces
              if (selected_scenario == "Tất cả" or row.get("scenario_id") == selected_scenario)
              and (group_value is None or groups.get(row.get("scenario_id")) == group_value)]
    samples = [row["latency"]["total_ms"] for row in traces
               if isinstance(row.get("latency", {}).get("total_ms"), (int, float))]
    if samples:
        fig = go.Figure(go.Histogram(x=samples, nbinsx=min(25, max(5, len(samples) // 4)),
                                     marker_color="#14b8a6"))
        p95 = (latency.get("total") or {}).get("p95_ms")
        if isinstance(p95, (int, float)):
            fig.add_vline(x=p95, line_dash="dash", line_color="#dc2626",
                          annotation_text="p95 BTC")
        fig.update_layout(xaxis_title="Tổng thời gian (ms)", yaxis_title="Số lượt")
        st.plotly_chart(fig, use_container_width=True)
    st.subheader("Bộ nhớ và truy hồi chính sách")
    operational = st.columns(3)
    operational[0].metric("Lượt trung bình / cuộc gọi",
                          system.get("avg_turns_per_call") if system.get("avg_turns_per_call") is not None
                          else "Chưa đo")
    close = system.get("calls_to_close") or {}
    operational[1].metric("Cuộc gọi để chốt", close.get("value")
                          if close.get("value") is not None else "Chưa đo")
    operational[1].caption(f"{close.get('n_closed', 0)} / {close.get('n_scenarios', 0)} ca chốt")
    operational[2].metric("Kiểm tra bộ nhớ", len(system.get("memory_checks") or []))
    memory = [row for row in rates if row["key"] in {"rqr", "ccr", "rqr_reduction"}]
    if any(row["value"] is not None for row in memory):
        fig = go.Figure(go.Bar(x=[row["label"] for row in memory if row["value"] is not None],
                               y=[row["value"] for row in memory if row["value"] is not None]))
        fig.update_layout(yaxis_title="%")
        st.plotly_chart(fig, use_container_width=True)
    rag = run.get("rag") or {}
    retrieval = rag.get("retrieval_metrics") or {}
    rag_rates = {key: value for key, value in retrieval.items()
                 if isinstance(value, (int, float))}
    if rag_rates:
        fig = go.Figure(go.Bar(x=list(rag_rates), y=list(rag_rates.values()),
                               marker_color="#8b5cf6"))
        fig.update_layout(yaxis_title="%", yaxis_range=[0, 100])
        st.plotly_chart(fig, use_container_width=True)
    tool_counts = Counter(call.get("name", "khác") for row in traces
                          for call in row.get("tool_calls") or [])
    if tool_counts:
        st.subheader("Sử dụng công cụ")
        fig = go.Figure(go.Bar(x=list(tool_counts), y=list(tool_counts.values()),
                               marker_color="#0ea5e9"))
        fig.update_layout(yaxis_title="Số lần gọi")
        st.plotly_chart(fig, use_container_width=True)
    st.caption("Abstention câu trả lời, version accuracy, chi phí và LLM judge: chưa đo.")
    st.subheader("Chẩn đoán lượt thoại")
    st.dataframe([{"scenario": row.get("scenario_id"), "call": row.get("call"),
                   "turn": row.get("turn"), "total_ms": row.get("latency", {}).get("total_ms"),
                   "tool_calls": len(row.get("tool_calls") or []),
                   "memory_error": row.get("memory_error")}
                  for row in traces], use_container_width=True)


if __name__ == "__main__":
    main()
