# Sovereign VHLL Execution Fabric

Runtime sequence:

1. Receive objective.
2. Convert objective into VHLL manifest.
3. Validate manifest schema.
4. Run no-spend policy.
5. Minify system/context payload.
6. Check vector cache for known verified execution.
7. Return cache hit when confidence passes floor.
8. Compute complexity on cache miss.
9. Route simple deterministic tasks to scripts.
10. Route local AI tasks to local model when enabled.
11. Queue high-risk or paid tasks for approval.
12. Verify output.
13. Run security scan.
14. Log result.
15. Commit verified result to memory.
16. Update Lifelong Catch and Correct.
