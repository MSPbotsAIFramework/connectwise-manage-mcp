# Omit disabled note email flags

Internal note creation previously forwarded explicitly false emailContactFlag,
emailResourceFlag and emailCcFlag values in the ServiceNote JSON body. Strict
API versions can reject these properties even when false. Omit disabled flags
just as the existing default omits them. Keep true flags, explicit
processNotifications=false and the requested note category unchanged.

Three regressions exercise the actual MCP handler against a strict simulated
ServiceNote endpoint. They fail before the patch and pass after it. No automatic
retry or fallback write was added; a failed write is not retried with changed
notification semantics. Existing public tool names and parameters are preserved.

This is a local compatibility candidate, not a live deployment or a solution for
call-to-ticket target binding. Explicit email delivery on an API version that
rejects true flags still requires investigation; do not silently drop delivery.
