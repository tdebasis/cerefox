import { notifications } from "@mantine/notifications";

export function showSuccess(title: string, message?: string) {
  notifications.show({
    title,
    message: message || "",
    color: "green",
    autoClose: 4000,
  });
}

export function showError(title: string, message?: string) {
  notifications.show({
    title,
    message: message || "",
    color: "red",
    autoClose: 6000,
  });
}

export function showInfo(title: string, message?: string) {
  notifications.show({
    title,
    message: message || "",
    color: "blue",
    autoClose: 4000,
  });
}
