import { main } from './session.mjs';
await main([...process.argv.slice(2), '--check-only']);
