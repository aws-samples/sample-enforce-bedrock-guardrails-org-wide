# Security notes and known limitations

This is a sample/reference implementation, not a hardened production
artifact. Read this before adapting any part of it, especially the
Organizations policy.

## AppSec review status

This repository has **not** completed a formal AWS AppSec security review.
It deploys or documents:

- An AWS Organizations Bedrock policy (`artifacts/bedrock-organizations-policy.json`)
- Account-wide guardrail set/delete operations (`scripts/set_account_enforcement.py`,
  `scripts/delete_account_enforcement.py`)
- A cross-account resource-based policy on the guardrail (in `cdk/lib/blog-guardrail-stack.ts`)
- A multi-account CloudFormation StackSet (`cdk/lib/blog-stackset-stack.ts`)
- A CI/CD pipeline with a production deployment stage (`.gitlab-ci.yml`)

Content that implements a security-focused solution, or that provides
guidance on implementing authorization, is in scope for escalation under
AWS's internal AppSec review criteria. If you are an AWS employee adapting
this content for internal or external publication, open an AppSec
consultation before publishing rather than relying on this disclaimer alone.
External users of this sample should run their own independent security
review before deploying any part of this to a production AWS Organization.

## Known limitations

### The SCP backstop (Layer 2) is not shipped in this repository

The Layer 2 service control policy that denies `bedrock:InvokeModel*` /
`bedrock:Converse*` without a `bedrock:GuardrailIdentifier` is described in
the accompanying blog post, not provided as a file here, because it changes
IAM authorization behavior across an Organization and must be authored and
reviewed by the adopting organization's own security team.

Two properties to evaluate when you write your own:

- A `Null` condition on `bedrock:GuardrailIdentifier` only proves *some*
  guardrail identifier was supplied on the call — it does not verify the
  caller used the *approved* central guardrail. Layer 1 (the Bedrock
  Organizations policy) is the layer that pins to one approved guardrail
  ARN and auto-applies it regardless of what the caller passes. A pinned
  `StringNotLike` / `ArnLike` variant closes that gap at the cost of
  blocking Layers 3 and 4 from ever varying the guardrail per account or app.
- Like any SCP, it only has effect where attached, and only for principals
  who cannot modify Organizations policies. Any principal with
  `organizations:DetachPolicy` / `organizations:UpdatePolicy` in the
  management account can remove or weaken it. Restrict those permissions to
  a small, audited set of principals.

### Dependency status (CSR-003)

All Critical and High advisories reported by `npm audit` (in `cdk/`) and
by the Python dependency scan have been remediated by upgrading, not by
exception. Current pins: `aws-cdk-lib` 2.275.0 (bundles `brace-expansion`
5.0.12), `jest` 30.5.2, `ts-jest` 29.4.15, `pillow` 13.0.0. Where a
vulnerable copy was reachable only as a transitive dependency,
`cdk/package.json` `overrides` pins it: `handlebars` 4.7.10, `js-yaml@3`
3.15.2, `brace-expansion` 1.1.21 / 2.1.7 / 5.0.12, `glob` 14.0.4,
`minimatch` 11.0.5. `npm audit fix --force` was not used.

`cdk/npm-audit-report.txt` is the report captured at this commit. Two
advisories remain, neither Critical nor High, and neither has a non-breaking
fix (`npm audit` offers only major-version downgrades of `jest` or
`aws-cdk-lib`, which would reintroduce the fixed findings above):

| Advisory | Package | Severity | Where | Why unpatched |
| --- | --- | --- | --- | --- |
| [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249) (globparts amplification DoS) | `minimatch` 10.2.6 | Moderate | `node_modules/aws-cdk-lib/node_modules/minimatch` | Bundled inside the published `aws-cdk-lib` package (`bundleDependencies`); consumer `overrides` cannot reach into a bundle. Fix requires an upstream `aws-cdk-lib` release that bundles `minimatch` ≥ 11.0.1. Used only during `cdk synth` on the developer/CI machine, never in deployed resources. |
| [GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) (prototype poisoning of returned objects) | `deepmerge` 4.3.1 | Low | `jest-config` → `deepmerge` | 4.3.1 is the latest release; no fixed version exists. Reached only when Jest merges its own config object; no untrusted input flows into it in this repo. |

Both are build/test-tooling exposure on the machine that runs `npm test` or
`cdk synth`; neither ships in the guardrail, dashboard or StackSet stacks.
Re-run `npm audit` in `cdk/` before you deploy and upgrade `aws-cdk-lib`
to the current latest; an upstream bundle refresh clears the first row.

Python dependencies are exact-pinned in `requirements*.txt` and installed
from hash-locked `requirements*.lock` files (`--require-hashes`) by both
`make install` and CI, so a substituted or tampered wheel fails the install.

### `run_benchmark.py` and `capture_trace.py` write full model output and guardrail trace JSON to disk in plaintext

`results/*.csv`, `results/summary_*.json`, and `results/trace_*.json`
contain the full prompt text, full model response text, and the complete
guardrail assessment (which can include detected PII entity values,
depending on your guardrail's PII policy actions). These files are
gitignored, but they are not encrypted or access-controlled beyond your
local filesystem permissions. If you run these scripts against
production-like prompts, treat `results/` as containing sensitive data:
restrict its permissions, avoid committing it, and delete it when you are
done with a benchmarking session (`make clean` removes generated result
files).

### `delete_account_enforcement.py` has no confirmation prompt

This script removes the account-wide enforced guardrail configuration for
the account/region you point it at, immediately and without confirmation.
If Layer 1 (the org policy) is not also active, this leaves the account
with only Layer 4 (per-app attachment) as enforcement until a new
configuration is set. Before wiring this into automation, add an explicit
`--yes` flag requirement or an interactive confirmation prompt, and confirm
via `scripts/get_account_enforcement.py` (or `--dry-run`, if you add one)
what will be removed before running it against any account you did not
personally provision for testing.

### `BlogDashboardStack`'s `alarmTopicArn` prop is accepted but not wired to alarm actions

`cdk/lib/blog-dashboard-stack.ts` declares an optional `alarmTopicArn` prop
but the two `Alarm` constructs do not currently attach it via
`.addAlarmAction()`. Alarms are created and visible in the CloudWatch
console, but nobody is paged when they fire. If you rely on these alarms
for operational awareness, either pass `alarmTopicArn` and confirm the
alarm actions are wired (check the current state of the stack before
assuming this is fixed — see the stack's source for the latest behavior),
or wire your own notification mechanism.

### The StackSet rollout creates independent per-account guardrails, not a shared central one

`cdk/lib/blog-stackset-stack.ts` synthesizes and deploys a **new,
independent copy** of the benchmark guardrail into every target
account/region — it does not reference one central, shared guardrail. Each
member account ends up with its own `AWS::Bedrock::Guardrail` resource with
the same configuration, not a pointer to a single organization-owned
guardrail. If your intended model is "one central guardrail that every
account references" (as Layer 1's org policy does), the StackSet path is
not that model — it is independent guardrail replication. Decide which
model your organization actually wants before using this stack, and update
the guardrail's policy content in one place if you need config drift
control across the fleet, since a StackSet update will redeploy to every
instance.

### Member-account `ApplyGuardrail` permission model

The cross-account resource-based policy that `blog-guardrail-stack.ts`
attaches (when `AWS_ORG_ID` is set) grants `bedrock:ApplyGuardrail` and
`bedrock:GetGuardrail` to any principal in the organization. It does not by
itself grant the IAM-side permission a member-account principal needs to
call `ApplyGuardrail` against a cross-account guardrail — member-account
IAM policies/roles must also explicitly allow those actions on the
guardrail's ARN. Confirm both the resource-based policy (management
account side) and the calling principal's IAM policy (member-account side)
are both in place; a missing member-account IAM grant is a common source of
`AccessDeniedException` that the resource policy alone will not fix. The
identity-side policy is not shipped in this repository; an example is
shown in the blog post for reference only.

### CloudTrail: invocation calls are management events; guardrail decisions are data events

Per the [Bedrock CloudTrail documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html),
`InvokeModel`, `InvokeModelWithResponseStream`, `Converse` and
`ConverseStream` are logged as **management events** (any standard trail
captures them). The record of *what a guardrail decided* is the
`ApplyGuardrail` **data event** on resource type `AWS::Bedrock::Guardrail`,
emitted both for direct `ApplyGuardrail` calls and for the evaluations
Bedrock performs inside a model invocation. Data events are off by default;
without an advanced event selector for `AWS::Bedrock::Guardrail`, the
intervention query (Q2) in `queries/cloudwatch_logs_insights.txt` returns
nothing, and you have no CloudTrail evidence of interventions beyond the
`AWS/Bedrock/Guardrails` CloudWatch metrics.

**Enabling the data event is a trail-wide write.**
[`PutEventSelectors`](https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/API_PutEventSelectors.html)
replaces every selector on the trail rather than appending, and events that
match no selector are not logged. A command containing only the
Bedrock data-event rule would silently stop that trail recording management
events. The example in `queries/cloudwatch_logs_insights.txt` therefore
includes an explicit `eventCategory = Management` selector alongside the
data-event rule, and the file instructs readers to run it against a
dedicated demonstration trail, or to merge it with the output of
`get-event-selectors` first if they must touch a real trail. Two further details the
queries depend on: `eventSource` is `bedrock.amazonaws.com` for all of
these (not `bedrock-runtime`), and streaming calls emit an extra
`AwsServiceEvent` record on stream completion that must be excluded
(`eventType = "AwsApiCall"`) or invocation counts double.

### The release gate requires guardrail identity by default

`scripts/verify_deployment.py`'s intervention check passes only when the
assessment that carries a `BLOCKED` finding is attributed, via
`appliedGuardrailDetails` (id/ARN and version), to the guardrail under
test. A different guardrail blocking (an org-enforced or account-enforced
guardrail, or a workload's own) while the deployed one is merely in scope
fails the gate. When Bedrock returns no `appliedGuardrailDetails` for the
blocking assessment, identity cannot be proven and the gate **fails by
default**. Setting `VERIFY_ALLOW_UNCONFIRMED_IDENTITY=1` downgrades that to
a PASS with `identity_confirmed: false` in the JSON report; use it only for
API surfaces that never return the field, and treat such a result as "a
guardrail intervened", not as proof the deployed guardrail is enforcing.

### CI/CD authentication and supply-chain posture

`.gitlab-ci.yml` uses long-lived AWS credentials stored as CI/CD variables
(`DEV_AWS_ACCESS_KEY_ID`, etc.) rather than short-lived, workload-identity
federated credentials (e.g. GitLab-to-AWS OIDC). Long-lived credentials in
CI variables are a larger blast radius if leaked (via a misconfigured job,
a malicious MR from a fork, or a compromised runner) than federated
credentials scoped to a single pipeline run. The pipeline header marks the
static-credential pattern as sandbox-only and ships a commented `.aws-oidc`
job template (`id_tokens:` + `sts assume-role-with-web-identity`) as the
production-strength starting point, with the AWS-side prerequisites (OIDC
identity provider, one scoped role per stage, trust policy conditioned on
the project and protected branch) described alongside it. If you use this
pipeline as a starting point for a real deployment, switch to that template
and delete the `*_AWS_*` variables before granting it access to any account
that matters, and pin third-party GitLab CI image tags (`python:3.12-slim`,
`node:20-slim`) to digests rather than floating tags to reduce supply-chain
exposure from image retagging.

## CSR-012 status — automated evidence vs. formal review

The formal-review portion of a security review has three sub-parts. Here is
what this repository closes with automated tooling, and what still requires
a human security reviewer:

- **cdk-nag (static analysis):** Wired into every `cdk synth` via
  `cdk/bin/app.ts` (`AwsSolutionsChecks`), enforced in CI
  (`.gitlab-ci.yml`'s `cdk-synth` job), and locked in by a dedicated Jest
  test (`cdk-nag (CSR-012)` in `cdk/test/synth.test.ts`) that fails if any
  unsuppressed `AwsSolutions-*` finding appears. One finding
  (`AwsSolutions-IAM4` on the `AwsCustomResource`-internal Lambda's
  `AWSLambdaBasicExecutionRole`) is suppressed with a documented reason in
  `blog-guardrail-stack.ts` — see the code comment there for why no
  supported fix exists. Run `make nag` to execute this check directly.
- **npm audit (dependency evidence):** `cdk/npm-audit-report.txt` is
  attached as evidence. Critical/High: 0. The two remaining Moderate/Low
  advisories and the reason each is unpatched are listed in the dependency
  section above for the reviewer to record a risk decision.
- **Threat model:** [`THREAT_MODEL.md`](THREAT_MODEL.md) is a draft written
  as part of this remediation, covering assets, trust boundaries, and a
  STRIDE-style threat/mitigation table for all four layers plus the
  supporting infrastructure. **This document has not been reviewed or
  signed off by a security engineer.** Treat it as a structured starting
  point for that review, not as proof the review occurred.

None of the above substitutes for CSR-001's required AppSec consultation.
Automated tooling catches known classes of infrastructure misconfiguration;
it does not replace a human reviewer's judgment on whether the overall
design (four-layer enforcement, the specific SCP condition choice, the
Organizations-policy trust model) is appropriate for a given organization's
risk tolerance.

## Reporting a vulnerability

If you find a security issue in this sample code, do not open a public
GitHub issue. Follow the process described in the top-level
[AWS Vulnerability Reporting Guide](https://aws.amazon.com/security/vulnerability-reporting/)
or, for AWS-internal contributors, open a ticket through your organization's
standard security escalation path.
