import { Module } from '@nestjs/common';
import { PythonJsonWorkerService } from './python-json-worker.service';

@Module({ providers: [PythonJsonWorkerService], exports: [PythonJsonWorkerService] })
export class PythonWorkerModule {}
