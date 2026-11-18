import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import {
  Dashboard,
  GraphWidget,
  GraphWidgetView,
  Metric,
  Stats,
  Alarm,
  ComparisonOperator,
  TreatMissingData,
  TextWidget,
} from 'aws-cdk-lib/aws-cloudwatch';
import { SnsAction } from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';

export interface BlogDashboardStackProps extends StackProps {
  /** ARN of the guardrail to chart. Pass via stack output / CfnImportValue. */
  readonly guardrailArn: string;

  /** Numeric guardrail version, e.g. '1'. */
  readonly guardrailVersion: string;

  /**
   * Optional SNS topic ARN to notify when alarms fire. If omitted, alarms
   * are still created and visible in CloudWatch, but no alarm action is
   * attached — no one is paged automatically.
   */
  readonly alarmTopicArn?: string;
}

/**
 * Production observability for the benchmark guardrail. Dashboard widgets
 * mirror the metrics documented at:
 *   https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-guardrails-cw-metrics.html
 *
 * Namespace: AWS/Bedrock/Guardrails
 * Dimensions used here: GuardrailArn + GuardrailVersion
 */
export class BlogDashboardStack extends Stack {
  public readonly dashboard: Dashboard;

  constructor(scope: Construct, id: string, props: BlogDashboardStackProps) {
    super(scope, id, props);

    const dims = {
      GuardrailArn: props.guardrailArn,
      GuardrailVersion: props.guardrailVersion,
    };

    const namespace = 'AWS/Bedrock/Guardrails';

    const m = (metricName: string, label: string, statistic: string = Stats.SUM) =>
      new Metric({
        namespace,
        metricName,
        dimensionsMap: dims,
        statistic,
        period: Duration.minutes(5),
        label,
      });

    const invocations = m('Invocations', 'Invocations');
    const intervened = m('InvocationsIntervened', 'Interventions');
    const clientErrors = m('InvocationClientErrors', 'Client errors');
    const serverErrors = m('InvocationServerErrors', 'Server errors');
    const throttles = m('InvocationThrottles', 'Throttles');
    const latencyP50 = m('InvocationLatency', 'p50 latency (ms)', Stats.percentile(50));
    const latencyP99 = m('InvocationLatency', 'p99 latency (ms)', Stats.percentile(99));

    this.dashboard = new Dashboard(this, 'BlogGuardrailDashboard', {
      dashboardName: 'blog-benchmark-guardrail',
    });

    this.dashboard.addWidgets(
      new TextWidget({
        markdown: [
          '# Benchmark guardrail — production dashboard',
          '',
          `Guardrail: \`${props.guardrailArn}\``,
          `Version: \`${props.guardrailVersion}\``,
          '',
          'Source: AWS/Bedrock/Guardrails CloudWatch namespace.',
        ].join('\n'),
        width: 24,
        height: 3,
      }),
    );

    this.dashboard.addWidgets(
      new GraphWidget({
        title: 'Invocations vs interventions',
        width: 12,
        height: 6,
        view: GraphWidgetView.TIME_SERIES,
        left: [invocations, intervened],
      }),
      new GraphWidget({
        title: 'Latency (p50 / p99)',
        width: 12,
        height: 6,
        left: [latencyP50, latencyP99],
        leftYAxis: { min: 0 },
      }),
    );

    this.dashboard.addWidgets(
      new GraphWidget({
        title: 'Errors and throttles',
        width: 24,
        height: 6,
        left: [clientErrors, serverErrors, throttles],
      }),
    );

    // Alarms — created regardless of action target so they're discoverable
    // in the CloudWatch console.
    const throttleAlarm = new Alarm(this, 'GuardrailThrottleAlarm', {
      metric: throttles,
      threshold: 1,
      evaluationPeriods: 3,
      comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
      alarmDescription:
        'Bedrock guardrail throttles detected. Investigate request volume or open a quota increase.',
      alarmName: 'blog-benchmark-guardrail-throttles',
    });

    const serverErrorAlarm = new Alarm(this, 'GuardrailServerErrorAlarm', {
      metric: serverErrors,
      threshold: 5,
      evaluationPeriods: 3,
      comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Sustained server-side errors from Bedrock guardrail evaluation.',
      alarmName: 'blog-benchmark-guardrail-server-errors',
    });

    // CSR-007: alarmTopicArn was previously accepted but never wired to an
    // alarm action, so alarms fired silently with no one paged. Wire both
    // alarms to the supplied SNS topic when provided.
    if (props.alarmTopicArn) {
      const topic = Topic.fromTopicArn(this, 'AlarmTopic', props.alarmTopicArn);
      const action = new SnsAction(topic);
      throttleAlarm.addAlarmAction(action);
      serverErrorAlarm.addAlarmAction(action);
    }
  }
}
