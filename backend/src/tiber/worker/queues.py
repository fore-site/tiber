from kombu import Exchange, Queue

NOTIFICATIONS_EXCHANGE = Exchange(
    "notifications.exchange",
    type="topic",
    durable=True,
)

NOTIFICATION_QUEUE = Queue(
    "notifications",
    exchange=NOTIFICATIONS_EXCHANGE,
    routing_key="notification.created",
    durable=True,
)

TASK_QUEUES = (NOTIFICATION_QUEUE,)
