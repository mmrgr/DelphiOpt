# Execution safety

Each candidate is copied into a separate temporary workspace. `sandbox.type` selects `local` or `docker`. Docker execution uses argv rather than nested shell quoting, disables networking by default, applies CPU/memory limits, mounts only the candidate workspace, and enforces command timeouts.

Accepted files are replaced atomically and restored from in-memory backups if synchronization fails. Production deployments should select Docker, use a pinned read-only base image where project behavior permits, restrict mounts, and keep timeouts and global budgets enabled.
