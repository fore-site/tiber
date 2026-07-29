task_routes = {
    "tiber.worker.tasks.process_notification": {
        "queue": "notifications",
        "routing_key": "notification.created",
    },
}
