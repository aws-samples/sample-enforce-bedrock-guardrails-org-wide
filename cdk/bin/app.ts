#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';
import { BlogBenchmarkGuardrailStack } from '../lib/blog-guardrail-stack';
import { BlogDashboardStack } from '../lib/blog-dashboard-stack';
import { BlogStackSetStack } from '../lib/blog-stackset-stack';
import { applyStandardTags } from '../lib/tagging';

const app = new cdk.App();

// CSR-012: run the AWS Solutions rule pack against every stack in this app
// as part of every synth. Set CDK_NAG=0 to skip (e.g. for quick iteration);
// on by default so `cdk synth` / CI always surfaces findings as synth-time
// errors/warnings (nothing is written to the deployed template).
if (process.env.CDK_NAG !== '0') {
  cdk.Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));
}

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
};

const orgId = process.env.AWS_ORG_ID; // o-xxxxxxxxxx (optional)

// ─── Single-region benchmark guardrail (always deployed) ────────────────────
const guardrailStack = new BlogBenchmarkGuardrailStack(app, 'Blog-Benchmark-Guardrail', {
  env,
  description:
    'Benchmark guardrail used by the blog post measurement scripts. ' +
    (orgId ? `Resource policy grants bedrock:ApplyGuardrail to org ${orgId}.` : 'Single-account scope.'),
  organizationId: orgId,
});

// ─── Dashboard (always deployed alongside the guardrail) ────────────────────
new BlogDashboardStack(app, 'Blog-Benchmark-Dashboard', {
  env,
  description: 'CloudWatch dashboard + alarms for the benchmark guardrail.',
  guardrailArn: guardrailStack.guardrail.attrGuardrailArn,
  guardrailVersion: guardrailStack.guardrailVersion.attrVersion,
  // Set ALARM_TOPIC_ARN to an existing SNS topic ARN so throttle/error
  // alarms actually notify someone (see CSR-007 in SECURITY.md).
  alarmTopicArn: process.env.ALARM_TOPIC_ARN,
});

// ─── Multi-region StackSet (deploy from management / delegated admin only) ──
//
// Set CDK_DEPLOY_STACKSET=1 to include this stack in `cdk deploy --all`.
// Otherwise it's still synthesisable for review but not deployed by default.
if (process.env.CDK_DEPLOY_STACKSET === '1') {
  new BlogStackSetStack(app, 'Blog-Benchmark-StackSet', {
    env,
    description: 'Multi-region StackSet rollout of the benchmark guardrail.',
    targetRegions: (process.env.CDK_TARGET_REGIONS ?? 'us-east-1,us-west-2').split(','),
    targets: process.env.CDK_TARGETS ? process.env.CDK_TARGETS.split(',') : [],
    permissionModel:
      (process.env.CDK_PERMISSION_MODEL as 'SERVICE_MANAGED' | 'SELF_MANAGED' | undefined) ??
      'SERVICE_MANAGED',
    organizationId: orgId,
  });
}

// ─── Standard project tags on every stack ───────────────────────────────────
const standardTags = {
  project: 'bedrock-guardrails-blog',
  environment: process.env.ENVIRONMENT ?? 'sandbox',
  owner: process.env.OWNER ?? 'tam-blog-author',
  costCenter: process.env.COST_CENTER,
};
for (const child of app.node.children) {
  if (cdk.Stack.isStack(child)) {
    applyStandardTags(child, standardTags);
  }
}
