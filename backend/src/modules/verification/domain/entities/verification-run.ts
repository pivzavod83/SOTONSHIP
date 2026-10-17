import { DomainException } from '../../../../common/exceptions/domain.exception';
import { JsonObject, JsonValue } from '../../../../common/value-objects/json-value';
import { VerificationCategory } from '../enums/verification-category.enum';
import { FormalProofStatusValue } from '../enums/formal-proof-status.enum';
import { CodeSnippet } from '../value-objects/code-snippet';
import { FormalProofStatus } from '../value-objects/formal-proof-status';
import { ModuleName } from '../value-objects/module-name';
import { RiskScore } from '../value-objects/risk-score';
import { VerificationId } from '../value-objects/verification-id';

export interface VerificationAnalysis {
  gnnAlignmentScore: number;
  gnnBugRiskScore: number;
  baselineAlignmentScore: number;
  baselineCaughtBug: boolean;
  formalProofStatus: FormalProofStatusValue;
  bugCategory: string;
  fStringSummary: string;
  cpgGraphJson: JsonObject;
  counterexamplesJson: JsonValue[];
  isFailureLimitCase: boolean;
  proofScope: JsonObject;
  provenanceJson: JsonObject;
}

export interface VerificationRunProps extends VerificationAnalysis {
  id: string;
  moduleName: string;
  category: VerificationCategory;
  cobolSource: string;
  javaSource: string;
  patchedJavaSource: string;
  createdAt: Date;
  updatedAt: Date;
  version: number;
}

export type VerificationEvent = import('../events/verification-completed.event').VerificationCompletedEvent
  | import('../events/discrepancy-detected.event').DiscrepancyDetectedEvent;

/** Pure aggregate; persistence and HTTP models never enter this layer. */
export class VerificationRun {
  readonly id: VerificationId;
  readonly moduleName: ModuleName;
  readonly formalProofStatus: FormalProofStatus;
  protected readonly state: VerificationRunProps;
  protected readonly events: VerificationEvent[] = [];

  constructor(props: VerificationRunProps) {
    this.id = new VerificationId(props.id);
    this.moduleName = new ModuleName(props.moduleName);
    this.formalProofStatus = new FormalProofStatus(props.formalProofStatus);
    new CodeSnippet(props.cobolSource);
    new CodeSnippet(props.javaSource);
    // An unsupported module may have no patch candidate.
    if (props.patchedJavaSource) new CodeSnippet(props.patchedJavaSource);
    new RiskScore(props.gnnAlignmentScore);
    new RiskScore(props.gnnBugRiskScore);
    new RiskScore(props.baselineAlignmentScore);
    if (!Object.values(VerificationCategory).includes(props.category)) throw new DomainException('Unsupported category.');
    if (props.isFailureLimitCase && props.formalProofStatus !== FormalProofStatusValue.UNKNOWN_HALTED_LIMIT) {
      throw new DomainException('An external limit case cannot claim a completed proof.');
    }
    if (!Array.isArray(props.counterexamplesJson)) throw new DomainException('Counterexamples must be an array.');
    if (props.formalProofStatus === FormalProofStatusValue.SAT_COUNTEREXAMPLE_FOUND && !props.counterexamplesJson.length) {
      throw new DomainException('A SAT result requires a concrete counterexample.');
    }
    if (typeof props.baselineCaughtBug !== 'boolean' || typeof props.isFailureLimitCase !== 'boolean') {
      throw new DomainException('Analysis flags must be boolean.');
    }
    for (const value of [props.cpgGraphJson, props.proofScope, props.provenanceJson]) {
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new DomainException('Analysis metadata must be JSON objects.');
    }
    if (typeof props.fStringSummary !== 'string' || typeof props.bugCategory !== 'string') {
      throw new DomainException('Analysis explanations must be strings.');
    }
    if (props.formalProofStatus === FormalProofStatusValue.UNSAT_PROVEN_SAFE) assertSupportedProof(props);
    this.state = structuredClone({ ...props, moduleName: this.moduleName.value });
  }

  toPrimitives(): VerificationRunProps { return structuredClone(this.state); }
  pullEvents(): VerificationEvent[] { return this.events.splice(0); }
}

export function assertSupportedProof(analysis: Pick<VerificationAnalysis, 'proofScope' | 'counterexamplesJson'>): void {
  const scope = analysis.proofScope;
  const bounds = scope.inputAmountCents;
  if (scope.supported !== true || scope.bounded !== true || !bounds || typeof bounds !== 'object' || Array.isArray(bounds)
    || typeof bounds.min !== 'number' || typeof bounds.max !== 'number'
    || !Number.isSafeInteger(bounds.min) || !Number.isSafeInteger(bounds.max) || bounds.min > bounds.max
    || analysis.counterexamplesJson.length !== 0) {
    throw new DomainException('UNSAT requires a supported, bounded proof with no counterexamples.', 'verification.invalid_proof_scope');
  }
}
