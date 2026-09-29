# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Đặng Hữu Tâm
- **MSSV:** 2A202602940
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/tam253211-a11y/K4-L3A-DAY13-DangHuuTam-2A202602940-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602940`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.txt` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08a-trace-by-correlation-id.png` (lọc theo `correlation_id`), `evidence/08b-trace-metadata.png` (metadata đầy đủ); token/cost xem `evidence/07-trace-waterfall.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10a-prompt-promote.png`, `evidence/10b-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (thiếu required fields, 0 correlation ID, thiếu enrichment) | 100/100 (sau CP1) | 10 correlation ID riêng biệt, 0 record thiếu field/enrichment |
| `validate_dashboard.py` | 6/6 panel | 6/6 panel | Contract giữ nguyên; dashboard runtime dựng từ chính contract này |
| `pytest` | 22 passed | 30 passed (sau CP2) | +4 test PII (CCCD, thẻ, hộ chiếu, nhiều PII) và +4 test tổng hợp dashboard |
| Số traces hợp lệ | 10 traces, chỉ có root `lab-agent-run` (chưa có child observation) | 15 traces trong 1 giờ gần nhất, mỗi trace có `retrieval` + `llm-generation` | Waterfall cho thấy LLM chiếm ~151/152 ms, retrieval ~0 ms |
| Số PII leak | 0 (theo `validate_logs.py`) | 0 (sau CP1) | Baseline 0 chỉ nhờ `summarize_text`; nay scrubber chạy trên toàn bộ payload trước khi ghi file |
| Latency P95 / TTFT P95 | Chưa đo được (log thiếu field) | 154 ms / 50 ms (205 request, 60 phút) | P99 2,016 ms: đuôi chậm do chờ tải prompt từ Langfuse |
| Retrieval success rate | Chưa đo được | 100% (205/205) | Chưa bật incident; error rate 0% |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` ([app/middleware.py](../app/middleware.py)) gọi `clear_contextvars()` đầu mỗi request để không rò context của request trước. Nếu client gửi header `x-request-id` thì dùng lại, nếu không thì sinh `req-<8 ký tự hex>` từ `uuid4`. ID được `bind_contextvars` vào structlog (mọi log trong request tự có `correlation_id`), lưu vào `request.state` để truyền xuống `LabAgent.run` và trace metadata, rồi trả lại qua header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** Trong [app/main.py](../app/main.py), trước log `request_received` tôi bind `user_id_hash` (SHA-256 cắt 12 ký tự, không log `user_id` thô), `session_id`, `feature`, `model`, `env`. Ngoài ra mỗi dòng có `ts`, `level`, `service`, `event`; log `response_sent` thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** Processor `scrub_event` được đăng ký trong [app/logging_config.py](../app/logging_config.py) **trước** `JsonlFileProcessor` và `JSONRenderer`; structlog chạy processor theo thứ tự nên dữ liệu được che trước khi serialize hoặc ghi file. [app/pii.py](../app/pii.py) có pattern cho email, thẻ thanh toán, CCCD, điện thoại Việt Nam và hộ chiếu; `credit_card` được đặt trước `cccd`/`phone_vn` để số thẻ bị che trọn một lần thay vì bị pattern ngắn hơn cắt một phần.
- **Cách kiểm chứng kết quả:** Đổi tên log baseline thành `data/logs-baseline.jsonl`, khởi động lại API, chạy `load_test.py`: `validate_logs.py` đạt 100/100, 10 correlation ID, 0 PII leak. `pytest` 26 passed (có test cho từng loại PII và test chống cắt nhầm số thẻ). Log thực tế của sample `u01`, `u05`, `u09` chứa `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CREDIT_CARD]`. Gọi `curl -i POST /chat` trả header `x-request-id: req-7ca96e23` và `x-response-time-ms: 395.9`. Evidence: `evidence/02-log-validator.png`, `evidence/04-structured-log.png`, `evidence/05-pii-redaction.png`.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** Tôi tự tạo project Langfuse Cloud `day13-k4-l3a-2A202602940` với key pair riêng trong `.env` (không commit), rồi tự chạy `load_test.py` và các request prompt. Trace list trong project này có các trace `day13-agent-request` đúng thời điểm tôi chạy workload, và `correlation_id` trong trace metadata trùng với `data/logs.jsonl` của máy tôi.
- **Cấu trúc root/retrieval/generation observations:** Root `lab-agent-run` (type `agent`, [app/agent.py](../app/agent.py)) có 2 con: `retrieval` (type `retriever`, method `_retrieve`, ghi `doc_count`, `retrieval_ms`, `query_preview` đã scrub) và `llm-generation` (type `generation`, method `_generate`, ghi `model`, liên kết `prompt` Langfuse, `usage_details` input/output, `cost_details` input/output/total, `completion_start_time` để Langfuse hiện TTFT). Cả 3 observation đều `capture_input=False`/`capture_output=False`; input/output chỉ là preview đã qua `scrub_text`, không gửi raw prompt/answer.
- **Cách nối trace với log:** `propagate_attributes(metadata={"correlation_id": ...})` gắn `correlation_id` từ middleware vào mọi observation của trace. Ví dụ log `response_sent` có `correlation_id=req-a71ae44d` ↔ trace `97e83c75bdf1d8e9b3d700672b14753c` có metadata `correlation_id=req-a71ae44d`. Trace cũng có `userId` = `user_id_hash` (không phải user_id thô), `sessionId`, tags `feature`/`model` và `environment=dev`.
- **Prompt name:** `day13-chat` (text prompt, giữ 3 biến `{{feature}}`, `{{docs}}`, `{{message}}`).
- **Version/label baseline:** v1, labels `baseline` + `production` (template gốc).
- **Version/label candidate:** v2, label `candidate` (thêm dòng `Answer in at most 3 short bullet points.`).
- **Trace ID của mỗi version:** Cùng input `"Explain the monitoring policy"` (user `u01`, feature `qa`):
  - `baseline` → trace `97e83c75bdf1d8e9b3d700672b14753c`, `correlation_id=req-a71ae44d`, `prompt_version=1`, `prompt_source=langfuse`, `tokens_in=36`.
  - `candidate` → trace `834add548afc70d2198d5d53e5b0ff65`, `correlation_id=req-fe69eb2b`, `prompt_version=2`, `prompt_source=langfuse`, `tokens_in=46` (tăng 10 token đúng bằng dòng hướng dẫn thêm ở v2).
- **Cách promote và rollback `production`:** App luôn chạy với `LANGFUSE_PROMPT_LABEL=production`, nên việc đổi version chỉ là di chuyển label trên Langfuse, không cần sửa code hay deploy lại.
  1. **Promote:** gắn label `production` cho v2 (Langfuse tự gỡ khỏi v1) — `evidence/10a-prompt-promote.png`. Request cùng input sau đó → trace `1ea8b8b6fb1c44cf67a6834ab986fa44`, `req-6567c176`, `prompt_label=production`, `prompt_version=2`.
  2. **Rollback:** gắn lại `production` cho v1 — `evidence/10b-prompt-rollback.png`. Request đầu tiên sau rollback (`req-8c55bebf`, trace `11084b54a0b8d5f9875e3d091a605a59`) vẫn trả v2 vì SDK cache prompt 60 giây và khi hết hạn thì trả bản cũ trong lúc tải bản mới ở nền; request kế tiếp (`req-55dd7edb`, trace `47a96d4e3e031293e6ca0aa0ff55a8e7`) đã dùng `prompt_version=1`.
  - **Bài học vận hành:** rollback prompt có độ trễ tối đa bằng `cache_ttl_seconds` (60s) cộng một request; khi sự cố nghiêm trọng cần rollback tức thì thì phải restart API hoặc giảm TTL.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** Tôi viết [scripts/build_dashboard.py](../scripts/build_dashboard.py) đọc `data/logs.jsonl` (nguồn chuẩn) và [config/dashboard.yaml](../config/dashboard.yaml), sinh trang HTML tự chứa `data/dashboard.html` (không cần cài thêm thư viện; `--watch` rebuild mỗi 30 s, trang tự refresh 30 s). Tên panel, đơn vị và threshold đọc thẳng từ YAML nên không lệch contract. Sáu panel, time range 60 phút, bucket 1 phút:
  1. *Latency percentiles and TTFT* (ms): P50/P95/P99 latency + TTFT P95 theo phút, đường SLO P95 ≤ 3000 ms.
  2. *Request traffic* (requests_per_minute): số `request_received` mỗi phút, đường tối thiểu ≥ 1 req/min.
  3. *Error rate and retrieval success* (percent): error rate theo phút với đường 2%, bảng breakdown `error_type`, tile retrieval success (`tool_success`).
  4. *Cost over time* (usd): cost mỗi phút + thanh tổng cost so với ngân sách 2.5 USD.
  5. *Input and output tokens* (tokens): tokens_in/tokens_out theo phút + tổng từng field so với giới hạn 50,000.
  6. *Quality proxy* (score_0_to_1): mean `quality_score` theo phút, đường ≥ 0.75.
  Mỗi panel có badge ✓/✗ so với threshold của contract. Logic tổng hợp có test ở [tests/test_build_dashboard.py](../tests/test_build_dashboard.py). Evidence: `evidence/11-dashboard-overview.png`.
- **SLO và lý do chọn:** [config/slo.yaml](../config/slo.yaml) — SLO `fast_successful_requests`: tỉ lệ request có `response_sent` với `latency_ms ≤ 3000` trên tổng `request_received`, mục tiêu **99.5% trong 28 ngày**. Tôi giữ ngưỡng sau khi đo baseline (60 request, traffic đều): P50 152 ms, P95 156 ms, P99 2426 ms, TTFT P95 50 ms, 100% request ≤ 3000 ms. 3000 ms đủ xa P95 để không báo động giả nhưng vẫn bắt được đuôi chậm thật: P99 2426 ms là các request phải chờ tải prompt từ Langfuse (timeout 2 s), và `rag_slow` (+2500 ms) đẩy request sát ngưỡng. Request lỗi không có `response_sent` nên tự động là bad event — một SLI đo cả "nhanh" lẫn "thành công".
- **Cách tính error budget:** Budget = (1 − 0.995) × tổng request trong 28 ngày = 0.5%. Ví dụ ở 1 req/phút: 40,320 request/28 ngày → được phép 201 bad event; quy ra thời gian ≈ 201.6 phút (~3 giờ 22 phút) sập hoàn toàn. Burn rate = tỉ lệ bad hiện tại / 0.5%; error rate 2% (ngưỡng alert) là burn rate 4× → hết budget sau 7 ngày. Chính sách: còn > 50% budget thì deploy/đổi prompt bình thường; < 25% chỉ deploy bản sửa lỗi; hết budget thì đóng băng thay đổi.
- **Ba alert và runbook tương ứng:** [config/alert_rules.yaml](../config/alert_rules.yaml) + runbook [docs/alerts.md](../docs/alerts.md), đều symptom-based, gửi Slack `#day13-oncall`, owner `dang-huu-tam`:
  1. `HighLatencyP95` — P2, P95 latency > 2000 ms trong 5m (cảnh báo sớm dưới SLO 3000 ms; bắt `rag_slow`).
  2. `HighErrorRate` — P1, error rate > 2% trong 5m (người dùng nhận HTTP 500; bắt `tool_fail`).
  3. `CostPerRequestSpike` — P3, cost trung bình/request > 0.005 USD (~2.5× baseline 0.00214) trong 15m (đo theo request nên bắt được cả khi traffic không đổi; bắt `cost_spike`).
  Mỗi runbook có 3 bước Metrics → Logs → Traces (panel nào, lệnh lọc log nào, span nào cần so sánh) và mitigation tạm thời (tắt nguồn lỗi, fallback, rollback prompt `production`).

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` (cohort K4, seed 1311, 5 query; file riêng do Lab Coach gửi, lưu tại `config/challenge.json`, đã `.gitignore`, không commit).
- **Khoảng thời gian điều tra:** 2026-09-29 16:37:08 – 16:38:45 (UTC+7). Inject incident lúc 16:37:08, chạy `load_test.py --challenge --concurrency 5` 16:37:10 – 16:37:26, tắt incident lúc 16:38:45 rồi chạy lại cùng workload để xác nhận hồi phục.
- **Triệu chứng từ metrics:** Panel *Latency percentiles and TTFT* (`evidence/12-incident-metric.png`): ở bucket phút 16:37, latency của feature `monitoring` nhảy lên **P50 2,654 ms, P95 4,947 ms** (vượt đường SLO 3,000 ms) so với baseline P50 152 ms / P95 156 ms; **TTFT P95 vẫn 50 ms**. Các panel khác bình thường: error rate 0%, retrieval success 100%, tokens/cost/quality không đổi (cost 0.0013–0.0024 USD/request, quality 0.8–0.9). Phía client, 5 request mất 13.5–16.2 s. Nhận xét: badge 60 phút vẫn "Within threshold" (P95 toàn cửa sổ 156 ms, P99 tăng 2,016 → 2,654 ms) vì 5/208 request bị pha loãng — đó là lý do alert `HighLatencyP95` dùng cửa sổ 5 phút. Kết luận bước 1: request chậm nhưng không lỗi, và TTFT không đổi ⇒ thời gian mất ở **trước** khi gọi LLM.
- **Log line và correlation ID liên quan:** Lọc `data/logs.jsonl` trong 16:37 (`evidence/13-incident-log.png`), chọn request tiêu biểu **`req-bd106a89`**:
  `{"service": "api", "latency_ms": 2654, "ttft_ms": 50, "tokens_in": 34, "tokens_out": 153, "cost_usd": 0.002397, "quality_score": 0.9, "tool_name": "retrieval", "tool_success": true, ..., "event": "response_sent", "correlation_id": "req-bd106a89", "feature": "monitoring", "model": "claude-sonnet-4-5", "ts": "2026-09-29T09:37:23.930999Z"}`
  Cả 5 request `req-40ea960e`, `req-5cc8f3b4`, `req-6c5b56a2`, `req-bd106a89`, `req-c724bbf8` đều `latency_ms` 2,653–4,947 với `ttft_ms` 50, `tool_success: true`. Ngay trước đó có log `{"service": "control", "payload": {"name": "rag_slow"}, "event": "incident_enabled", "ts": "2026-09-29T09:37:09.683725Z"}` và sau khi xử lý có `incident_disabled` lúc 09:38:45Z — khớp đúng khoảng sự cố.
- **Trace ID và span gây ảnh hưởng:** Trace **`2d8bef9f222eb0713d981a5f52c24b0a`** (metadata `correlation_id = req-bd106a89`, `evidence/14-incident-trace.png`): `lab-agent-run` 2.655 s = **`retrieval` 2.502 s** + `llm-generation` 0.152 s; không span nào level ERROR. So với baseline (trace `47a96d4e3e031293e6ca0aa0ff55a8e7`: retrieval ~0 ms, generation 151 ms), chỉ `retrieval` thay đổi. 4 trace còn lại của challenge đều có `retrieval` 2.501–2.502 s. Riêng `req-40ea960e` (trace `6987003491b9c34a907bb4ff18344f83`, 4.948 s) có thêm ~2.3 s giữa retrieval và generation — request đầu tiên sau khi cache prompt hết hạn phải tải prompt từ Langfuse.
- **Root cause:** Bước **retrieval (vector store) chậm thêm ~2.5 s mỗi request** (incident `rag_slow` do challenge inject). Ba lớp bằng chứng cùng chỉ về một chỗ: metric latency tăng nhưng TTFT/tokens/errors không đổi → log cùng request `latency_ms` 2,654 với `ttft_ms` 50 → trace cùng `correlation_id` có span `retrieval` 2.50 s chiếm 94% thời gian. Xác nhận ngược: tắt incident lúc 16:38:45 thì cùng 5 query quay về ~805 ms phía client. Yếu tố khuếch đại: endpoint `async def chat` gọi `agent.run` đồng bộ nên chặn event loop — 5 request đồng thời bị xếp hàng (bắt đầu cách nhau đúng ~2.65 s), vì vậy client thấy 13.5–16.2 s dù mỗi request chỉ tốn 2.65 s ở server.
- **Fix action:** (1) Tắt nguồn gây chậm — `python scripts/inject_incident.py --disable` (tương đương khôi phục vector store), đã xác nhận hồi phục. (2) Đặt timeout cho retrieval (ví dụ 500 ms) và fallback trả lời không cần docs khi quá hạn, để một dependency chậm không kéo cả request vượt SLO. (3) Chuyển `chat` sang `def` (FastAPI chạy trong threadpool) hoặc bọc `agent.run` bằng `run_in_threadpool`, để một request chậm không chặn các request khác.
- **Preventive measure:** Alert `HighLatencyP95` (P95 > 2000 ms trong 5m) sẽ bắn trước khi chạm SLO 3000 ms; bổ sung SLI riêng cho retrieval (P95 của span `retrieval`, ví dụ ≤ 300 ms) để alert chỉ thẳng thành phần hỏng; thêm panel/metric `retrieval_ms` vào dashboard (đã có trong trace metadata); load test định kỳ với concurrency > 1 để phát hiện lỗi chặn event loop; runbook `docs/alerts.md#alert-1` đã ghi sẵn bước so sánh span `retrieval` vs `llm-generation`.

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
