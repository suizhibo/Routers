# Proposal: Forwarder Stream Loop 集成 Redis Cancel Fallback

## 问题

`CancellationBroadcaster.publish()` 同时做了两件事：
1. Redis Pub/Sub 广播 `CANCEL_CHANNEL`
2. Redis SET `cancel:{request_id}` key (TTL=30s)

第 2 点是一个 fallback 机制：即使某个工作节点错过了 Pub/Sub 消息，也可以通过检查 Redis key 发现请求已被取消。

`poll_key()` 方法已经实现并测试覆盖，但 **forwarder 的 stream 循环从未调用它**。流式转发只检查本地 `cancel_event.is_set()`：

```python
# agent_routers/services/forwarder.py:378
if cancel_event is not None and cancel_event.is_set():
    break
```

这意味着：
- 如果节点 B 正常收到 Pub/Sub 消息 → 取消成功
- 如果节点 B 因网络闪断、Redis 重连、或进程重启而错过了 Pub/Sub 消息 → 流式请求永远不知道自己已被取消

## 本质需求

分布式部署时，**任何节点发起的取消请求，必须可靠地终止正在处理该请求的目标节点上的流式转发**。

## 方案

保留现有 Pub/Sub + 本地 `asyncio.Event` 架构（这是正确的），只在 stream 循环中增加一个 **periodic Redis key fallback**：

每收到 N 个 chunks（或每隔一段时间），异步查询 Redis `cancel:{request_id}` key。如果 key 存在，主动 `cancel_event.set()` 并中断流。

这个改动不涉及 `self._events` dict 的替换（`asyncio.Event` 无法也不应存入 Redis），而是补齐现有 fallback 机制的调用链路。
