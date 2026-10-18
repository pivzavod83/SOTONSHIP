import { Injectable } from '@nestjs/common';
import { IMlBridge, MlVerificationInput } from '../../application/ports/ml-bridge';
import { VerificationAnalysis } from '../../domain/entities/verification-run';
import { PythonJsonWorkerService } from '../../../../common/infrastructure/python/python-json-worker.service';

@Injectable()
export class PythonMlBridgeService implements IMlBridge {
  constructor(private readonly worker: PythonJsonWorkerService) {}

  async verify(input: MlVerificationInput): Promise<VerificationAnalysis> {
    // Handlers validate aggregate and proof invariants before persistence.
    return await this.worker.execute('ml_engine.verify', input) as VerificationAnalysis;
  }
}
