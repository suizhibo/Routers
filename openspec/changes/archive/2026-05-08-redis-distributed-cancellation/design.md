# Design: Forwarder Stream Loop 集成 Redis Cancel Fallback

## 改动范围

只修改 `agent_routers/services/forwarder.py` 中的 `_forward_stream` 方法，其余 coordination 组件保持不变。

## Stream 循环变更

当前代码（agent_routers/services/forwarder.py:366-388）：

```python
async def generator() -> AsyncIterator[bytes]:
    try:
        async with client.request(method, url, **kwargs) as upstream:
            async for chunk in upstream.content.iter_any():
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("stream_cancelled")
                    break
                yield chunk
    except asyncio.CancelledError:
        logger.info("stream_cancelled")
        raise
```

新设计：每 20 个 chunks 检查一次 Redis fallback。选择 chunk 计数而非时间间隔，是因为 SSE 流的 chunk 到达间隔不可预测（可能几秒一条），而计数方式更稳定且开销可控。

```python
async def generator() -> AsyncIterator[bytes]:
    chunks_since_check = 0
    try:
        async with client.request(method, url, **kwargs) as upstream:
            async for chunk in upstream.content.iter_any():
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("stream_cancelled_local")
                    break

                # Redis fallback: check every 20 chunks if broadcaster is available
                chunks_since_check += 1
                if chunks_since_check >= 20 and broadcaster is not None:
                    chunks_since_check = 0
                    try:
                        if await broadcaster.poll_key(request_id):
                            logger.info("stream_cancelled_redis_fallback", extra={"request_id": request_id})
                            cancel_event.set()  # set locally so next iteration breaks
                            break
                    except Exception:
                        # Redis unreachable — keep streaming, will retry on next 20 chunks
                        pass

                yield chunk
    except asyncio.CancelledError:
        logger.info("stream_cancelled")
        raise
```

## 依赖注入

`_forward_stream` 的签名增加 `broadcaster` 参数：

```python
async def _forward_stream(
    self,
    client: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: dict[str, Any],
    body: Any,
    cancel_event: asyncio.Event | None,
    agent_id: str,
    session_id: str | None,
    broadcaster: CancellationBroadcaster | None,
) -> StreamingResponse:
```

`forward()` 方法中，在调用 `_forward_stream` 时传入 `get_broadcaster()` 的结果。

## 为什么选 chunk 计数而非时间轮询

| 方式 | 优点 | 缺点 |
|------|------|------|
| 每 N 秒轮询 | 延迟有上限 | 需要 `asyncio.sleep` 或额外 task；如果流很慢，会空转 |
| 每 N 个 chunks | 无空转；实现简单；与流天然同步 | 极端慢流下延迟可能较高 |

SSE 流的典型场景是 AI 生成的 token 流，chunks 到达频率通常在 10-100ms 级别，每 20 chunks 约 200ms-2s 的检查间隔是可接受的。

## 为什么不替换 `self._events`

`asyncio.Event` 是进程内协程同步原语，提供 `wait()` / `is_set()` / `set()` 接口。它不能也不应被替换为 Redis，因为：

1. 无法序列化：`asyncio.Event` 包含锁、条件变量等 OS 资源
2. 语义不同：Redis 是网络存储，检查一次需要 RTT；`is_set()` 是纳秒级的内存访问
3. 当前架构正确：Pub/Sub 负责实时通知，Redis key 负责持久化 fallback，本地 event 负责进程内高效同步

## 文件变更

| 文件 | 变更 |
|------|------|
| `agent_routers/services/forwarder.py` | `_forward_stream` 增加 `broadcaster` 参数；stream generator 增加每 20 chunks 的 `poll_key` fallback |
| `tests/unit/test_forwarder.py` | 更新 `_forward_stream` mock 调用，传入 `broadcaster=None` |
| `tests/contract/test_cancel_sse.py` | 同上 |
