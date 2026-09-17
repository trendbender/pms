// Short shareable task link: /t/<KEY> (e.g. /t/SSK-23). Reuses the task detail
// page, which resolves either a UUID (/tasks/<uuid>) or a human key (this route).
// Word-like keys avoid the phishing heuristics that flag long random UUID paths.
export { default } from "@/app/tasks/[taskId]/page";
