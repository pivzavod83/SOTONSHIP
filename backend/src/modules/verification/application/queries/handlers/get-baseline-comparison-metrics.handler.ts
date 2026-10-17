import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { BaselineComparisonRto, DeterministicBaselineMetricsRto, NeuroSymbolicMetricsRto } from '../../../presentation/rto/baseline-comparison.rto';
import { FormalProofStatusValue as Status } from '../../../domain/enums/formal-proof-status.enum';
import { GetBaselineComparisonMetricsQuery } from '../get-baseline-comparison-metrics.query';
import { analysisIsCurrent } from '../../../../../common/config/verification-policy';

@QueryHandler(GetBaselineComparisonMetricsQuery)
export class GetBaselineComparisonMetricsHandler implements IQueryHandler<GetBaselineComparisonMetricsQuery> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly repository: IVerificationRepository) {}
  async execute(): Promise<BaselineComparisonRto> {
    const stored = (await this.repository.findAll()).map((run) => run.toPrimitives());
    const rows = stored.filter(row => analysisIsCurrent(row.provenanceJson, row.proofScope));
    const average = (key: 'baselineAlignmentScore' | 'gnnAlignmentScore'): number =>
      rows.length ? rows.reduce((sum, row) => sum + row[key], 0) / rows.length : 0;
    const unknownModules = rows.filter((row) => row.formalProofStatus === Status.UNKNOWN_HALTED_LIMIT).length;
    return Object.assign(new BaselineComparisonRto(), {
      totalModules: stored.length, currentAnalyzedModules: rows.length, staleModules: stored.length - rows.length,
      completedProofs: rows.length - unknownModules, unknownModules,
      deterministicBaseline: Object.assign(new DeterministicBaselineMetricsRto(), {
        meanAlignmentScore: average('baselineAlignmentScore'), caughtBugs: rows.filter((row) => row.baselineCaughtBug).length,
      }),
      neuroSymbolic: Object.assign(new NeuroSymbolicMetricsRto(), {
        meanAlignmentScore: average('gnnAlignmentScore'), flaggedHighRiskModules: rows.filter((row) => row.gnnBugRiskScore >= 0.5).length,
        provenCounterexamples: rows.filter((row) => row.formalProofStatus === Status.SAT_COUNTEREXAMPLE_FOUND).length,
        provenSafeModules: rows.filter((row) => row.formalProofStatus === Status.UNSAT_PROVEN_SAFE).length,
      }),
      interpretation: 'Descriptive scores over current-engine analyses, not measured alignment accuracy or a held-out superiority benchmark. Stale analyses are excluded pending re-verification. UNSAT is restricted to each run’s explicit proofScope; UNKNOWN is not safe.',
    });
  }
}
