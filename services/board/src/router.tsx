import { createBrowserRouter } from "react-router-dom"
import { AppShell } from "./AppShell"

export const router = createBrowserRouter([
  { path: "/", element: <AppShell /> },
])
