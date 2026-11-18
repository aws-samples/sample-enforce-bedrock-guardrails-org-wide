# Static artifacts

One JSON document the blog post links to. It is not imported by the CDK
app — that's deliberate, because it is applied by AWS Organizations, not
CloudFormation, and by a different caller.

| File | Applied by | Caller |
| --- | --- | --- |
| `bedrock-organizations-policy.json` | `aws organizations create-policy --type BEDROCK_POLICY` | Management account or delegated admin |

> **Not in this repository:** the service control policy (SCP) backstop
> and the member-account IAM policy for `bedrock:ApplyGuardrail` are
> described in the accompanying blog post, not shipped here as files.
> Those documents change IAM authorization behavior in your Organization
> and must be reviewed, adapted, and validated by your own security team
> before use.

## Bedrock Organizations policy

`bedrock-organizations-policy.json` is the document that activates org-wide
guardrail enforcement. It is deliberately kept free of comments —
declarative policy documents (`BEDROCK_POLICY`) use a strict, fixed schema
and the API rejects unrecognized top-level keys, so do not add a `_comment`
field before applying it with `create-policy`.

Replace `<<GUARDRAIL_ARN>>` and `<<GUARDRAIL_VER>>` with the values from the
CDK stack output before applying:

```bash
aws organizations create-policy \
    --name BlogBedrockGuardrail \
    --type BEDROCK_POLICY \
    --content file://bedrock-organizations-policy.json
```

Then attach to the target OU(s) with `aws organizations attach-policy`.
Validate the result with `scripts/verify_effective_policy.py`.

The guardrail must:
1. Be **versioned** — `DRAFT` is rejected.
2. Live in the management account or a delegated admin (the policy can
   reference only management-account-owned guardrails as of April 2026).
3. Carry a **resource-based policy** allowing `bedrock:ApplyGuardrail`
   from the org. The CDK stack attaches that policy automatically when
   you set `AWS_ORG_ID=o-xxxxxxxxxx` in the environment.

### Known gap — the resource-based policy alone is not enough (CSR-008)

Cross-account permission on AWS is normally two-sided: a resource-based
policy on the resource (what the CDK stack attaches above) AND an
identity-based policy on the calling principal. The resource-based policy
above only satisfies the resource side. **Member-account roles also need
`bedrock:ApplyGuardrail` (and typically `bedrock:GetGuardrail`) granted in
their own IAM policy**, scoped to the central guardrail's ARN. Without
this, calls from member accounts fail with `AccessDeniedException` even
though the resource policy is correctly attached, because IAM evaluates
both sides and denies if either is missing. An example identity-side
policy is shown in the blog post; author and review your own for your
Organization.

## Apply order (recommended)

> **This is sample code for learning the pattern, not a production rollout
> runbook.** Before applying any of this to an OU that contains production
> workloads, run it through your own security review, in a sandbox
> Organization.

1. Deploy the CDK guardrail and dashboard (`cdk deploy --all`) in a
   **sandbox** AWS account.
2. Apply the Bedrock Organizations policy and attach to a **sandbox OU**.
3. Validate with `scripts/verify_effective_policy.py`.
4. Run `scripts/run_benchmark.py` from a workload account in that OU to
   confirm the org policy is active.
5. Do not attach the policy to a production OU without your own
   independent security review, threat model, and change-management
   process. See [`../SECURITY.md`](../SECURITY.md) for what this sample
   does not cover.
