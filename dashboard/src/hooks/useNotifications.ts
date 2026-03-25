import { useEffect } from "react";
import type { ToastVariant } from "../components/ui/Toast";

export interface PipelineNotification {
  type: string;
  task_id: string;
  title: string;
  body: string;
  timestamp: string;
}

const TYPE_TO_VARIANT: Record<string, ToastVariant> = {
  complete: "success",
  completed: "success",
  failed: "error",
  error: "error",
  warning: "warning",
};

export function toastVariantFor(type: string): ToastVariant {
  return TYPE_TO_VARIANT[type] ?? "info";
}

export function useNotifications(onNotification?: (n: PipelineNotification) => void) {
  useEffect(() => {
    const eventSource = new EventSource("/api/v1/pipeline/notifications/stream");

    eventSource.onmessage = (event) => {
      try {
        const notification: PipelineNotification = JSON.parse(event.data);
        onNotification?.(notification);
      } catch {
        // Ignore parse errors (heartbeats)
      }
    };

    return () => eventSource.close();
  }, [onNotification]);
}
