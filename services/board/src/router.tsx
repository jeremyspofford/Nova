import { createBrowserRouter } from "react-router-dom"
import { AppShell } from "./AppShell"
import { Settings } from "./components/Settings/Settings"

export const router = createBrowserRouter([
  { path: "/",         element: <AppShell /> },
  { path: "/settings", element: <Settings /> },
])
