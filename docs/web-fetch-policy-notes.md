# Web Fetch Policy Notes

## Current stance

`web_fetch` is currently treated as a **safe read capability** in ORBIT.

Why:
- it performs bounded remote retrieval
- it does not mutate local workspace files
- it does not send messages or perform external write actions
- its current role is public/readable docs/web text retrieval rather than authenticated browsing or crawler-style automation

## Current intended boundary

The intended boundary for the current first slice is:
- public/readable `http` / `https` retrieval
- bounded content extraction
- lightweight HTML text normalization
- metadata return suitable for coding-agent context building

The current first slice is **not** intended to mean:
- authenticated browsing
- full browser automation
- crawler recursion
- a finalized trust model for all possible network targets

## Future hardening candidates

Future policy hardening may want to add or tighten rules around:
- localhost / loopback targets
- private-network / RFC1918 targets
- redirect trust and host changes
- stricter host-level allow / deny rules
- clearer distinction between public-doc retrieval and arbitrary network probing

## Why document this now

The current implementation choice is reasonable for a first bounded retrieval slice, but it should not be mistaken for the final network policy of ORBIT.
