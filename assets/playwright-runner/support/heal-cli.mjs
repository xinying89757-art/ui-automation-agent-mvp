import fs from 'node:fs';
import path from 'node:path';
import { gateProposal } from './heal.mjs';

const evidence = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const base = process.argv[4] || process.cwd();
const spec = fs.readFileSync(path.resolve(base, evidence.spec), 'utf8');
const proposal = fs.readFileSync(path.resolve(base, evidence.proposal), 'utf8');
const result = gateProposal(spec, proposal, evidence.message || '');
fs.mkdirSync(path.dirname(path.resolve(process.argv[3])), { recursive: true });
fs.writeFileSync(process.argv[3], JSON.stringify(result, null, 2));
