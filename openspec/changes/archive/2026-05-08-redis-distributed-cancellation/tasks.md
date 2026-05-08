# Tasks: Forwarder Stream Loop 集成 Redis Cancel Fallback

## Task 1: 修改 `_forward_stream` 签名和 stream generator
- [ ] 在 `_forward_stream` 签名中增加 `broadcaster: CancellationBroadcaster | None` 参数
- [ ] 在 `agent_routers/services/forwarder.py` 顶部导入 `CancellationBroadcaster`
- [ ] 在 stream generator 中增加 chunk 计数器 `chunks_since_check = 0`
- [ ] 每收到 20 个 chunks，如果 `broadcaster` 不为 None，调用 `await broadcaster.poll_key(request_id)`
- [ ] 如果 `poll_key` 返回 True：log `stream_cancelled_redis_fallback`，`cancel_event.set()`，然后 `break`
- [ ] `poll_key` 异常时静默忽略（Redis 不可用不影响流继续）

## Task 2: 修改 `forward()` 调用点
- [ ] 在 `forward()` 方法中获取 `broadcaster = get_broadcaster()`
- [ ] 将 `broadcaster` 传入 `_forward_stream(...)` 调用

## Task 3: 更新单元测试
- [ ] 在 `tests/unit/test_forwarder.py` 中，所有调用 `_forward_stream` 的测试传入 `broadcaster=None`
- [ ] 新增测试：`test_forward_stream_redis_fallback_cancels` — mock `broadcaster.poll_key` 返回 True，验证 generator 在第 20 个 chunk 后中断

## Task 4: 更新 contract 测试
- [ ] 在 `tests/contract/test_cancel_sse.py` 中，`_forward_stream` 调用增加 `broadcaster=None`

## Task 5: 验证
- [ ] `python3 -m ruff check agent_routers tests`
- [ ] `python3 -m mypy agent_routers`
- [ ] `python3 -m pytest tests/unit`
- [ ] `python3 -m pytest tests/integration`
- [ ] `python3 -m pytest tests/contract`
