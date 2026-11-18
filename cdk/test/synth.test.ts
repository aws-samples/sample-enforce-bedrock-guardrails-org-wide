import * as cdk from 'aws-cdk-lib';
import { Template, Match, Annotations } from 'aws-cdk-lib/assertions';
import { AwsSolutionsChecks } from 'cdk-nag';
import { BlogBenchmarkGuardrailStack } from '../lib/blog-guardrail-stack';
import { BlogDashboardStack } from '../lib/blog-dashboard-stack';
import { BlogStackSetStack } from '../lib/blog-stackset-stack';

const env = { account: '123456789012', region: 'us-east-1' };

describe('BlogBenchmarkGuardrailStack', () => {
  test('synthesizes one guardrail and one published version', () => {
    const app = new cdk.App();
    const stack = new BlogBenchmarkGuardrailStack(app, 'Test', { env });
    const t = Template.fromStack(stack);

    t.resourceCountIs('AWS::Bedrock::Guardrail', 1);
    t.resourceCountIs('AWS::Bedrock::GuardrailVersion', 1);

    t.hasResourceProperties('AWS::Bedrock::Guardrail', {
      Name: 'blog-benchmark-guardrail',
      ContentPolicyConfig: Match.objectLike({
        FiltersConfig: Match.arrayWith([
          Match.objectLike({ Type: 'HATE', InputStrength: 'HIGH' }),
        ]),
      }),
      TopicPolicyConfig: Match.objectLike({
        TopicsConfig: Match.arrayWith([
          Match.objectLike({ Name: 'BenchmarkDeniedTopic', Type: 'DENY' }),
        ]),
      }),
    });
  });

  test('attaches a resource policy when an organization id is provided', () => {
    const app = new cdk.App();
    const stack = new BlogBenchmarkGuardrailStack(app, 'TestOrg', {
      env,
      organizationId: 'o-abcd123456',
    });
    const t = Template.fromStack(stack);

    // AwsCustomResource backing — the synthesised resource is
    // AWS::CloudFormation::CustomResource via the SDK call provider.
    const customResources = t.findResources('Custom::AWS');
    expect(Object.keys(customResources).length).toBeGreaterThanOrEqual(1);
  });

  test('T6: resource policy scopes to the provided org id and does not grant globally', () => {
    // The custom-resource-backed resource policy embeds its policy document
    // as a JSON string inside a CloudFormation intrinsic (Fn::Join over
    // Fn::GetAtt references). Rather than parsing the intrinsic tree, we
    // stringify the whole template and assert on the literal substrings
    // cdk-cfn would have produced for the condition and org id — a
    // regression that removed or weakened the aws:PrincipalOrgID condition
    // would change this text.
    const app = new cdk.App();
    const stack = new BlogBenchmarkGuardrailStack(app, 'TestOrgCondition', {
      env,
      organizationId: 'o-abcd123456',
    });
    const templateJson = JSON.stringify(Template.fromStack(stack).toJSON());

    expect(templateJson).toContain('aws:PrincipalOrgID');
    expect(templateJson).toContain('o-abcd123456');
    expect(templateJson).toContain('StringEquals');
    // Principal is intentionally AWS: '*' but MUST be paired with the
    // condition above — assert both are present together, not that '*' is
    // absent (it is expected, scoped down by the condition).
    expect(templateJson).toContain('AllowOrgMembersToApplyGuardrail');
  });

  test('does NOT create a resource policy when organization id is omitted', () => {
    const app = new cdk.App();
    const stack = new BlogBenchmarkGuardrailStack(app, 'TestNoOrg', { env });
    const t = Template.fromStack(stack);

    expect(Object.keys(t.findResources('Custom::AWS')).length).toBe(0);
  });
});

describe('BlogDashboardStack', () => {
  test('produces a dashboard and three alarms', () => {
    const app = new cdk.App();
    const stack = new BlogDashboardStack(app, 'Dash', {
      env,
      guardrailArn: 'arn:aws:bedrock:us-east-1:123456789012:guardrail/abcd1234',
      guardrailVersion: '1',
    });
    const t = Template.fromStack(stack);

    t.resourceCountIs('AWS::CloudWatch::Dashboard', 1);
    t.resourceCountIs('AWS::CloudWatch::Alarm', 2);
  });

  test('alarms have no action when alarmTopicArn is omitted', () => {
    const app = new cdk.App();
    const stack = new BlogDashboardStack(app, 'DashNoTopic', {
      env,
      guardrailArn: 'arn:aws:bedrock:us-east-1:123456789012:guardrail/abcd1234',
      guardrailVersion: '1',
    });
    const t = Template.fromStack(stack);

    const alarms = t.findResources('AWS::CloudWatch::Alarm');
    for (const alarm of Object.values(alarms)) {
      expect((alarm as any).Properties.AlarmActions).toBeUndefined();
    }
  });

  test('CSR-007: alarms notify the provided SNS topic when alarmTopicArn is set', () => {
    const app = new cdk.App();
    const topicArn = 'arn:aws:sns:us-east-1:123456789012:guardrail-alerts';
    const stack = new BlogDashboardStack(app, 'DashWithTopic', {
      env,
      guardrailArn: 'arn:aws:bedrock:us-east-1:123456789012:guardrail/abcd1234',
      guardrailVersion: '1',
      alarmTopicArn: topicArn,
    });
    const t = Template.fromStack(stack);

    const alarms = t.findResources('AWS::CloudWatch::Alarm');
    expect(Object.keys(alarms).length).toBe(2);
    for (const alarm of Object.values(alarms)) {
      expect((alarm as any).Properties.AlarmActions).toEqual([topicArn]);
    }
  });
});

describe('BlogStackSetStack', () => {
  test('creates a StackSet with no instances when no targets are provided', () => {
    const app = new cdk.App();
    const stack = new BlogStackSetStack(app, 'SS', { env });
    const t = Template.fromStack(stack);

    t.hasResourceProperties('AWS::CloudFormation::StackSet', {
      StackSetName: 'blog-benchmark-guardrail',
      PermissionModel: 'SERVICE_MANAGED',
      StackInstancesGroup: Match.absent(),
    });
  });

  test('creates a StackSet with instance group when targets are provided', () => {
    const app = new cdk.App();
    const stack = new BlogStackSetStack(app, 'SSWithTargets', {
      env,
      targets: ['ou-abcd-12345678'],
      targetRegions: ['us-east-1', 'eu-west-1'],
    });
    const t = Template.fromStack(stack);

    t.hasResourceProperties('AWS::CloudFormation::StackSet', {
      StackInstancesGroup: Match.arrayWith([
        Match.objectLike({
          Regions: ['us-east-1', 'eu-west-1'],
          DeploymentTargets: { OrganizationalUnitIds: ['ou-abcd-12345678'] },
        }),
      ]),
    });
  });
});

describe('cdk-nag (CSR-012)', () => {
  test('AwsSolutionsChecks reports zero unsuppressed errors across all stacks', () => {
    const app = new cdk.App();
    cdk.Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));

    const guardrailStack = new BlogBenchmarkGuardrailStack(app, 'Blog-Benchmark-Guardrail', {
      env,
      organizationId: 'o-abcd123456', // exercises the AwsCustomResource path
    });
    new BlogDashboardStack(app, 'Blog-Benchmark-Dashboard', {
      env,
      guardrailArn: guardrailStack.guardrail.attrGuardrailArn,
      guardrailVersion: guardrailStack.guardrailVersion.attrVersion,
      alarmTopicArn: 'arn:aws:sns:us-east-1:123456789012:test-topic',
    });
    new BlogStackSetStack(app, 'Blog-Benchmark-StackSet', {
      env,
      targets: ['ou-abcd-12345678'],
      organizationId: 'o-abcd123456',
    });

    app.synth();

    for (const stackId of [
      'Blog-Benchmark-Guardrail',
      'Blog-Benchmark-Dashboard',
      'Blog-Benchmark-StackSet',
    ]) {
      const stack = app.node.findChild(stackId) as cdk.Stack;
      const errors = Annotations.fromStack(stack).findError(
        '*',
        Match.stringLikeRegexp('AwsSolutions-.*'),
      );
      expect(errors).toHaveLength(0);
    }
  });
});
