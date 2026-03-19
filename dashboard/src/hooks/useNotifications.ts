import { useEffect } from "react";

interface PipelineNotification {
  type: string;
  task_id: string;
  title: string;
  body: string;
  timestamp: string;
}

export function useNotifications(onNotification?: (n: PipelineNotification) => void) {
  useEffect(() => {
    const eventSource = new EventSource("/api/v1/pipeline/notifications/stream");

    eventSource.onmessage = (event) => {
      try {
        const notification: PipelineNotification = JSON.parse(event.data);
        onNotification?.(notification);

        if ("Notification" in window && Notification.permission === "granted") {
          new Notification(notification.title, { body: notification.body });
        }
      } catch {
        // Ignore parse errors (heartbeats)
      }
    };

    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }

    return () => eventSource.close();
  }, [onNotification]);
}
