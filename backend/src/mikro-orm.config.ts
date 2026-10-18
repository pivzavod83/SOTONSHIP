import { defineConfig } from '@mikro-orm/postgresql';
import { Migrator } from '@mikro-orm/migrations';
import { SeedManager } from '@mikro-orm/seeder';
import { config as loadEnv } from 'dotenv';
import { resolve } from 'node:path';

const baseDir = resolve(__dirname, '..');
loadEnv({ path: resolve(baseDir, '.env') });
loadEnv({ path: resolve(baseDir, '../.env') });

export default defineConfig({
  baseDir,
  clientUrl: process.env.DATABASE_URL ?? 'postgresql://verifier:verifier_local@localhost:5432/neuro_symbolic',
  entities: ['dist/**/entities/*.entity.js'],
  entitiesTs: ['src/**/entities/*.entity.ts'],
  extensions: [Migrator, SeedManager],
  migrations: {
    path: 'dist/common/migrations', pathTs: 'src/common/migrations',
    glob: '!(*.d).{js,ts}', transactional: true, allOrNothing: true,
    safe: true, dropTables: false,
  },
  seeder: {
    path: 'dist/common/seeders', pathTs: 'src/common/seeders',
    defaultSeeder: 'InitialVerificationSeeder', glob: '!(*.d).{js,ts}',
  },
  debug: process.env.DB_DEBUG === 'true',
});
