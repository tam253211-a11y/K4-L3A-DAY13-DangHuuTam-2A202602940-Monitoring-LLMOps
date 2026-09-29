# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Đặng Hữu Tâm
- **MSSV:** 2A202602940
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/tam253211-a11y/K4-L3A-DAY13-DangHuuTam-2A202602940-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602940`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (thiếu required fields, 0 correlation ID, thiếu enrichment) | 100/100 (sau CP1) | 10 correlation ID riêng biệt, 0 record thiếu field/enrichment |
| `validate_dashboard.py` | 6/6 panel | | |
| `pytest` | 22 passed | 26 passed (sau CP1) | Thêm 4 test PII: CCCD, thẻ, hộ chiếu, nhiều PII trong một câu |
| Số traces hợp lệ | 10 traces, chỉ có root `lab-agent-run` (chưa có child observation) | | |
| Số PII leak | 0 (theo `validate_logs.py`) | 0 (sau CP1) | Baseline 0 chỉ nhờ `summarize_text`; nay scrubber chạy trên toàn bộ payload trước khi ghi file |
| Latency P95 / TTFT P95 | | | |
| Retrieval success rate | | | |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` ([app/middleware.py](../app/middleware.py)) gọi `clear_contextvars()` đầu mỗi request để không rò context của request trước. Nếu client gửi header `x-request-id` thì dùng lại, nếu không thì sinh `req-<8 ký tự hex>` từ `uuid4`. ID được `bind_contextvars` vào structlog (mọi log trong request tự có `correlation_id`), lưu vào `request.state` để truyền xuống `LabAgent.run` và trace metadata, rồi trả lại qua header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** Trong [app/main.py](../app/main.py), trước log `request_received` tôi bind `user_id_hash` (SHA-256 cắt 12 ký tự, không log `user_id` thô), `session_id`, `feature`, `model`, `env`. Ngoài ra mỗi dòng có `ts`, `level`, `service`, `event`; log `response_sent` thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** Processor `scrub_event` được đăng ký trong [app/logging_config.py](../app/logging_config.py) **trước** `JsonlFileProcessor` và `JSONRenderer`; structlog chạy processor theo thứ tự nên dữ liệu được che trước khi serialize hoặc ghi file. [app/pii.py](../app/pii.py) có pattern cho email, thẻ thanh toán, CCCD, điện thoại Việt Nam và hộ chiếu; `credit_card` được đặt trước `cccd`/`phone_vn` để số thẻ bị che trọn một lần thay vì bị pattern ngắn hơn cắt một phần.
- **Cách kiểm chứng kết quả:** Đổi tên log baseline thành `data/logs-baseline.jsonl`, khởi động lại API, chạy `load_test.py`: `validate_logs.py` đạt 100/100, 10 correlation ID, 0 PII leak. `pytest` 26 passed (có test cho từng loại PII và test chống cắt nhầm số thẻ). Log thực tế của sample `u01`, `u05`, `u09` chứa `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CREDIT_CARD]`. Gọi `curl -i POST /chat` trả header `x-request-id: req-7ca96e23` và `x-response-time-ms: 395.9`. Evidence: `evidence/02-log-validator.png`, `evidence/04-structured-log.png`, `evidence/05-pii-redaction.png`.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:**
- **Cấu trúc root/retrieval/generation observations:**
- **Cách nối trace với log:**
- **Prompt name:**
- **Version/label baseline:**
- **Version/label candidate:**
- **Trace ID của mỗi version:**
- **Cách promote và rollback `production`:**

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:**
- **SLO và lý do chọn:**
- **Cách tính error budget:**
- **Ba alert và runbook tương ứng:**

## 7. Điều tra challenge

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
