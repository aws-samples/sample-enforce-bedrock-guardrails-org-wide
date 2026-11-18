# Threat model — centralized Bedrock Guardrails enforcement

> **Status:** Draft, written as part of the CSR-012 remediation. This
> document has **not** received formal security review sign-off. Treat it
> as a structured starting point for that review, not as evidence the
> review has happened. See [SECURITY.md](SECURITY.md) for the review
> status of this repository as a whole.

## 1. Scope

This threat model covers the four enforcement layers implemented in this
repository and the supporting infrastructure (CDK stacks, CI/CD pipeline,
and operational scripts) that deploy, verify, and operate them:

- **Layer 1** — Bedrock Organizations policy (`artifacts/bedrock-organizations-policy.json`)
- **Layer 2** — Service control policy (described in the blog post; not shipped as a file in this repository — see SECURITY.md)
- **Layer 3** — Account-level enforced guardrail configuration (`scripts/set_account_enforcement.py`, `scripts/delete_account_enforcement.py`)
- **Layer 4** — Per-app guardrail attachment (application-side `guardrailIdentifier`/`guardrailVersion` on `InvokeModel`/`Converse`)
- Supporting infrastructure: the guardrail CDK stack and its cross-account
  resource policy, the CloudWatch dashboard, the CI/CD pipeline, and the
  Python operational scripts.

Out of scope: the internal implementation of Amazon Bedrock Guardrails
itself (content filtering accuracy, model behavior), and AWS Organizations'
internal policy evaluation engine. Both are treated as trusted AWS-managed
components.

## 2. Assets

| Asset | Description | Impact if compromised |
| --- | --- | --- |
| The approved central guardrail | The single guardrail (specific ARN + numeric version) an organization designates as its baseline | If bypassed or swapped, unfiltered model calls proceed org-wide |
| Bedrock Organizations policy | The org-level document pinning member accounts to the approved guardrail | If detached or edited, Layer 1 enforcement stops entirely |
| SCP | The IAM-layer backstop denying invokes without a guardrail | If detached, edited, or bypassed, Layer 2 backstop is gone |
| Account-level enforced configuration | Per-account floor guardrail | If deleted, an account has only Layer 4 (if anything) as enforcement |
| CI/CD credentials | AWS credentials used by the deployment pipeline | If leaked, an attacker can deploy/modify infrastructure with pipeline-level permissions |
| Prompt/response content in `results/` | Full model I/O and guardrail trace data written by benchmark/verification scripts | May contain PII detected (and possibly not redacted, depending on guardrail action) from test runs |
| The guardrail's cross-account resource policy | Grants `bedrock:ApplyGuardrail`/`GetGuardrail` to org members | If overly broad or misconfigured, could grant call access beyond intended scope |

## 3. Trust boundaries and actors

| Actor | Trust level | Capability |
| --- | --- | --- |
| Management account (or delegated admin) | Fully trusted | Can create/attach/detach Organizations policies and SCPs; owns the central guardrail |
| Member account (workload) principals | Partially trusted | Can call `InvokeModel`/`Converse`/`ApplyGuardrail`; can create their own guardrails; cannot modify org-level policies (assuming least-privilege IAM) |
| Application code inside a member account | Partially trusted, varies by workload | Chooses whether to attach a guardrail identifier on its own calls (Layer 4) |
| CI/CD pipeline | Trusted with deployment-scoped credentials | Can deploy/modify the guardrail CDK stacks; should not have Organizations-policy-modifying permissions |
| External caller (outside the AWS Organization) | Untrusted | No direct access unless the guardrail's resource policy or IAM is misconfigured to allow it |

Trust boundary crossings of interest:
1. Member account → management account: via Organizations API calls (`DescribeEffectivePolicy`, policy attach/detach) — should be denied to member-account principals under normal least-privilege IAM.
2. Application code → Bedrock data plane: every `InvokeModel`/`Converse` call, potentially with or without a guardrail identifier attached.
3. CI/CD pipeline → AWS account: via long-lived static credentials (current state) or OIDC-federated short-lived credentials (recommended target state — see SECURITY.md).
4. Cross-account: member account → management-account-owned guardrail, via the resource-based policy + member-account IAM grant (both required — see CSR-008 in SECURITY.md).

## 4. Threats and mitigations (STRIDE-style)

### T1 — Spoofing: a workload impersonates having a valid guardrail attached

**Threat:** An application attaches a `guardrailIdentifier` that is not the
approved central guardrail (its own, more permissive guardrail), satisfying
Layer 2's `Null` condition check while bypassing the intended baseline.

**Mitigation:** Layer 1 (org policy) auto-applies the approved guardrail
regardless of what the caller passes, so this bypass only escapes Layer 2 —
Layer 1 still evaluates. If Layer 1 is not deployed/attached, this threat
is **not mitigated** by Layer 2 alone. See CSR-002 in SECURITY.md and the
pinned SCP variant discussed in the blog post.

**Residual risk:** Medium, if an organization relies on Layer 2 alone
without Layer 1.

### T2 — Tampering: removal or weakening of the org policy or SCP

**Threat:** A principal with `organizations:DetachPolicy` or
`organizations:UpdatePolicy` in the management account removes or
weakens Layer 1 or Layer 2.

**Mitigation:** This is an IAM/organizational control question outside
this repo's code — restrict those permissions to a small, audited set of
principals in the management account. Not implemented in code; documented
as an operational requirement in SECURITY.md.

**Residual risk:** Medium — depends entirely on the customer's own IAM
hygiene in the management account, which this repo cannot enforce.

### T3 — Tampering: deletion of Layer 3 without a fallback

**Threat:** `delete_account_enforcement.py` removes the account-level
floor guardrail. If Layer 1 is not active for that account and no app has
attached its own guardrail (Layer 4), the account is left with zero
enforcement.

**Mitigation:** The script requires interactive confirmation or an
explicit `--yes` flag (CSR-006), and prints the account/region being
affected before deleting. It does not currently check whether Layer 1 is
active before deleting Layer 3 — that check would need to call
`organizations:DescribeEffectivePolicy`, which requires management-account
or delegated-admin permissions the account owner running this script may
not have. Documented as a residual gap.

**Residual risk:** Low-Medium — confirmation prompt reduces accidental
deletion; the "would this leave zero enforcement" check is not automated.

### T4 — Repudiation: no verifiable record of which guardrail actually enforced a given call

**Threat:** Without the fix in CSR-004, the release-gate script could pass
even if a different (unintended) guardrail intervened on the test prompt,
giving false confidence that the correct guardrail is deployed and active.

**Mitigation:** `scripts/verify_deployment.py` pairs each assessment's
`BLOCKED` findings with that assessment's `appliedGuardrailDetails` and
passes only when the guardrail under test (id/ARN and version) is one that
blocked. Another guardrail blocking while the deployed one was merely in
scope fails the gate. A blocking assessment with no
`appliedGuardrailDetails` fails by default; `VERIFY_ALLOW_UNCONFIRMED_IDENTITY=1`
opts in to a PASS that reports `identity_confirmed: false` (see SECURITY.md).

**Residual risk:** Low for the verify-gate use case. Ordinary production
traffic is not covered by this check — for production auditing, rely on
the `ApplyGuardrail` CloudTrail **data event** (resource type
`AWS::Bedrock::Guardrail`, off by default; see CSR-010 in SECURITY.md) and
the `AWS/Bedrock/Guardrails` CloudWatch metrics (this repo's dashboard
stack). `InvokeModel`/`Converse` themselves are management events and show
that a call happened, not what a guardrail decided.

### T5 — Information disclosure: plaintext prompts/responses/PII in local result files

**Threat:** `run_benchmark.py`, `capture_trace.py`, and related scripts
write full model I/O and guardrail assessment JSON — including any
detected PII entity values — to `results/*.csv|json|log` in plaintext.

**Mitigation:** CSR-009 restricts the results directory to 0700 and each
written file to 0600 at write time (`scripts/_lib/secure_io.py`). This is
filesystem-permission hardening, not encryption at rest, and does not
protect data already copied elsewhere (e.g. attached to a support ticket,
committed accidentally despite `.gitignore`).

**Residual risk:** Medium if these scripts are run against real production
prompts rather than synthetic/benchmark prompts. Documented in SECURITY.md
with an explicit recommendation to treat `results/` as sensitive.

### T6 — Information disclosure: cross-account resource policy grants too broadly

**Threat:** The resource-based policy attached to the central guardrail
(`blog-guardrail-stack.ts`, `_attachResourcePolicy`) uses `Principal: { AWS: '*' }`
scoped down only by a `StringEquals: aws:PrincipalOrgID` condition. If that
condition were ever removed or misconfigured, the policy would grant
`bedrock:ApplyGuardrail`/`GetGuardrail` to any AWS principal globally, not
just the organization.

**Mitigation:** The condition is present in the current code. A dedicated
Jest test (`T6: resource policy scopes to the provided org id and does not
grant globally` in `cdk/test/synth.test.ts`) asserts that the synthesized
template contains the `aws:PrincipalOrgID` / `StringEquals` condition text
paired with the supplied org id, so a future edit that removes or weakens
the condition fails CI.

**Residual risk:** Low. The remaining gap is that the test asserts on
serialized template text (the policy document is embedded as a JSON string
inside a CloudFormation intrinsic, not a directly-assertable property tree)
rather than a structured property match — sufficient to catch the
regression, but a security reviewer may want a stronger structural
assertion if this pattern is reused elsewhere.

### T7 — Denial of service: guardrail throttling or misconfiguration blocks legitimate traffic

**Threat:** A denied-topic or content-filter rule configured too broadly
blocks legitimate business traffic org-wide (since Layer 1 auto-applies).

**Mitigation:** Outside this repo's code — this is a guardrail *content*
design question, not an infrastructure security question. The CloudWatch
dashboard (`blog-dashboard-stack.ts`) surfaces `InvocationsIntervened` and
error/throttle metrics so an operator can detect this, and alarms notify
an SNS topic when wired (CSR-007 fix). Detecting *content*-driven false
positives (as opposed to throttle/error alarms) requires product-level
monitoring outside this repo's scope.

**Residual risk:** Medium — mitigated by observability, not by automatic
rollback. A bad guardrail change still requires a human to notice and act.

### T8 — Elevation of privilege: CI/CD pipeline credential compromise

**Threat:** `.gitlab-ci.yml` uses long-lived AWS credentials stored as
CI/CD variables. If leaked (misconfigured job, malicious MR from a fork,
compromised runner), an attacker gains whatever permissions those
credentials carry — potentially including the ability to deploy/modify
the guardrail stacks or, if scoped too broadly, more.

**Mitigation:** Not implemented in code. Documented in SECURITY.md
(CSR-005) as a known limitation with OIDC federation recommended as the
production-strength alternative. The pipeline's `deploy-prod` stage is
`when: manual`, limiting blast radius of an accidental trigger but not of
a credential leak.

**Residual risk:** Medium-High if this pipeline is used as-is for a real
deployment without migrating to OIDC federation first.

### T9 — Elevation of privilege: member-account principal missing IAM grant, masking a misconfiguration

**Threat:** Without the member-account IAM grant documented in CSR-008
(example shown in the blog post; not shipped as a file), a member-account
principal calling `ApplyGuardrail` cross-account fails with
`AccessDeniedException` even when the resource policy is correctly
attached — this is a fail-closed outcome (safe), but the resulting
confusion could lead an operator to weaken the resource policy
(e.g. broadening the org-ID condition) to "fix" what is actually a
missing identity-side grant, which would be a real weakening.

**Mitigation:** CSR-008 documents both sides of the required grant
explicitly, specifically to prevent this "fix the wrong thing" failure
mode.

**Residual risk:** Low, given the documentation now exists — depends on
operators reading it before making changes.

## 5. Recommendations for formal review

This document identifies the threats and current mitigations, but the
following require a security engineer's judgment beyond what this repo's
code changes can determine:

1. Whether relying on `Null` (not `StringEquals`) for the default SCP
   (T1 / CSR-002) is an acceptable risk for your organization, or whether
   the pinned variant should be the default.
2. Whether the management-account IAM hygiene assumption in T2 needs to be
   backed by an actual SCP or permission boundary restricting who can
   detach/modify Organizations policies, rather than left as an
   operational assumption.
3. Whether the CI/CD credential model (T8) is acceptable for your
   deployment, or whether OIDC federation is a hard requirement before
   this pipeline touches any account that matters.
4. Any threats specific to your organization's actual account structure,
   OU layout, or existing SCP set that this generic model does not
   anticipate, since this repo was written as a standalone reference
   implementation, not against a specific customer environment.
