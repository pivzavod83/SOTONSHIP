import { Injectable } from '@nestjs/common';
import { PythonJsonWorkerService } from '../../../../common/infrastructure/python/python-json-worker.service';
import { IProgramMatchingEngine } from '../../application/ports/program-matching-engine';
import { MatchingRequestState } from '../../domain/value-objects/matching-request';

@Injectable()
export class PythonProgramMatchingService implements IProgramMatchingEngine {
  constructor(private readonly worker: PythonJsonWorkerService) {}

  match(input: MatchingRequestState): Promise<unknown> {
    return this.worker.execute('ml_engine.matching', input);
  }
}
