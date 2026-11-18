import { Tags } from 'aws-cdk-lib';
import { IConstruct } from 'constructs';

/**
 * Apply standard project tags to every taggable resource in the scope.
 * Run from app.ts on each Stack so child resources inherit consistently.
 */
export function applyStandardTags(scope: IConstruct, opts: {
  project: string;
  environment: string;
  owner: string;
  costCenter?: string;
}): void {
  Tags.of(scope).add('Project', opts.project);
  Tags.of(scope).add('Environment', opts.environment);
  Tags.of(scope).add('Owner', opts.owner);
  Tags.of(scope).add('ManagedBy', 'cdk');
  if (opts.costCenter) {
    Tags.of(scope).add('CostCenter', opts.costCenter);
  }
}
