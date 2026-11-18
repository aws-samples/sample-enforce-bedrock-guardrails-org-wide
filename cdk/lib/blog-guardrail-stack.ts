import {
  Stack,
  StackProps,
  CfnOutput,
  RemovalPolicy,
  Duration,
  custom_resources as cr,
} from 'aws-cdk-lib';
import { CfnGuardrail, CfnGuardrailVersion } from 'aws-cdk-lib/aws-bedrock';
import { PolicyStatement, Effect } from 'aws-cdk-lib/aws-iam';
import { NagSuppressions } from 'cdk-nag';
import { Construct } from 'constructs';

export interface BlogBenchmarkGuardrailStackProps extends StackProps {
  /**
   * Optional AWS Organization ID. When supplied, a resource-based policy is
   * attached to the guardrail granting `bedrock:ApplyGuardrail` to all
   * principals in that organization. Required for the org-level enforcement
   * pattern (Bedrock Organizations policy referencing this guardrail).
   *
   * Format: `o-xxxxxxxxxx` (10-character lowercase + digits).
   *
   * If omitted, the guardrail is single-account-scoped only.
   */
  readonly organizationId?: string;

  /**
   * Override the deployed guardrail name. Useful when running multiple
   * benchmark variants in the same account.
   * @default 'blog-benchmark-guardrail'
   */
  readonly guardrailName?: string;
}

/**
 * Benchmark guardrail used by the blog post's measurement code.
 *
 * Production hardening:
 *   - Versioned (CfnGuardrailVersion) so the org policy and the SCP can pin
 *     to a numeric version. DRAFT is rejected by both.
 *   - Optional resource-based policy via AwsCustomResource → bedrock:Put-
 *     ResourcePolicy. Required when other org accounts will call
 *     ApplyGuardrail against this guardrail.
 *   - Removal policy DESTROY so `cdk destroy` leaves no orphans, but the
 *     CfnGuardrailVersion is retained on update (the construct enforces
 *     replace-on-change semantics correctly out of the box).
 */
export class BlogBenchmarkGuardrailStack extends Stack {
  public readonly guardrail: CfnGuardrail;
  public readonly guardrailVersion: CfnGuardrailVersion;

  constructor(scope: Construct, id: string, props: BlogBenchmarkGuardrailStackProps = {}) {
    super(scope, id, props);

    this.guardrail = new CfnGuardrail(this, 'BenchGuardrail', {
      name: props.guardrailName ?? 'blog-benchmark-guardrail',
      description: 'Benchmarking guardrail for the org-wide remediation blog post',
      blockedInputMessaging: 'Blocked by benchmark guardrail.',
      blockedOutputsMessaging: 'Output blocked by benchmark guardrail.',

      contentPolicyConfig: {
        filtersConfig: [
          { type: 'HATE', inputStrength: 'HIGH', outputStrength: 'HIGH' },
          { type: 'PROMPT_ATTACK', inputStrength: 'HIGH', outputStrength: 'NONE' },
        ],
      },
      topicPolicyConfig: {
        topicsConfig: [
          {
            name: 'BenchmarkDeniedTopic',
            type: 'DENY',
            definition:
              "Requests to write someone's university assignments, exams, or other graded work for them.",
            examples: [
              'Write my CS101 assignment for me.',
              'Give me the answers to the final exam for unit XYZ.',
            ],
          },
        ],
      },
      sensitiveInformationPolicyConfig: {
        piiEntitiesConfig: [{ type: 'EMAIL', action: 'BLOCK' }],
      },
    });
    this.guardrail.applyRemovalPolicy(RemovalPolicy.DESTROY);

    this.guardrailVersion = new CfnGuardrailVersion(this, 'BenchGuardrailVersion', {
      guardrailIdentifier: this.guardrail.attrGuardrailId,
      description: 'v1 — benchmarking',
    });

    if (props.organizationId) {
      this._attachResourcePolicy(props.organizationId);
    }

    // Outputs consumed by scripts/run_benchmark.py and friends.
    new CfnOutput(this, 'GuardrailId', {
      value: this.guardrail.attrGuardrailId,
      description: 'export GUARDRAIL_ID=<this>',
      exportName: `${this.stackName}-GuardrailId`,
    });
    new CfnOutput(this, 'GuardrailVersion', {
      value: this.guardrailVersion.attrVersion,
      description: 'export GUARDRAIL_VERSION=<this>',
      exportName: `${this.stackName}-GuardrailVersion`,
    });
    new CfnOutput(this, 'GuardrailArn', {
      value: this.guardrail.attrGuardrailArn,
      exportName: `${this.stackName}-GuardrailArn`,
    });
  }

  /**
   * Bedrock guardrail resource-based policies are not yet a first-class
   * CloudFormation resource; manage them via AwsCustomResource so the IaC
   * lifecycle still owns create / update / delete.
   */
  private _attachResourcePolicy(organizationId: string): void {
    const policyDoc = {
      Version: '2012-10-17',
      Statement: [
        {
          Sid: 'AllowOrgMembersToApplyGuardrail',
          Effect: 'Allow',
          Principal: { AWS: '*' },
          Action: [
            'bedrock:ApplyGuardrail',
            'bedrock:GetGuardrail',
          ],
          Resource: this.guardrail.attrGuardrailArn,
          Condition: {
            StringEquals: { 'aws:PrincipalOrgID': organizationId },
          },
        },
      ],
    };

    new cr.AwsCustomResource(this, 'GuardrailResourcePolicy', {
      onCreate: {
        service: 'bedrock',
        action: 'putResourcePolicy',
        parameters: {
          resourceArn: this.guardrail.attrGuardrailArn,
          policy: JSON.stringify(policyDoc),
        },
        physicalResourceId: cr.PhysicalResourceId.of(
          `${this.guardrail.attrGuardrailId}-resource-policy`,
        ),
      },
      onUpdate: {
        service: 'bedrock',
        action: 'putResourcePolicy',
        parameters: {
          resourceArn: this.guardrail.attrGuardrailArn,
          policy: JSON.stringify(policyDoc),
        },
        physicalResourceId: cr.PhysicalResourceId.of(
          `${this.guardrail.attrGuardrailId}-resource-policy`,
        ),
      },
      onDelete: {
        service: 'bedrock',
        action: 'deleteResourcePolicy',
        parameters: {
          resourceArn: this.guardrail.attrGuardrailArn,
        },
        ignoreErrorCodesMatching: 'ResourceNotFoundException',
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: [
            'bedrock:PutResourcePolicy',
            'bedrock:DeleteResourcePolicy',
            'bedrock:GetResourcePolicy',
          ],
          resources: [this.guardrail.attrGuardrailArn],
        }),
      ]),
      installLatestAwsSdk: false,
      timeout: Duration.minutes(2),
    });

    // CSR-012 / cdk-nag AwsSolutions-IAM4: AwsCustomResource provisions a
    // stack-level singleton Lambda (construct id starting with "AWS...",
    // a sibling of GuardrailResourcePolicy, not a child of it) to back the
    // bedrock:PutResourcePolicy call, since that API has no native
    // CloudFormation resource type. CDK attaches the AWS-managed
    // AWSLambdaBasicExecutionRole (CloudWatch Logs write only) to that
    // singleton's service role, with no supported override point short of
    // re-implementing AwsCustomResource. Suppressed at the stack level
    // because the violating construct is a stack-level singleton, not a
    // child of GuardrailResourcePolicy. The resource-policy-granting
    // permissions on the singleton are separately scoped to
    // bedrock:PutResourcePolicy / DeleteResourcePolicy / GetResourcePolicy
    // on this one guardrail ARN (see the `policy:` prop above) — this
    // suppression only concerns the unrelated basic-execution logging
    // permission.
    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-IAM4',
        reason:
          "AwsCustomResource's internally-provisioned singleton Lambda " +
          'service role uses the AWS-managed AWSLambdaBasicExecutionRole ' +
          '(CloudWatch Logs write only) with no supported override point. ' +
          'This singleton is only referenced from GuardrailResourcePolicy ' +
          'in this stack.',
        appliesTo: ['Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'],
      },
    ]);
  }
}
