# Agent Guidelines

## Task Cleanup

Before finishing a task, clean up temporary resources created during that task:

- Stop development servers, watchers, background Node/Next.js processes, browser sessions, and other local services started by the agent.
- Stop and remove temporary containers, networks, and volumes created specifically for the task.
- Remove disposable virtual environments, temporary files, screenshots, logs, and generated test artifacts that are not requested deliverables.
- Check that no command or tool session started for the task is still running before sending the final response.

Only clean up resources created or explicitly owned by the current task. Never use broad commands such as `pkill node`, and never stop user-owned processes, shared containers, databases, caches, or external services.

If the user explicitly asks to keep a service running, leave it running and report its address and process details in the final response.

## Frontend Visual QA

For every frontend update, save visual QA screenshots to a task-specific folder under `tmp/` in the repository. Keep those screenshots as deliverable artifacts unless the user explicitly asks to remove them.

After each verified frontend visual tuning pass, commit its code and roadmap changes as a separate checkpoint with a descriptive message. Keep generated screenshots under `tmp/` out of Git unless the user explicitly requests versioned image artifacts.
