"use client";

import { usePathname } from "next/navigation";
import { AppNav } from "@/components/AppNav";

/** Renders the app-wide top nav on every authenticated page (all but /login and
 * the root redirect), highlighting the section that matches the current path. */
export function NavGate() {
  const path = usePathname();
  if (!path || path === "/" || path.startsWith("/login")) return null;

  let active:
    | "dashboard"
    | "myTasks"
    | "myReviews"
    | "allTasks"
    | "projects"
    | "users"
    | undefined;
  if (path.startsWith("/dashboard")) active = "dashboard";
  else if (path.startsWith("/my-tasks")) active = "myTasks";
  else if (path.startsWith("/my-reviews")) active = "myReviews";
  else if (path.startsWith("/all-tasks")) active = "allTasks";
  else if (path.startsWith("/projects") || path.startsWith("/tasks") || path.startsWith("/t/"))
    active = "projects";
  else if (path.startsWith("/users")) active = "users";

  return <AppNav active={active} />;
}
