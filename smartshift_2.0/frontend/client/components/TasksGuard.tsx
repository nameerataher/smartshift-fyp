import { Navigate } from "react-router-dom";
import { useMode } from "@/hooks/useMode";
import Tasks from "@/pages/Tasks";

/** Wraps Tasks and redirects personal users to /map (commercial-only route). */
export function TasksGuard() {
  const { isPersonalUser } = useMode();
  if (isPersonalUser) return <Navigate to="/map" replace />;
  return <Tasks />;
}
