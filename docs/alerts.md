# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

Định nghĩa máy đọc được nằm ở [`config/alert_rules.yaml`](../config/alert_rules.yaml). Dashboard dựng bằng `python scripts/build_dashboard.py` (mở `data/dashboard.html`). Mọi bước điều tra đi theo **Metrics → Logs → Traces**.

## Alert 1

- Tên: `HighLatencyP95`
- Severity: P2 (trả lời trong giờ làm việc, xử lý trong 1 giờ)
- Duration: 5m
- Kênh thông báo: Slack `#day13-oncall`
- SLI/SLO liên quan: `fast_successful_requests` — request thành công với `latency_ms ≤ 3000`, mục tiêu 99.5%/28 ngày ([`config/slo.yaml`](../config/slo.yaml)).
- Điều kiện và thời gian duy trì: P95 của `latency_ms` trên các log `response_sent` trong cửa sổ 5 phút > 2000 ms, kéo dài liên tục 5 phút. Ngưỡng 2000 ms thấp hơn SLO 3000 ms để cảnh báo sớm trước khi đốt error budget.
- Ảnh hưởng tới người dùng: câu trả lời chậm rõ rệt; nếu vượt 3000 ms thì mỗi request tính là bad event của SLO.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** panel *Latency percentiles and TTFT* — P95/P99 tăng từ lúc nào? TTFT P95 có tăng theo không (TTFT không đổi mà latency tăng ⇒ chậm trước khi gọi LLM, thường là retrieval).
  2. **Logs:** lọc `data/logs.jsonl` các dòng `response_sent` có `latency_ms > 2000` trong khoảng đó, lấy `correlation_id`:
     `Select-String -Path data/logs.jsonl -Pattern '"event": "response_sent"' | Where-Object { ($_.Line | ConvertFrom-Json).latency_ms -gt 2000 }`
  3. **Traces:** trên Langfuse lọc Metadata `correlation_id = <id>`, mở tab Timeline, so sánh độ dài span `retrieval` và `llm-generation`.
- Mitigation tạm thời: nếu `retrieval` chậm (ví dụ incident `rag_slow`), tắt nguồn gây chậm (`python scripts/inject_incident.py --scenario rag_slow --disable`), hoặc giảm timeout retrieval/trả lời bằng fallback không cần docs; nếu `llm-generation` chậm, chuyển sang model nhỏ hơn hoặc giảm `max_tokens`. Nếu vừa đổi prompt, rollback label `production` về version trước.
- Owner: dang-huu-tam

## Alert 2

- Tên: `HighErrorRate`
- Severity: P1 (page ngay, xử lý trong 15 phút)
- Duration: 5m
- Kênh thông báo: Slack `#day13-oncall`
- SLI/SLO liên quan: `fast_successful_requests` (mỗi `request_failed` là bad event) và guardrail `error_rate_pct_max: 2`.
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received) × 100` trong cửa sổ 5 phút > 2%, kéo dài liên tục 5 phút.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 thay vì câu trả lời.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** panel *Error rate and retrieval success* — xem bảng `error_type` nào chiếm đa số và *Retrieval success* có giảm dưới 90% không.
  2. **Logs:** lọc `"event": "request_failed"`, đọc `error_type`, `tool_name`, `tool_success` và `payload.detail` (đã scrub PII), lấy `correlation_id`:
     `Select-String -Path data/logs.jsonl -Pattern '"request_failed"'`
  3. **Traces:** mở trace cùng `correlation_id`; observation lỗi được Langfuse đánh level `ERROR` — kiểm tra lỗi nằm ở `retrieval` (vector store) hay `llm-generation`.
- Mitigation tạm thời: nếu lỗi `RuntimeError: Vector store timeout` từ retrieval (incident `tool_fail`), tắt incident/khôi phục vector store; trong lúc chờ có thể trả lời bằng fallback không dùng docs để người dùng không nhận 500. Nếu lỗi bắt đầu ngay sau deploy hoặc đổi prompt, rollback.
- Owner: dang-huu-tam

## Alert 3

- Tên: `CostPerRequestSpike`
- Severity: P3 (ticket, xử lý trong ngày làm việc)
- Duration: 15m
- Kênh thông báo: Slack `#day13-oncall`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5` trong [`config/slo.yaml`](../config/slo.yaml); panel *Cost over time* và *Input and output tokens*.
- Điều kiện và thời gian duy trì: trung bình `cost_usd` trên mỗi `response_sent` trong cửa sổ 15 phút > 0.005 USD (≈ 2.5 lần baseline ~0.002 USD), kéo dài 15 phút. Đo theo từng request nên vẫn bắt được khi traffic không tăng.
- Ảnh hưởng tới người dùng: chưa ảnh hưởng trực tiếp, nhưng đốt ngân sách nhanh; câu trả lời dài bất thường cũng làm latency tăng.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** panel *Cost over time* và *Input and output tokens* — cost tăng do `tokens_out` (câu trả lời dài) hay `tokens_in` (prompt/docs dài)? Panel *Request traffic* có tăng không.
  2. **Logs:** so sánh `tokens_in`, `tokens_out`, `cost_usd` của các `response_sent` trước/sau thời điểm tăng; lấy `correlation_id` của request đắt nhất.
  3. **Traces:** mở generation của trace đó — xem usage input/output, cost và `prompt_version` (prompt mới có làm câu trả lời dài hơn không).
- Mitigation tạm thời: giới hạn `max_tokens` cho output, rollback prompt `production` nếu version mới gây dài dòng, chuyển feature ít quan trọng sang model rẻ hơn; tắt incident `cost_spike` nếu đang practice.
- Owner: dang-huu-tam
