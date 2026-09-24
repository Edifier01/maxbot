# MAXBOT safe error contract

This catalogue is the public error vocabulary. `app.services.errors` is the
runtime source of truth and must construct `ErrorInfo` from a trusted source
boundary. Exception text, credentials, OTP values, session tokens and proxy
credentials are never public fields.

The UI may render the `safe_message` for a known `code`; an unknown code is
rendered as `UNCLASSIFIED`. A mutating outcome of `unknown`, `in_flight`, or
`accepted` is never an automatic retry permission.

| Code | Safe action |
| --- | --- |
| AUTH_REQUIRED | AUTHENTICATE |
| AUTH_SESSION_EXPIRED | REAUTHENTICATE |
| AUTH_SESSION_REVOKED | REAUTHENTICATE |
| LOGIN_INVALID | REVIEW_INPUT |
| PERMISSION_DENIED | REVIEW_ACCESS |
| SUBSCRIPTION_INACTIVE | REVIEW_SUBSCRIPTION |
| PROFILE_NOT_FOUND | REVIEW_PROFILE |
| OBJECT_NOT_FOUND | REVIEW_OBJECT |
| WORK_GROUP_SELECTION_REQUIRED | SELECT_GROUP |
| DESTINATION_REVIEW_REQUIRED | REVIEW_DESTINATION |
| MEMBERSHIP_REVIEW_REQUIRED | REVIEW_MEMBERSHIP |
| CONSENT_REVOKED | STOP_OPERATION |
| ACCOUNT_AUTOMATION_CONFLICT | REVIEW_CONFLICT |
| ROUTE_MISSING | CONFIGURE_ROUTE |
| ROUTE_CONFLICT | REVIEW_ROUTE |
| ROUTE_DISABLED | ENABLE_ROUTE |
| ROUTE_REVISION_CONFLICT | RELOAD_ROUTE |
| PROXY_URL_INVALID | REVIEW_PROXY |
| PROXY_UNSUPPORTED_SCHEME | REVIEW_PROXY |
| PROXY_AUTH_FAILED | REVIEW_PROXY |
| PROXY_CONNECT_FAILED | REVIEW_PROXY |
| PROXY_RESPONSE_INVALID | REVIEW_PROXY |
| TLS_ERROR | REVIEW_NETWORK |
| MAX_CONNECT_FAILED | REVIEW_NETWORK |
| SDK_INCOMPATIBLE | REVIEW_RUNTIME |
| MAX_SESSION_REVOKED | REAUTHENTICATE |
| MAX_RATE_LIMIT | WAIT_RETRY |
| MAX_ACCOUNT_BANNED | STOP_TENANT |
| MAX_ACTION_FORBIDDEN | REVIEW_ACTION |
| CONNECTION_TIMEOUT | REVIEW_NETWORK |
| CODE_REQUEST_TIMEOUT | RETRY_LOGIN |
| CODE_INPUT_TIMEOUT | RESTART_LOGIN |
| PASSWORD_INPUT_TIMEOUT | RESTART_LOGIN |
| OTP_FORMAT_INVALID | REVIEW_INPUT |
| OTP_INVALID | REVIEW_INPUT |
| OTP_EXPIRED | REQUEST_NEW_CODE |
| PASSWORD_INVALID | REVIEW_INPUT |
| ATTEMPT_STATE_CONFLICT | RELOAD_OPERATION |
| ATTEMPT_EXPIRED | RESTART_OPERATION |
| ATTEMPT_INTERRUPTED | REVIEW_OPERATION |
| REGISTRATION_REQUIRED | REVIEW_REGISTRATION |
| SEND_OUTCOME_UNKNOWN | RECONCILE_BEFORE_RETRY |
| ACK_PERSIST_PENDING | PERSIST_ACK |
| CLEANUP_FAILED | REVIEW_CLEANUP |
| DAILY_BUDGET_ALLOCATED | REVIEW_BUDGET |
| CAMPAIGN_BUSY | WAIT_OPERATION |
| PREVIEW_STALE | RELOAD_PREVIEW |
| COMMAND_STATE_UNKNOWN | RECONCILE_BEFORE_RETRY |
| STOP_PENDING | WAIT_OPERATION |
| RESTORE_HOLD | REVIEW_RESTORE |
| MIGRATION_REVIEW_REQUIRED | REVIEW_MIGRATION |
| VAULT_KEY_REQUIRED | UNLOCK_VAULT |
| VAULT_INTEGRITY_FAILED | REVIEW_VAULT |
| STORAGE_ERROR | REVIEW_STORAGE |
| POLICY_APPLY_PARTIAL | REVIEW_POLICY |
| VERSION_CONFLICT | RELOAD_DATA |
| POOL_EMPTY | REVIEW_LIBRARY |
| IMPORT_INVALID | REVIEW_IMPORT |
| INPUT_TOO_LARGE | REVIEW_INPUT |
| SETTINGS_NOT_LOADED | RELOAD_SETTINGS |
| API_RATE_LIMIT | WAIT_RETRY |
| NETWORK_UNAVAILABLE | REVIEW_NETWORK |
| SERVER_UNAVAILABLE | WAIT_RETRY |
| LOGOUT_NOT_CONFIRMED | REVIEW_SESSION |
| IMPERSONATION_EXIT_FAILED | REVIEW_SESSION |
| UNCLASSIFIED | REVIEW_OPERATION |

T03 unit evidence covers source precedence, proxy-vs-MAX sanction separation,
unknown mutation handling, and secret-free envelopes. Current dirty-worktree
T27/T30 browser evidence now covers visible cabinet, admin and impersonation
role surfaces for all catalogue codes and normalized actions; it remains
uncommitted local evidence, while auxiliary consumers and manual acceptance
remain pending.

For every catalogue row the cabinet and admin renderer expose the normalized
action token as an explicit keyboard-focusable control. The control only opens
the relevant local review surface, reads a local journal/settings/list endpoint,
or opens authentication; it never retries an unknown mutation, submits OTP or
password material, or invokes MAX/provider traffic automatically. `STOP_*`
actions focus the explicit Stop control and require a separate user click.

## Account and campaign presentation

- Show one primary profile status: active, awaiting first login (`pending`),
  reauthentication required (`needs_reauth`), disabled, or banned. Show an
  in-progress code/password prompt or a temporary cooldown separately from that
  status; do not repeat the primary status as a second badge.
- Offer the primary login action only for a pending or reauthentication-needed
  profile that is not already in an auth step and has a selected group. A banned
  profile must never offer login. Put cancellation, diagnostics, repeat-login,
  and removal under an accessible “Ещё” disclosure. Preserve confirmation for
  destructive account, group, subscription, and impersonation actions.
- The user campaign home presents launch readiness and its safe, localized
  blockers before Start. Use `/api/campaign/preview` and carry its
  `readiness_revision` with Start. If the preview is stale, disable Start, fetch
  a fresh preview, and show that the earlier result expired. Never display raw
  readiness codes to a user.
- The user home shows “Требуют внимания” from read-only
  `GET /api/dashboard/attention?offset=0&limit=10`. The feed contains safe
  profile fields for tenant profiles that need attention, including profiles
  without an enabled group. `limit` is clamped to 50. Priority is banned,
  waiting for auth input, reauthentication,
  first login, disabled, then temporary pause. It must not return proxy URLs,
  proxy credentials, MAX credentials, SMS/password values, or session data.
- A ban message must make clear that campaign sending stopped for the tenant.
  Its only available follow-up is safe current-attempt diagnostics when such a
  diagnostic exists; never suggest another login for a banned account.
- The admin user table keeps subscription expiry visible and combines the
  30-day and custom extension into one days input. Secondary and destructive
  actions remain keyboard accessible in “Ещё”; revoke and delete still require
  confirmation. The impersonation cabinet preserves all role restrictions.
